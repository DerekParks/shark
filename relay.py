#!/usr/bin/env python3
"""Copy stdin to stdout, and best-effort to a stream command that is restarted when it dies.

Usage:
  relay.py <streamCmd>

The stream side is fed through a bounded queue that drops whole chunks when full,
so a slow or dead stream never blocks stdout.
"""

import queue, subprocess, sys, threading, time

CHUNK = 4096

def feed(streamCmd, chunks, stopping, retrySec, current):
  while not stopping.is_set():
    proc = subprocess.Popen(["bash", "-c", streamCmd], stdin=subprocess.PIPE)
    current[0] = proc
    try:
      while (chunk := chunks.get()) is not None:
        proc.stdin.write(chunk)
      proc.stdin.close()
      proc.wait()
      return
    except (BrokenPipeError, ValueError):
      pass
    proc.wait()
    print("relay: stream exited with %s, restarting in %ss" % (proc.returncode, retrySec), file=sys.stderr, flush=True)
    stopping.wait(retrySec)

def relay(src, dst, streamCmd, retrySec=5, maxChunks=256, stopSec=10):
  chunks = queue.Queue(maxChunks)
  stopping = threading.Event()
  current = [None]
  feeder = threading.Thread(target=feed, args=(streamCmd, chunks, stopping, retrySec, current), daemon=True)
  feeder.start()

  dropped = 0
  while chunk := src.read(CHUNK):
    dst.write(chunk)
    try:
      chunks.put_nowait(chunk)
    except queue.Full:
      dropped += 1
  dst.flush()

  stopping.set()
  try:
    chunks.put(None, timeout=stopSec)
  except queue.Full:
    pass
  feeder.join(stopSec)
  if feeder.is_alive() and current[0] is not None:
    current[0].kill()
    feeder.join(stopSec)
  if dropped:
    print("relay: dropped %d stream chunks" % dropped, file=sys.stderr, flush=True)

if __name__ == "__main__":
  if len(sys.argv) != 2:
    sys.exit(__doc__)
  relay(sys.stdin.buffer, sys.stdout.buffer, sys.argv[1])
