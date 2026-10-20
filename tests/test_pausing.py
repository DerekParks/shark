import subprocess

import pytest

import pausing


def test_recording_is_busy_while_a_partial_is_being_written(tmpdir, capsys):
  busy = pausing.Recording(str(tmpdir))
  assert not busy()

  tmpdir.join("Avalanche-2026-10-16-1900.mp3.partial").write("x")
  assert busy() and busy()
  tmpdir.join("Avalanche-2026-10-16-1900.mp3.partial").remove()
  assert not busy()

  assert capsys.readouterr().out == "A game is recording, pausing\nRecording finished, resuming\n"


def test_run_pausing_stops_the_process_while_busy(tmpdir, monkeypatch):
  monkeypatch.setattr(pausing, "BUSY_POLL_SEC", 0.05)
  pidfile, states = tmpdir.join("pid"), []

  def busy():
    if not pidfile.exists() or not pidfile.read().strip():
      return False
    state = open("/proc/%s/stat" % pidfile.read().strip()).read().split(")")[1].split()[0]
    states.append(state)
    return len(states) < 4

  pausing.runPausing(["bash", "-c", "echo $$ > %s; exec sleep 0.5" % pidfile], busy)

  assert states[2:4] == ["T", "T"]


def test_run_pausing_raises_when_the_command_fails():
  with pytest.raises(subprocess.CalledProcessError):
    pausing.runPausing(["false"], pausing.idle)
