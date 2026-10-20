#!/usr/bin/env python3
"""Copy stdin to stdout, and best-effort to a stream command that is restarted when it dies.

Usage:
  relay.py <streamCmd>

Stdout is written from a backlog held in memory, so a slow disk under the encoder
delays the recording instead of stalling the capture that feeds stdin.
The stream side is fed through a bounded queue that drops whole chunks when full,
so a slow or dead stream never blocks stdout.
"""

import queue, subprocess, sys, threading, time

CHUNK = 4096
BACKLOG_CHUNKS = 16384
LOG_BACKLOG_CHUNKS = 32

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

def logDrained(peak):
  if peak >= LOG_BACKLOG_CHUNKS:
    print("relay: recording backlog of %d KB drained" % (peak * CHUNK // 1024), file=sys.stderr, flush=True)

def record(dst, backlog, failure):
  try:
    peak = 0
    while (chunk := backlog.get()) is not None:
      dst.write(chunk)
      waiting = backlog.qsize()
      peak = max(peak, waiting)
      if waiting == 0:
        logDrained(peak)
        peak = 0
    dst.flush()
    logDrained(peak)
  except BaseException as e:
    failure.append(e)

def putRecorded(backlog, chunk, failure):
  while not failure:
    try:
      backlog.put(chunk, timeout=0.5)
      return
    except queue.Full:
      pass
  raise failure[0]

def stopStream(chunks, stopping, feeder, current, stopSec):
  stopping.set()
  try:
    chunks.put(None, timeout=stopSec)
  except queue.Full:
    pass
  feeder.join(stopSec)
  if feeder.is_alive() and current[0] is not None:
    current[0].kill()
    feeder.join(stopSec)

def relay(src, dst, streamCmd, retrySec=5, maxChunks=256, stopSec=10, backlogChunks=BACKLOG_CHUNKS):
  chunks = queue.Queue(maxChunks)
  stopping = threading.Event()
  current = [None]
  feeder = threading.Thread(target=feed, args=(streamCmd, chunks, stopping, retrySec, current), daemon=True)
  feeder.start()

  backlog = queue.Queue(backlogChunks)
  failure = []
  recorder = threading.Thread(target=record, args=(dst, backlog, failure), daemon=True)
  recorder.start()

  dropped = 0
  try:
    while chunk := src.read(CHUNK):
      putRecorded(backlog, chunk, failure)
      try:
        chunks.put_nowait(chunk)
      except queue.Full:
        dropped += 1
    putRecorded(backlog, None, failure)
    recorder.join()
    if failure:
      raise failure[0]
  finally:
    stopStream(chunks, stopping, feeder, current, stopSec)
  if dropped:
    print("relay: dropped %d stream chunks" % dropped, file=sys.stderr, flush=True)

if __name__ == "__main__":
  if len(sys.argv) != 2:
    sys.exit(__doc__)
  relay(sys.stdin.buffer, sys.stdout.buffer, sys.argv[1])
