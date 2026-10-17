import shlex
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import readCSVRecord

NOW = datetime(2026, 10, 17, 0, 0, tzinfo=timezone.utc)


def makeGame(**overrides):
  game = {
    "team": "Rockies",
    "name": "Rockies at D-backs",
    "start": "2017-04-02 15:10:00-05:00",
    "end": "2017-04-02 18:10:00-05:00",
    "band": "FM",
    "freq": "94.1",
  }
  game.update(overrides)
  return game


def gameAt(team, minutesFromNow, hours=3):
  start = NOW + timedelta(minutes=minutesFromNow)
  return makeGame(team=team, name="%s game" % team, start=str(start), end=str(start + timedelta(hours=hours)))


def captureExecute(monkeypatch):
  commands = []
  monkeypatch.setattr(readCSVRecord, "execute", commands.append)
  return commands


def test_record_command_passes_device_with_capital_D(monkeypatch):
  monkeypatch.delenv("SHARK_ALSA_DEVICE", raising=False)

  args = readCSVRecord.getRecordCommand(5400).split()

  assert args[args.index("-D") + 1] == "hw:CARD=RadioSHARK,DEV=0"
  assert args.count("-d") == 1
  assert args[args.index("-d") + 1] == "5400"


def test_uppercase_am_band_tunes_in_mhz(monkeypatch):
  commands = captureExecute(monkeypatch)

  readCSVRecord.runRecordGame("pipeline", makeGame(band="AM", freq="950"))

  assert commands[0] == "fm -q 0.95"


def test_fm_band_tunes_unchanged(monkeypatch):
  commands = captureExecute(monkeypatch)

  readCSVRecord.runRecordGame("pipeline", makeGame(band="FM", freq="94.1"))

  assert commands == ["fm -q 94.10", "pipeline"]


def test_record_game_tunes_then_runs_pipeline_for_duration(monkeypatch, tmpdir):
  commands = captureExecute(monkeypatch)

  readCSVRecord.recordGame(str(tmpdir), makeGame(), 600)

  assert commands[0] == "fm -q 94.10"
  assert commands[1].startswith("arecord -q -d 600 ")
  assert str(tmpdir.join(readCSVRecord.gameToStr(makeGame()) + ".mp3.partial")) in commands[1]


def fakePipeline(monkeypatch, audio=b"ID3audio", fail=False):
  def execute(cmd):
    if cmd.startswith("fm "):
      return
    partial = shlex.split(cmd.rsplit(" | ", 1)[1])[-1]
    with open(partial, "wb") as f:
      f.write(audio)
    if fail:
      raise readCSVRecord.subprocess.CalledProcessError(1, cmd)
  monkeypatch.setattr(readCSVRecord, "execute", execute)
  posted = []
  monkeypatch.setattr(readCSVRecord, "postRecord", lambda filename, game: posted.append(filename))
  return posted


def test_recording_is_published_under_its_final_name_when_done(monkeypatch, tmpdir):
  posted = fakePipeline(monkeypatch)

  readCSVRecord.recordGame(str(tmpdir), makeGame(), 600)

  final = tmpdir.join(readCSVRecord.gameToStr(makeGame()) + ".mp3")
  assert [p.basename for p in tmpdir.listdir()] == [final.basename]
  assert posted == [str(final)]


def test_failed_recording_keeps_what_was_captured(monkeypatch, tmpdir):
  posted = fakePipeline(monkeypatch, fail=True)

  readCSVRecord.recordGame(str(tmpdir), makeGame(), 600)

  assert [p.basename for p in tmpdir.listdir()] == [readCSVRecord.gameToStr(makeGame()) + ".mp3"]
  assert len(posted) == 1


def test_empty_recording_is_discarded(monkeypatch, tmpdir):
  posted = fakePipeline(monkeypatch, audio=b"", fail=True)

  readCSVRecord.recordGame(str(tmpdir), makeGame(), 600)

  assert tmpdir.listdir() == []
  assert posted == []


def test_rejoined_game_is_recorded_as_another_part(monkeypatch, tmpdir):
  fakePipeline(monkeypatch)

  readCSVRecord.recordGame(str(tmpdir), makeGame(), 600)
  readCSVRecord.recordGame(str(tmpdir), makeGame(), 300)

  name = readCSVRecord.gameToStr(makeGame())
  assert sorted(p.basename for p in tmpdir.listdir()) == [name + "-2.mp3", name + ".mp3"]


def test_interrupted_recordings_are_recovered_at_startup(tmpdir):
  tmpdir.join("Avalanche-2026-10-16-1900.mp3.partial").write("ID3audio")
  tmpdir.join("Nuggets-2026-10-17-1900.mp3.partial").write("")

  readCSVRecord.recoverPartials(str(tmpdir))

  assert [p.basename for p in tmpdir.listdir()] == ["Avalanche-2026-10-16-1900.mp3"]


def test_sleeps_until_next_game_start():
  later = gameAt("Nuggets", 45)
  sooner = gameAt("Avalanche", 30)

  assert readCSVRecord.nextAction([later, sooner], NOW, set()) == ("sleep", 30 * 60)


def test_sleep_is_capped_so_schedule_changes_are_seen():
  game = gameAt("Avalanche", 24 * 60)

  assert readCSVRecord.nextAction([game], NOW, set()) == ("sleep", readCSVRecord.RECHECK_SEC)


def test_sleeps_when_no_upcoming_games():
  assert readCSVRecord.nextAction([gameAt("Avalanche", -240)], NOW, set()) == ("sleep", readCSVRecord.RECHECK_SEC)


def test_records_full_game_at_start():
  game = gameAt("Avalanche", 0, hours=3)

  assert readCSVRecord.nextAction([game], NOW, set()) == ("record", game, 3 * 3600)


def test_joins_game_in_progress_for_remaining_time():
  game = gameAt("Avalanche", -60, hours=3)

  assert readCSVRecord.nextAction([game], NOW, set()) == ("record", game, 2 * 3600)


def test_does_not_rerecord_a_game_that_ended_early():
  game = gameAt("Avalanche", -60, hours=3)

  action = readCSVRecord.nextAction([game], NOW, {readCSVRecord.gameKey(game)})

  assert action == ("sleep", readCSVRecord.RECHECK_SEC)


def test_mixed_utc_offsets_compare_as_instants():
  mountain = timezone(timedelta(hours=-6))
  start = (NOW + timedelta(minutes=10)).astimezone(mountain)
  game = makeGame(start=str(start), end=str(start + timedelta(hours=3)))

  assert readCSVRecord.nextAction([game], NOW, set()) == ("sleep", 10 * 60)


def test_execute_fails_when_any_pipeline_stage_fails():
  try:
    readCSVRecord.execute("false | cat")
  except readCSVRecord.subprocess.CalledProcessError:
    return
  raise AssertionError("pipeline failure was not reported")


def test_filename_uses_local_start_date_and_time():
  denver = ZoneInfo("America/Denver")

  name = readCSVRecord.gameToStr(makeGame(team="Avalanche", start="2026-10-17 01:00:00+00:00"), denver)

  assert name == "Avalanche-2026-10-16-1900"


def test_doubleheader_games_get_distinct_filenames():
  first = makeGame(start="2026-04-26 17:10:00+00:00")
  second = makeGame(start="2026-04-26 22:40:00+00:00")

  assert readCSVRecord.gameToStr(first) != readCSVRecord.gameToStr(second)


def test_no_stream_without_icecast_url(monkeypatch, tmpdir):
  commands = captureExecute(monkeypatch)
  monkeypatch.delenv("SHARK_ICECAST_URL", raising=False)

  readCSVRecord.recordGame(str(tmpdir), makeGame(), 600)

  assert commands[1].count(" | ") == 1 and "ffmpeg" not in commands[1]


def test_streams_through_relay_between_recorder_and_encoder(monkeypatch, tmpdir):
  commands = captureExecute(monkeypatch)
  monkeypatch.setenv("SHARK_ICECAST_URL", "icecast://source@127.0.0.1:8765/live")

  readCSVRecord.recordGame(str(tmpdir), makeGame(), 600)

  recorder, relayStage, encoder = commands[1].split(" | ")
  relayArgs = shlex.split(relayStage)
  assert recorder.startswith("arecord ")
  assert relayArgs[1] == readCSVRecord.RELAY
  assert relayArgs[2].startswith("ffmpeg ")
  assert "icecast://source@127.0.0.1:8765/live" in relayArgs[2]
  assert encoder.startswith("lame ")


def test_titles_are_shell_quoted():
  game = makeGame(name='Rockies "at" $(touch pwned) D-backs')

  assert "'Rockies \"at\" $(touch pwned) D-backs'" in readCSVRecord.getMp3Command("out.mp3", game)
  assert "'Rockies \"at\" $(touch pwned) D-backs'" in readCSVRecord.getStreamCommand("icecast://x", game)


def test_alsa_device_comes_from_environment(monkeypatch):
  monkeypatch.setenv("SHARK_ALSA_DEVICE", "hw:CARD=Shark,DEV=0")

  args = readCSVRecord.getRecordCommand(60).split()

  assert args[args.index("-D") + 1] == "hw:CARD=Shark,DEV=0"


def test_bitrates_come_from_environment(monkeypatch):
  monkeypatch.setenv("SHARK_BITRATE", "48")
  monkeypatch.setenv("SHARK_STREAM_BITRATE", "96")

  assert "--preset 48 " in readCSVRecord.getMp3Command("out.mp3", makeGame())
  assert "-b:a 96k " in readCSVRecord.getStreamCommand("icecast://x", makeGame())


def test_default_bitrates(monkeypatch):
  monkeypatch.delenv("SHARK_BITRATE", raising=False)
  monkeypatch.delenv("SHARK_STREAM_BITRATE", raising=False)

  assert "--preset 64 " in readCSVRecord.getMp3Command("out.mp3", makeGame())
  assert "-b:a 64k " in readCSVRecord.getStreamCommand("icecast://x", makeGame())


def test_recording_and_stream_are_mono():
  assert " -a " in readCSVRecord.getMp3Command("out.mp3", makeGame())
  assert " -ac 1 " in readCSVRecord.getStreamCommand("icecast://x", makeGame())


def test_stream_password_is_read_by_the_shell_and_never_logged(monkeypatch, tmpdir, capsys):
  monkeypatch.setenv("SHARK_ICECAST_URL", "icecast://source@icecast:8000/live")
  monkeypatch.setenv("SHARK_ICECAST_PASSWORD", "hunter2")
  monkeypatch.setattr(readCSVRecord.subprocess, "run", lambda *a, **k: None)

  readCSVRecord.recordGame(str(tmpdir), makeGame(), 600)

  logged = capsys.readouterr().out
  assert '-password "$SHARK_ICECAST_PASSWORD"' in logged
  assert "hunter2" not in logged


def test_stream_command_passes_the_password_to_ffmpeg(monkeypatch):
  monkeypatch.setenv("SHARK_ICECAST_PASSWORD", "it's $ecret")

  cmd = readCSVRecord.getStreamCommand("icecast://source@icecast:8000/live", makeGame())
  args = readCSVRecord.subprocess.run(["bash", "-c", "printf '%s\\n' " + cmd.split(" ", 1)[1]],
                                      capture_output=True, text=True, check=True).stdout.splitlines()

  assert args[args.index("-password") + 1] == "it's $ecret"
