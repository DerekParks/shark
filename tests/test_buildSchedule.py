import json
from datetime import datetime, timedelta, timezone

import buildSchedule


def game(team, startHourUTC, hours=3):
  start = datetime(2026, 10, 20, startHourUTC, tzinfo=timezone.utc)
  return {"team": team, "name": "%s game" % team, "start": start, "end": start + timedelta(hours=hours), "band": "FM", "freq": "92.5"}


def test_higher_priority_team_wins_overlap_regardless_of_start_order():
  rockies = game("Rockies", 0)
  nuggets = game("Nuggets", 1)
  avalanche = game("Avalanche", 2)

  merged = buildSchedule.prioritize([[avalanche], [nuggets], [rockies]])

  assert merged == [avalanche]


def test_lower_priority_games_fill_gaps():
  avalanche = game("Avalanche", 2)
  nuggets = game("Nuggets", 18)
  rockies = game("Rockies", 6)

  merged = buildSchedule.prioritize([[avalanche], [nuggets], [rockies]])

  assert merged == [avalanche, rockies, nuggets]


def test_whole_game_skipped_rather_than_truncated():
  avalanche = game("Avalanche", 3)
  nuggets = game("Nuggets", 1)

  merged = buildSchedule.prioritize([[avalanche], [nuggets]])

  assert merged == [avalanche]


def team(name, **fields):
  t = {"name": name, "source": "nhl", "id": "COL", "band": "AM", "freq": "950", "hours": 3}
  t.update(fields)
  return t


def teamsFile(tmpdir, *teams):
  path = tmpdir.join("teams.toml")
  path.write("".join("[[team]]\n" + "".join("%s = %s\n" % (k, json.dumps(v)) for k, v in t.items()) + "\n" for t in teams))
  return str(path)


def test_load_teams_keeps_file_order(tmpdir):
  path = teamsFile(tmpdir, team("Avalanche"), team("Nuggets", source="nba", id="DEN", slug="nuggets"))

  assert [t["name"] for t in buildSchedule.loadTeams(path)] == ["Avalanche", "Nuggets"]


def test_numeric_frequency_is_accepted_as_text(tmpdir):
  assert buildSchedule.loadTeams(teamsFile(tmpdir, team("Avalanche", freq=92.5)))[0]["freq"] == "92.5"


def test_example_teams_file_is_valid():
  teams = buildSchedule.loadTeams("teams.example.toml")

  assert {t["source"] for t in teams} == {"nhl", "nfl", "nba", "mlb"}


def problems(tmpdir, *teams):
  try:
    buildSchedule.loadTeams(teamsFile(tmpdir, *teams))
  except SystemExit as err:
    return str(err)
  raise AssertionError("teams file was accepted")


def test_every_problem_is_reported_with_its_team(tmpdir):
  message = problems(tmpdir,
    team("Avalanche"),
    team("Nuggets", source="nba", id="DEN"),
    team("Rockies", source="mlb", id=115, band="XM", freq="ninety", hours=0),
    team("Bad/Name", source="nhl"),
    team("Seals", source="whl"))

  assert "team 2 (Nuggets): missing slug" in message
  assert "team 3 (Rockies): band must be AM or FM" in message
  assert "team 3 (Rockies): freq must be a number" in message
  assert "team 3 (Rockies): hours must be a positive number" in message
  assert "team 4 (Bad/Name): name can't contain /" in message
  assert "team 5 (Seals): source must be one of nhl, nfl, mlb, nba" in message
  assert "Avalanche" not in message


def test_missing_or_empty_teams_file_explains_itself(tmpdir):
  for setup in (lambda: None, lambda: tmpdir.join("teams.toml").write("")):
    setup()
    try:
      buildSchedule.loadTeams(str(tmpdir.join("teams.toml")))
    except SystemExit as err:
      assert "teams.toml" in str(err)
    else:
      raise AssertionError("missing teams were accepted")


def test_build_writes_merged_schedule(tmpdir, monkeypatch):
  teams = teamsFile(tmpdir, team("Avalanche"), team("Nuggets", source="nba", id="DEN", slug="nuggets"))
  schedules = {"Avalanche": [game("Avalanche", 2)], "Nuggets": [game("Nuggets", 3), game("Nuggets", 18)]}
  monkeypatch.setattr(buildSchedule.scrapers, "fetchSchedule", lambda team: schedules[team["name"]])
  out = tmpdir.join("merged.csv")

  buildSchedule.build(teams, str(out))

  assert [line.split(",")[0] for line in out.readlines(cr=False)[1:] if line] == ["Avalanche", "Nuggets"]


class Stop(BaseException):
  pass


def test_refresh_retries_sooner_after_a_failed_build():
  outcomes = iter([None, OSError("league site down"), None])
  slept = []

  def rebuild():
    outcome = next(outcomes)
    if outcome:
      raise outcome

  def sleep(seconds):
    slept.append(seconds)
    if len(slept) == 3:
      raise Stop

  try:
    buildSchedule.refreshForever(rebuild, 86400, sleep)
  except Stop:
    pass

  assert slept == [86400, buildSchedule.RETRY_SEC, 86400]
