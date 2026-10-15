import io, os, time

import relay

DATA = os.urandom(relay.CHUNK * 64)


def runRelay(streamCmd, data=DATA, **options):
  src, dst = io.BytesIO(data), io.BytesIO()
  options.setdefault("retrySec", 0.05)
  options.setdefault("stopSec", 2)
  started = time.monotonic()
  relay.relay(src, dst, streamCmd, **options)
  return dst.getvalue(), time.monotonic() - started


def test_primary_and_stream_both_get_every_byte(tmpdir):
  streamed = tmpdir.join("stream.raw")

  primary, _ = runRelay("cat > %s" % streamed)

  assert primary == DATA
  assert streamed.read_binary() == DATA


def test_primary_complete_when_stream_command_fails():
  primary, _ = runRelay("exit 1")

  assert primary == DATA


def test_primary_never_waits_on_a_stalled_stream():
  data = os.urandom(relay.CHUNK * 1024)

  primary, elapsed = runRelay("sleep 30", data=data, maxChunks=4, stopSec=0.5)

  assert primary == data
  assert elapsed < 5


def test_stream_restarts_after_failure(tmpdir):
  marker, streamed = tmpdir.join("failed-once"), tmpdir.join("stream.raw")
  streamCmd = "if [ -e {m} ]; then cat > {s}; else touch {m}; exit 1; fi".format(m=marker, s=streamed)
  chunks = [DATA[i:i + relay.CHUNK] for i in range(0, len(DATA), relay.CHUNK)]

  class SlowSource:
    def read(self, size):
      time.sleep(0.01)
      return chunks.pop(0) if chunks else b""

  dst = io.BytesIO()
  relay.relay(SlowSource(), dst, streamCmd, retrySec=0.05, stopSec=2)

  assert dst.getvalue() == DATA
  assert marker.exists()
  assert 0 < len(streamed.read_binary()) < len(DATA)
  assert len(streamed.read_binary()) % relay.CHUNK == 0
