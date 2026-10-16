#!/usr/bin/env python3
"""Clean up game recordings: notch out mains hum, reduce noise with DeepFilterNet3 by at most 12 dB, and
regenerate the highs of narrowband recordings with LavaSR v2. The recording's own audio is kept below its band edge.

Usage:
  enhance.py <recording> <output>
  enhance.py --watch <recordings> <enhanced>

Options:
  -h --help   Show this screen.
  --watch     Enhance each recording in <recordings> without a copy in <enhanced>, newest first, and keep watching.
"""

import glob, math, os, queue, subprocess, tempfile, threading, time

import numpy as np
import soundfile as sf
from docopt import docopt
from scipy.signal import resample_poly, stft, welch

from config import setting

SR = 48000
BLOCK = SR * 60
MAINS_HZ = 60.0
HUM_MAX_HZ = 3000
HUM_MIN_DB = 8.0
HUM_MIN_FRACTION = 0.8
EDGE_DB = 30
ATTEN_LIM_DB = 12
DEEP_FILTER_PAD = SR // 10
LAVA_REPO, LAVA_REVISION = "YatharthS/LavaSR", "b98dc8be472da45ab7b6346ad7997e1dfeb5911d"
LAVA_MAX_EDGE_HZ = 12000
LAVA_MAX_CUTOFF_HZ = 7000
LAVA_CUTOFF_MARGIN_HZ = 150
CROSSOVER_HZ = 500
TORCH_THREADS = 1
DFN_FRAME, LAVA_FRAME = 480, 3 * 512
FRAME = math.lcm(DFN_FRAME, LAVA_FRAME)

def frames(seconds):
  return FRAME * round(SR * seconds / FRAME)

HOP, CONTEXT, FADE = frames(30), frames(3), SR
DFN_HOP, DFN_CONTEXT = frames(600), frames(15)
WATCH_SEC = 60
PARTIAL = ".partial"

def decode(path, filters=()):
  """Mono 48 kHz float blocks of a recording, after the given ffmpeg filters."""
  af = ",".join(list(filters) + ["aresample=%d:resampler=soxr:precision=28" % SR])
  with subprocess.Popen(["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-ac", "1", "-af", af,
                         "-ar", str(SR), "-f", "f32le", "-"], stdout=subprocess.PIPE) as proc:
    try:
      while block := proc.stdout.read(BLOCK * 4):
        yield np.frombuffer(block[:len(block) // 4 * 4], dtype=np.float32)
    except GeneratorExit:
      proc.kill()
      raise
  if proc.returncode:
    raise RuntimeError("ffmpeg couldn't decode %s" % path)

class Analysis:
  """Hum harmonics standing out of the noise floor in most 1 s frames, and the -30 dB band edge."""

  def __init__(self):
    self.harmonics = np.arange(1, int(HUM_MAX_HZ // MAINS_HZ) + 1) * MAINS_HZ
    self.humFrames, self.frames, self.psd, self.blocks = np.zeros(len(self.harmonics)), 0, None, 0

  def add(self, x):
    if len(x) < SR:
      return
    _, _, Z = stft(x, SR, nperseg=SR, noverlap=SR // 2, boundary=None, padded=False)
    db = 20 * np.log10(np.abs(Z[:HUM_MAX_HZ + 20]) + 1e-10)
    for i, hz in enumerate(self.harmonics):
      b = int(hz)
      floor = np.median(np.r_[db[max(1, b - 15):b - 2], db[b + 3:b + 16]], axis=0)
      self.humFrames[i] += np.sum(db[b - 1:b + 2].max(axis=0) - floor >= HUM_MIN_DB)
    self.frames += Z.shape[1]
    f, P = welch(x, SR, nperseg=4096)
    self.freqs, self.psd, self.blocks = f, P if self.psd is None else self.psd + P, self.blocks + 1

  def hum(self):
    return [float(hz) for hz, n in zip(self.harmonics, self.humFrames) if self.frames and n / self.frames >= HUM_MIN_FRACTION]

  def edge(self):
    db = 10 * np.log10(self.psd / self.blocks + 1e-20)
    ref = np.median(db[(self.freqs > 1000) & (self.freqs < 2500)])
    return float(self.freqs[np.nonzero((db > ref - EDGE_DB) & (self.freqs > 1000))[0][-1]])

def analyse(path):
  a = Analysis()
  for x in decode(path):
    a.add(x)
  return a

def notches(hum):
  return ["bandreject=f=%g:width_type=q:w=%d" % (hz, 25 if hz < 400 else 40) for hz in hum] + ["highpass=f=40"]

def chunked(blocks, process, hop=HOP, context=CONTEXT, fade=FADE):
  """Stream blocks through process one hop at a time, each call seeing context on both sides, crossfading neighbours."""
  half = fade // 2
  up = np.sin(np.pi / 2 * (np.arange(2 * half) + 0.5) / (2 * half)) ** 2
  blocks = iter(blocks)
  try:
    yield from _chunked(blocks, process, hop, context, half, up)
  finally:
    if hasattr(blocks, "close"):
      blocks.close()

def _chunked(blocks, process, hop, context, half, up):
  buf, base, done, tail, k = np.zeros(0, np.float32), 0, False, None, 0
  while True:
    start, end = k * hop, (k + 1) * hop + context
    while not done and base + len(buf) < end:
      try:
        buf = np.concatenate([buf, next(blocks)])
      except StopIteration:
        done = True
    total = base + len(buf)
    if start >= total:
      return
    lo, hi = max(0, start - context), min(end, total)
    y = process(buf[lo - base:hi - base])
    last = done and total <= end
    if tail is not None:
      yield tail * (1 - up) + y[start - half - lo:start + half - lo] * up
    yield y[(start + half if k else 0) - lo:(total if last else start + hop - half) - lo]
    if last:
      return
    tail = y[start + hop - half - lo:start + hop + half - lo]
    k += 1
    drop = k * hop - context - base
    buf, base = buf[drop:], base + drop

def threaded(blocks, depth=2):
  """Produce blocks on a background thread so the stages around it run at the same time."""
  q, end, stop = queue.Queue(depth), object(), threading.Event()
  def put(item):
    while not stop.is_set():
      try:
        return q.put(item, timeout=1)
      except queue.Full:
        pass
  def run():
    try:
      for b in blocks:
        if stop.is_set():
          break
        put(b)
      put(end)
    except BaseException as err:
      put(err)
    finally:
      blocks.close()
  producer = threading.Thread(target=run, daemon=True)
  producer.start()
  try:
    while (b := q.get()) is not end:
      if isinstance(b, BaseException):
        raise b
      yield b
  finally:
    stop.set()
    producer.join()

def crossover(low, high, hz, width=CROSSOVER_HZ):
  """low below hz - width and high above hz, with a raised-cosine transition between."""
  f = np.fft.rfftfreq(len(low), 1 / SR)
  t = np.clip((f - (hz - width)) / width, 0, 1)
  mask = np.sin(np.pi / 2 * t) ** 2
  L, H = np.fft.rfft(low), np.fft.rfft(high)
  return np.fft.irfft(L + (H - L) * mask, n=len(low)).astype(np.float32)

def deepFilter(workdir):
  def run(x):
    src, out = os.path.join(workdir, "in.wav"), os.path.join(workdir, "out")
    sf.write(src, np.r_[x, np.zeros(DEEP_FILTER_PAD, np.float32)], SR, subtype="FLOAT")
    subprocess.run([setting("SHARK_DEEP_FILTER"), "-a", str(ATTEN_LIM_DB), "-D", "-o", out, src],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    y, sr = sf.read(os.path.join(out, "in.wav"), dtype="float32")
    assert sr == SR and len(y) >= len(x), (sr, len(y), len(x))
    return y[:len(x)]
  return run

def lavaModelDir():
  from huggingface_hub import snapshot_download
  return snapshot_download(LAVA_REPO, revision=LAVA_REVISION, allow_patterns=["enhancer_v2/*", "denoiser/*"])

def lavaSR(edge):
  import torch
  from LavaSR.enhancer.linkwitz_merge import FastLRMerge
  from LavaSR.model import LavaEnhance2
  torch.set_num_threads(TORCH_THREADS)
  lava = LavaEnhance2(lavaModelDir(), "cpu")
  lava.bwe_model.lr_refiner = FastLRMerge(device="cpu", cutoff=min(edge - LAVA_CUTOFF_MARGIN_HZ, LAVA_MAX_CUTOFF_HZ), transition_bins=1024)
  def run(x):
    x16 = torch.from_numpy(resample_poly(x, 1, 3).astype(np.float32))[None]
    with torch.no_grad():
      y = lava.enhance(x16, denoise=False).float().numpy().reshape(-1)
    y = np.pad(y[:len(x)], (0, max(0, len(x) - len(y))))
    return crossover(x, y, edge)
  return run

def encode(blocks, source, output):
  with subprocess.Popen(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
                         "-i", source, "-map", "0:a", "-map_metadata", "1", "-c:a", "libmp3lame",
                         "-b:a", "%sk" % setting("SHARK_BITRATE"), "-ar", "44100", "-id3v2_version", "3", "-f", "mp3", output],
                        stdin=subprocess.PIPE) as proc:
    for b in blocks:
      proc.stdin.write(np.ascontiguousarray(b, dtype=np.float32).tobytes())
  if proc.returncode:
    raise RuntimeError("ffmpeg couldn't encode %s" % output)

def enhance(recording, output):
  t0 = time.monotonic()
  a = analyse(recording)
  hum, edge = a.hum(), a.edge()
  lava = edge < LAVA_MAX_EDGE_HZ
  print("%s: hum %s, band edge %.0f Hz, %s" % (os.path.basename(recording), hum or "none", edge,
        "extending the highs" if lava else "full band"), flush=True)
  partial = output + PARTIAL
  try:
    with tempfile.TemporaryDirectory() as workdir:
      blocks = chunked(decode(recording, notches(hum)), deepFilter(workdir), DFN_HOP, DFN_CONTEXT)
      if lava:
        blocks = chunked(threaded(blocks), lavaSR(edge))
      encode(blocks, recording, partial)
    os.replace(partial, output)
  finally:
    if os.path.exists(partial):
      os.remove(partial)
  print("%s: done in %.0f s" % (os.path.basename(output), time.monotonic() - t0), flush=True)

def pending(recordings, enhanced):
  paths = sorted(glob.glob(os.path.join(glob.escape(recordings), "*.mp3")), key=os.path.getmtime, reverse=True)
  return [p for p in paths if not os.path.exists(os.path.join(enhanced, os.path.basename(p)))]

def watch(recordings, enhanced):
  os.makedirs(enhanced, exist_ok=True)
  for stale in glob.glob(os.path.join(glob.escape(enhanced), "*" + PARTIAL)):
    os.remove(stale)
  failed = set()
  while True:
    todo = [p for p in pending(recordings, enhanced) if p not in failed]
    if not todo:
      time.sleep(WATCH_SEC)
      continue
    try:
      enhance(todo[0], os.path.join(enhanced, os.path.basename(todo[0])))
    except Exception as err:
      print("Couldn't enhance %s: %s" % (todo[0], err), flush=True)
      failed.add(todo[0])

if __name__ == "__main__":
  arguments = docopt(__doc__, version="Shark Enhance 0.1")
  if arguments["--watch"]:
    watch(arguments["<recordings>"], arguments["<enhanced>"])
  else:
    enhance(arguments["<recording>"], arguments["<output>"])
