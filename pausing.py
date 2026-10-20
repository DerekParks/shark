"""Pause background work while the recorder is writing a game, so it never competes with the capture."""

import glob, os, signal, subprocess, threading, time

BUSY_POLL_SEC = 5
PARTIAL = ".partial"

def idle():
  return False

class Recording:
  """True while the recorder is writing a game into recordings, logging each change."""

  def __init__(self, recordings):
    self.pattern = os.path.join(glob.escape(recordings), "*" + PARTIAL)
    self.lock, self.was = threading.Lock(), False

  def __call__(self):
    now = bool(glob.glob(self.pattern))
    with self.lock:
      if now != self.was:
        print("A game is recording, pausing" if now else "Recording finished, resuming", flush=True)
        self.was = now
    return now

def waitWhile(busy):
  while busy():
    time.sleep(BUSY_POLL_SEC)

def runPausing(cmd, busy):
  """Run cmd to completion, stopping it while busy."""
  proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
  try:
    while True:
      try:
        proc.wait(timeout=BUSY_POLL_SEC)
        break
      except subprocess.TimeoutExpired:
        if busy():
          proc.send_signal(signal.SIGSTOP)
          waitWhile(busy)
          proc.send_signal(signal.SIGCONT)
  except BaseException:
    proc.kill()
    proc.wait()
    raise
  if proc.returncode:
    raise subprocess.CalledProcessError(proc.returncode, cmd)
