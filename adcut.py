#!/usr/bin/env python3
"""Cut the ad breaks out of game recordings, found by a sports-trained BiLSTM-CRF on a silence-of-the-spams
GPU worker, leaving a short beep where each break was. Crew-read sponsor lines stay in.

Usage:
  adcut.py <recording> <ads> <trimmed> [--enhanced=<dir>]
  adcut.py --watch <recordings> <enhanced> <ads> <trimmed>

Options:
  -h --help         Show this screen.
  --enhanced=<dir>  Cut the enhanced copy of the recording from here when it exists.
  --watch           Cut each recording in <recordings>, newest first, and keep watching. A trimmed copy is cut
                    again once an enhanced copy newer than it appears. Pauses while a game is recording.

The worker's transcript, music timeline and the breaks found go to <ads>/<name>.{transcript,music,breaks}.json.
"""

import glob, json, os, sys, time
from pathlib import Path

import httpx2 as httpx
from docopt import docopt
from mutagen.mp3 import MP3

from config import setting
from pausing import PARTIAL, Recording, idle, runPausing, waitWhile

MERGE_GAP_SEC = 20
MIN_BREAK_SEC = 10
BEEP_SEC, BEEP_HZ, BEEP_DB = 0.4, 1000, -16
FADE_SEC = 0.05
WATCH_SEC = 60
RETRY_SEC = 1800
WORKER_TIMEOUT = httpx.Timeout(30, read=3600)
MIN_SPEAKERS, MAX_SPEAKERS, CLUSTERING_THRESHOLD = 1, 5, 0.7

class Worker:
  """The calls adcut makes to a silence-of-the-spams GPU worker."""

  def __init__(self, url, transport=None):
    self.client = httpx.Client(base_url=url, timeout=WORKER_TIMEOUT, transport=transport)

  def post(self, path, **kwargs):
    response = self.client.post(path, **kwargs)
    response.raise_for_status()
    return response.json()

  def upload(self, path, endpoint, data):
    with open(path, "rb") as f:
      return self.post(endpoint, files={"file": (os.path.basename(path), f, "audio/mpeg")}, data=data)

  def transcribe(self, path):
    return self.upload(path, "/v1/audio/transcriptions", {
      "language": "en", "diarize": "true", "min_speakers": MIN_SPEAKERS, "max_speakers": MAX_SPEAKERS,
      "clustering_threshold": CLUSTERING_THRESHOLD})

  def music(self, path):
    return self.upload(path, "/v1/audio/music/upload", {})

  def classify(self, segments, music):
    return self.post("/v1/bilstm/classify", json={
      "segments": segments, "music_timeline": music,
      "model_path": setting("SHARK_ADCUT_MODEL"), "embedding_model": setting("SHARK_ADCUT_EMBEDDER")})["labels"]

def segments(transcript):
  return [{"start_time": s["start"], "end_time": s["end"], "text": s["text"], "speaker": s.get("speaker", "SPEAKER_00")}
          for s in transcript["segments"]]

def breaks(segs, labels, mergeGap=MERGE_GAP_SEC, minLength=MIN_BREAK_SEC):
  """[start, end] seconds of each break: ad segments joined across gaps up to mergeGap, then those under minLength dropped."""
  spans = []
  for seg, label in zip(segs, labels, strict=True):
    if label != "ad":
      continue
    if spans and seg["start_time"] - spans[-1][1] <= mergeGap:
      spans[-1][1] = max(spans[-1][1], seg["end_time"])
    else:
      spans.append([seg["start_time"], seg["end_time"]])
  return [s for s in spans if s[1] - s[0] >= minLength]

def keeps(cuts, duration):
  """The spans of a recording of the given duration left once the cuts are taken out."""
  spans, at = [], 0.0
  for start, end in cuts:
    if start > at:
      spans.append((at, min(start, duration)))
    at = max(at, end)
  if at < duration:
    spans.append((at, duration))
  return [(a, b) for a, b in spans if b - a > 2 * FADE_SEC]

def cutCommand(source, spans, output, rate, bitrate):
  """ffmpeg joining the spans of source with a beep between each, re-encoded to an MP3 at output."""
  parts, chains = [], []
  for i, (start, end) in enumerate(spans):
    chains.append("[0:a]atrim=start=%.3f:end=%.3f,asetpts=PTS-STARTPTS,afade=t=in:d=%s,afade=t=out:st=%.3f:d=%s[k%d]"
                  % (start, end, FADE_SEC, end - start - FADE_SEC, FADE_SEC, i))
    parts.append("[k%d]" % i)
    if i < len(spans) - 1:
      chains.append("sine=f=%d:d=%s:r=%d,volume=%ddB,afade=t=in:d=%s,afade=t=out:st=%s:d=%s[b%d]"
                    % (BEEP_HZ, BEEP_SEC, rate, BEEP_DB, FADE_SEC, BEEP_SEC - FADE_SEC, FADE_SEC, i))
      parts.append("[b%d]" % i)
  chains.append("%sconcat=n=%d:v=0:a=1,aformat=channel_layouts=mono[out]" % ("".join(parts), len(parts)))
  return ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", source, "-filter_complex", ";".join(chains),
          "-map", "[out]", "-map_metadata", "0", "-id3v2_version", "3",
          "-c:a", "libmp3lame", "-b:a", "%dk" % bitrate, "-f", "mp3", output]

def sidecar(ads, recording, kind):
  return os.path.join(ads, "%s.%s.json" % (Path(recording).stem, kind))

def cached(path, compute):
  if os.path.exists(path):
    return json.loads(Path(path).read_text())
  value = compute()
  Path(path + PARTIAL).write_text(json.dumps(value))
  os.replace(path + PARTIAL, path)
  return value

def detect(recording, ads, worker, busy=idle):
  """The breaks in a recording, asking the worker only for what isn't already saved in ads."""
  waitWhile(busy)
  transcript = cached(sidecar(ads, recording, "transcript"), lambda: worker.transcribe(recording))
  waitWhile(busy)
  music = cached(sidecar(ads, recording, "music"), lambda: worker.music(recording))
  waitWhile(busy)
  segs = segments(transcript)
  return cached(sidecar(ads, recording, "breaks"), lambda: breaks(segs, worker.classify(segs, music)))

def source(recording, enhanced):
  copy = os.path.join(enhanced, os.path.basename(recording)) if enhanced else None
  return copy if copy and os.path.isfile(copy) else recording

def cut(recording, ads, trimmed, worker, enhanced=None, busy=idle):
  t0, cuts = time.monotonic(), detect(recording, ads, worker, busy)
  src = source(recording, enhanced)
  info = MP3(src).info
  output = os.path.join(trimmed, os.path.basename(recording))
  try:
    waitWhile(busy)
    runPausing(cutCommand(src, keeps(cuts, info.length), output + PARTIAL, info.sample_rate, info.bitrate // 1000), busy)
    os.replace(output + PARTIAL, output)
  finally:
    if os.path.exists(output + PARTIAL):
      os.remove(output + PARTIAL)
  print("%s: cut %d breaks (%.0f s) from the %s copy in %.0f s" % (
    os.path.basename(recording), len(cuts), sum(b - a for a, b in cuts),
    "enhanced" if src != recording else "raw", time.monotonic() - t0), flush=True)

def pending(recordings, enhanced, trimmed):
  """Recordings without a trimmed copy, or whose source is newer than it, newest first."""
  def stale(path):
    copy = os.path.join(trimmed, os.path.basename(path))
    return not os.path.exists(copy) or os.path.getmtime(source(path, enhanced)) > os.path.getmtime(copy)
  return sorted((p for p in glob.glob(os.path.join(glob.escape(recordings), "*.mp3")) if stale(p)),
                key=os.path.getmtime, reverse=True)

def watch(recordings, enhanced, ads, trimmed, worker):
  for d in (ads, trimmed):
    os.makedirs(d, exist_ok=True)
    for stale in glob.glob(os.path.join(glob.escape(d), "*" + PARTIAL)):
      os.remove(stale)
  retryAt, busy = {}, Recording(recordings)
  while True:
    todo = [p for p in pending(recordings, enhanced, trimmed) if retryAt.get(p, 0) <= time.monotonic()]
    if not todo:
      time.sleep(WATCH_SEC)
      continue
    try:
      cut(todo[0], ads, trimmed, worker, enhanced, busy)
    except Exception as err:
      print("Couldn't cut %s, retrying in %d s: %s" % (todo[0], RETRY_SEC, err), flush=True)
      retryAt[todo[0]] = time.monotonic() + RETRY_SEC

if __name__ == "__main__":
  arguments = docopt(__doc__, version="Shark Adcut 0.1")
  if not setting("SHARK_GPU_WORKER_URL"):
    sys.exit("Set SHARK_GPU_WORKER_URL to the silence-of-the-spams GPU worker, e.g. http://turnpike.lan:8090")
  worker = Worker(setting("SHARK_GPU_WORKER_URL"))
  if arguments["--watch"]:
    watch(arguments["<recordings>"], arguments["<enhanced>"], arguments["<ads>"], arguments["<trimmed>"], worker)
  else:
    os.makedirs(arguments["<ads>"], exist_ok=True)
    os.makedirs(arguments["<trimmed>"], exist_ok=True)
    cut(arguments["<recording>"], arguments["<ads>"], arguments["<trimmed>"], worker, arguments["--enhanced"])
