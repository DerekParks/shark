import os, subprocess, sys

import numpy as np
import pytest
import soundfile as sf
from mutagen.mp3 import MP3

import enhance, pausing
from enhance import SR

FAKE_DEEP_FILTER = """#!{python}
import os, sys
import soundfile as sf
args = sys.argv[1:]
out, src = args[args.index("-o") + 1], args[-1]
assert args[args.index("-a") + 1] == "12" and "-D" in args
x, sr = sf.read(src, dtype="float32")
os.makedirs(out, exist_ok=True)
sf.write(os.path.join(out, os.path.basename(src)), 0.5 * x[:-1440], sr, subtype="FLOAT")
"""


def blocksOf(x, sizes):
  i = 0
  for n in sizes:
    yield x[i:i + n]
    i += n
  if i < len(x):
    yield x[i:]


def tone(hz, seconds, amp=0.1):
  return (amp * np.sin(2 * np.pi * hz * np.arange(int(seconds * SR)) / SR)).astype(np.float32)


@pytest.mark.parametrize("n", [0, 1, 999, 1000, 1001, 2350, 9999, 10000, 10050])
def test_chunked_identity_reproduces_the_input_exactly(n):
  x = np.random.default_rng(n).standard_normal(n).astype(np.float32)

  y = np.concatenate([np.zeros(0, np.float32)] + list(enhance.chunked(blocksOf(x, [7, 333, 4000]), lambda c: c, 1000, 120, 100)))

  np.testing.assert_allclose(y, x, atol=1e-6)


def test_chunked_gives_each_call_its_context_and_crossfades_neighbours():
  x = np.arange(10_000, dtype=np.float32)
  seen = []

  def process(c):
    seen.append((int(c[0]), len(c)))
    return np.full(len(c), len(seen), np.float32)

  y = np.concatenate(list(enhance.chunked(blocksOf(x, [2500] * 4), process, 3000, 500, 200)))

  assert seen == [(0, 3500), (2500, 4000), (5500, 4000), (8500, 1500)]
  assert len(y) == len(x)
  assert (y[:2900] == 1).all() and (y[3100:5900] == 2).all() and (y[6100:8900] == 3).all() and (y[9100:] == 4).all()
  assert np.all(np.diff(y[2900:3100]) >= 0) and 1 < y[3000] < 2


def test_chunked_closes_its_input_when_stopped_early():
  closed = []

  def source():
    try:
      while True:
        yield np.zeros(1000, np.float32)
    finally:
      closed.append(True)

  stream = enhance.chunked(source(), lambda c: c, 1000, 100, 50)
  next(stream)
  stream.close()

  assert closed == [True]


def test_threaded_passes_blocks_through_and_raises_the_producers_error():
  def failing():
    yield np.ones(3, np.float32)
    raise ValueError("decoder died")

  out = enhance.threaded(failing())

  np.testing.assert_array_equal(next(out), np.ones(3))
  with pytest.raises(ValueError, match="decoder died"):
    next(out)


def test_analysis_finds_steady_hum_and_the_band_edge():
  rng = np.random.default_rng(0)
  noise = np.fft.irfft(np.fft.rfft(rng.standard_normal(SR * 20)) * (np.fft.rfftfreq(SR * 20, 1 / SR) < 5500))
  a = enhance.Analysis()
  for x in blocksOf((0.05 * noise / noise.std() + tone(120, 20, 0.05) + tone(360, 20, 0.02)).astype(np.float32), [SR * 7] * 3):
    a.add(x)

  assert a.hum() == [120.0, 360.0]
  assert 5300 < a.edge() < 5600


def test_analysis_finds_no_hum_in_noise():
  a = enhance.Analysis()
  a.add(np.random.default_rng(1).standard_normal(SR * 10).astype(np.float32))

  assert a.hum() == []
  assert a.edge() > 20000


def test_crossover_keeps_low_below_and_high_above():
  low, high = tone(1000, 2) + tone(9000, 2), tone(1000, 2, 0.3) + tone(9000, 2, 0.3)

  y = enhance.crossover(low, high, 5000)
  spectrum = np.abs(np.fft.rfft(y)) / (len(y) / 2)

  assert spectrum[2000] == pytest.approx(0.1, rel=1e-3)
  assert spectrum[18000] == pytest.approx(0.3, rel=1e-3)


def test_notches_reject_each_hum_harmonic_and_rumble():
  assert enhance.notches([120.0, 480.0]) == [
    "bandreject=f=120:width_type=q:w=25", "bandreject=f=480:width_type=q:w=40", "highpass=f=40"]


def test_pending_is_newest_first_and_skips_enhanced(tmpdir):
  out, done = tmpdir.mkdir("out"), tmpdir.mkdir("enhanced")
  for i, name in enumerate(["Broncos-2026-10-15-1815.mp3", "Avalanche-2026-10-16-1900.mp3", "Nuggets-2026-10-17-1900.mp3"]):
    out.join(name).write("x")
    os.utime(str(out.join(name)), (1000 + i, 1000 + i))
  out.join("Rockies-2026-10-18-1300.mp3.partial").write("x")
  done.join("Nuggets-2026-10-17-1900.mp3").write("x")

  assert [os.path.basename(p) for p in enhance.pending(str(out), str(done))] == [
    "Avalanche-2026-10-16-1900.mp3", "Broncos-2026-10-15-1815.mp3"]


def test_enhance_runs_a_full_band_recording_through_deep_filter(tmpdir, monkeypatch):
  fake = tmpdir.join("deep-filter")
  fake.write(FAKE_DEEP_FILTER.format(python=sys.executable))
  fake.chmod(0o755)
  monkeypatch.setenv("SHARK_DEEP_FILTER", str(fake))
  rng = np.random.default_rng(2)
  sf.write(str(tmpdir.join("raw.wav")), 0.1 * rng.standard_normal(SR * 70).astype(np.float32), SR)
  recording, output = tmpdir.join("Avalanche-2026-10-16-1900.mp3"), tmpdir.join("enhanced.mp3")
  subprocess.run(["ffmpeg", "-v", "error", "-i", str(tmpdir.join("raw.wav")), "-c:a", "libmp3lame", "-b:a", "64k",
                  "-metadata", "title=Avalanche vs. Penguins", "-metadata", "artist=Avalanche", str(recording)], check=True)

  enhance.enhance(str(recording), str(output))

  before, after = MP3(str(recording)), MP3(str(output))
  assert after.info.length == pytest.approx(before.info.length, abs=0.1)
  assert after.info.channels == 1
  assert after.tags["TIT2"].text == ["Avalanche vs. Penguins"] and after.tags["TPE1"].text == ["Avalanche"]
  y, _ = sf.read(str(output))
  assert 0.03 < np.sqrt(np.mean(y[SR:-SR] ** 2)) < 0.07
  assert not tmpdir.join("enhanced.mp3.partial").exists()


def test_failed_enhance_leaves_no_partial(tmpdir, monkeypatch):
  monkeypatch.setenv("SHARK_DEEP_FILTER", "false")
  sf.write(str(tmpdir.join("raw.wav")), np.zeros(SR * 5, np.float32), SR)
  recording = tmpdir.join("r.mp3")
  subprocess.run(["ffmpeg", "-v", "error", "-i", str(tmpdir.join("raw.wav")), str(recording)], check=True)

  with pytest.raises(subprocess.CalledProcessError):
    enhance.enhance(str(recording), str(tmpdir.join("out.mp3")))

  assert tmpdir.listdir(lambda p: p.basename.startswith("out")) == []


def test_analysis_waits_while_busy(tmpdir, monkeypatch):
  monkeypatch.setattr(pausing, "BUSY_POLL_SEC", 0)
  sf.write(str(tmpdir.join("r.wav")), tone(440, 2), SR)
  answers = iter([True, True, False])

  enhance.analyse(str(tmpdir.join("r.wav")), lambda: next(answers, False))

  assert next(answers, "drained") == "drained"
