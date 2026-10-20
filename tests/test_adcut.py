import json, os, subprocess

import httpx2 as httpx
import pytest
from mutagen.id3 import ID3
from mutagen.mp3 import MP3

import adcut

SEGMENTS = [(0, 10, "game"), (10, 20, "ad"), (21, 30, "ad"), (30, 55, "game"), (55, 59, "ad"), (59, 85, "game"), (85, 100, "ad")]


def recording(path, seconds=100):
  subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=%d:r=44100" % seconds, "-ac", "1",
                  "-c:a", "libmp3lame", "-b:a", "64k", "-metadata", "title=Avalanche at Flyers",
                  "-metadata", "artist=Avalanche", str(path)], check=True)
  return str(path)


class FakeWorker:
  def __init__(self, segments=SEGMENTS):
    self.segments, self.calls = segments, []

  def __call__(self, request):
    self.calls.append(request)
    if request.url.path == "/v1/audio/transcriptions":
      return httpx.Response(200, json={"language": "en", "segments": [
        {"start": a, "end": b, "text": label, "speaker": "SPEAKER_00"} for a, b, label in self.segments]})
    if request.url.path == "/v1/audio/music/upload":
      return httpx.Response(200, json={"hop_s": 1.0, "duration": 100.0, "music": [0.0] * 100, "jingle": [], "whoosh": []})
    if request.url.path == "/v1/bilstm/classify":
      segs = json.loads(request.content)["segments"]
      return httpx.Response(200, json={"labels": ["ad" if s["text"] == "ad" else "content" for s in segs]})
    return httpx.Response(404)

  def paths(self):
    return [c.url.path for c in self.calls]


@pytest.fixture
def worker():
  fake = FakeWorker()
  return fake, adcut.Worker("http://worker:8090", transport=httpx.MockTransport(fake))


def test_breaks_join_close_ads_and_drop_short_ones():
  segs = [{"start_time": a, "end_time": b} for a, b, _ in SEGMENTS]

  assert adcut.breaks(segs, [label if label == "ad" else "content" for *_, label in SEGMENTS]) == [[10, 30], [85, 100]]
  assert adcut.breaks(segs, ["ad"] * 7) == [[0, 100]]
  assert adcut.breaks(segs, ["content"] * 7) == []


def test_keeps_are_what_is_left_between_the_breaks():
  assert adcut.keeps([[10, 30], [50, 70]], 60) == [(0.0, 10), (30, 50)]
  assert adcut.keeps([[0, 5]], 60) == [(5, 60)]
  assert adcut.keeps([], 60) == [(0.0, 60)]


def test_cut_removes_the_breaks_with_a_beep_between(tmpdir, worker):
  fake, client = worker
  src = recording(tmpdir.join("Avalanche-2026-10-19-1700.mp3"))
  ads, trimmed = tmpdir.mkdir("ads"), tmpdir.mkdir("trimmed")

  adcut.cut(src, str(ads), str(trimmed), client)

  out = trimmed.join("Avalanche-2026-10-19-1700.mp3")
  assert MP3(str(out)).info.length == pytest.approx(10 + 55 + adcut.BEEP_SEC, abs=0.1)
  assert MP3(str(out)).info.channels == 1
  assert str(ID3(str(out))["TIT2"]) == "Avalanche at Flyers"
  assert json.loads(ads.join("Avalanche-2026-10-19-1700.breaks.json").read()) == [[10, 30], [85, 100]]
  assert sorted(os.listdir(str(ads))) == ["Avalanche-2026-10-19-1700.%s.json" % k for k in ("breaks", "music", "transcript")]
  assert fake.paths() == ["/v1/audio/transcriptions", "/v1/audio/music/upload", "/v1/bilstm/classify"]


def test_worker_is_asked_for_the_sports_model_and_diarized_english(tmpdir, worker, monkeypatch):
  monkeypatch.setenv("SHARK_ADCUT_MODEL", "trained_models/sports/test.pt")
  fake, client = worker
  src = recording(tmpdir.join("Avalanche-2026-10-19-1700.mp3"), 5)

  adcut.detect(src, str(tmpdir.mkdir("ads")), client)

  upload = fake.calls[0].content
  assert b'name="language"\r\n\r\nen' in upload and b'name="diarize"\r\n\r\ntrue' in upload
  assert b'filename="Avalanche-2026-10-19-1700.mp3"' in upload
  classify = json.loads(fake.calls[2].content)
  assert classify["model_path"] == "trained_models/sports/test.pt"
  assert classify["embedding_model"] == adcut.setting("SHARK_ADCUT_EMBEDDER")
  assert classify["music_timeline"]["hop_s"] == 1.0
  assert classify["segments"][1] == {"start_time": 10, "end_time": 20, "text": "ad", "speaker": "SPEAKER_00"}


def test_saved_results_are_not_asked_for_again(tmpdir, worker):
  fake, client = worker
  src = recording(tmpdir.join("Avalanche-2026-10-19-1700.mp3"), 5)
  ads = str(tmpdir.mkdir("ads"))

  adcut.detect(src, ads, client)
  adcut.detect(src, ads, client)

  assert len(fake.calls) == 3


def test_a_failed_classify_keeps_the_transcript_for_the_retry(tmpdir):
  calls = []

  def flaky(request):
    calls.append(request.url.path)
    if request.url.path == "/v1/bilstm/classify" and calls.count("/v1/bilstm/classify") == 1:
      return httpx.Response(500, json={"error": "boom"})
    return FakeWorker()(request)

  client = adcut.Worker("http://worker:8090", transport=httpx.MockTransport(flaky))
  src = recording(tmpdir.join("Avalanche-2026-10-19-1700.mp3"), 5)
  ads = str(tmpdir.mkdir("ads"))

  with pytest.raises(httpx.HTTPStatusError):
    adcut.detect(src, ads, client)
  assert adcut.detect(src, ads, client) == [[10, 30], [85, 100]]
  assert calls.count("/v1/audio/transcriptions") == 1


def test_enhanced_copy_is_cut_when_it_exists(tmpdir, worker):
  _, client = worker
  src = recording(tmpdir.join("Avalanche-2026-10-19-1700.mp3"))
  enhanced = tmpdir.mkdir("enhanced")
  recording(enhanced.join("Avalanche-2026-10-19-1700.mp3"), 110)
  trimmed = tmpdir.mkdir("trimmed")

  adcut.cut(src, str(tmpdir.mkdir("ads")), str(trimmed), client, str(enhanced))

  assert MP3(str(trimmed.join("Avalanche-2026-10-19-1700.mp3"))).info.length == pytest.approx(10 + 55 + 10 + 2 * adcut.BEEP_SEC, abs=0.1)


def test_pending_includes_copies_older_than_a_new_enhanced_copy(tmpdir, mp3):
  enhanced, trimmed = tmpdir.mkdir("enhanced"), tmpdir.mkdir("trimmed")
  old = mp3(tmpdir.join("Broncos-2026-10-15-1815.mp3"), 1, mtime=1000)
  new = mp3(tmpdir.join("Avalanche-2026-10-19-1700.mp3"), 1, mtime=2000)
  done = mp3(tmpdir.join("Avalanche-2026-10-16-1900.mp3"), 1, mtime=1500)
  mp3(trimmed.join("Avalanche-2026-10-16-1900.mp3"), 1, mtime=1600)
  mp3(trimmed.join("Broncos-2026-10-15-1815.mp3"), 1, mtime=1100)
  mp3(enhanced.join("Broncos-2026-10-15-1815.mp3"), 1, mtime=1200)
  tmpdir.join("Nuggets-2026-10-20-1900.mp3.partial").write("x")

  assert adcut.pending(str(tmpdir), str(enhanced), str(trimmed)) == [str(new), str(old)]
  assert str(done) not in adcut.pending(str(tmpdir), str(enhanced), str(trimmed))


def test_failed_cut_leaves_no_partial(tmpdir, worker, monkeypatch):
  _, client = worker
  src = recording(tmpdir.join("Avalanche-2026-10-19-1700.mp3"), 5)
  trimmed = tmpdir.mkdir("trimmed")
  monkeypatch.setattr(adcut, "cutCommand", lambda *a: ["bash", "-c", "echo x > %s.partial; exit 1" % trimmed.join("Avalanche-2026-10-19-1700.mp3")])

  with pytest.raises(subprocess.CalledProcessError):
    adcut.cut(src, str(tmpdir.mkdir("ads")), str(trimmed), client)

  assert trimmed.listdir() == []
