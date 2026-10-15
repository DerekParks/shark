import json, os
from datetime import datetime, timezone

import scrapers

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
  with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
    return f.read()


def utc(*args):
  return datetime(*args, tzinfo=timezone.utc)


def team(name, **overrides):
  config = {"name": name, "band": "FM", "freq": "92.5", "hours": 3}
  config.update(overrides)
  return config


def test_nhl_keeps_regular_season_with_home_and_away_names():
  games = scrapers.nhlGames(json.loads(fixture("nhl-COL.json")), team("Avalanche", id="COL"))

  assert games == [
    {"team": "Avalanche", "name": "Avalanche vs. Kings", "start": utc(2026, 10, 1, 2), "end": utc(2026, 10, 1, 5), "band": "FM", "freq": "92.5"},
    {"team": "Avalanche", "name": "Avalanche at Jets", "start": utc(2026, 10, 7, 23, 30), "end": utc(2026, 10, 8, 2, 30), "band": "FM", "freq": "92.5"},
  ]


def test_nhl_skips_games_not_on_schedule():
  data = json.loads(fixture("nhl-COL.json"))
  data["games"][1]["gameScheduleState"] = "PPD"

  games = scrapers.nhlGames(data, team("Avalanche", id="COL"))

  assert [g["name"] for g in games] == ["Avalanche at Jets"]


def test_nba_reads_schedule_embedded_in_page():
  games = scrapers.nbaGames(fixture("nba-nuggets.html"), team("Nuggets", id="DEN", hours=2.5))

  assert games == [
    {"team": "Nuggets", "name": "Nuggets vs. Pelicans", "start": utc(2026, 10, 25, 1), "end": utc(2026, 10, 25, 3, 30), "band": "FM", "freq": "92.5"},
    {"team": "Nuggets", "name": "Nuggets at Thunder", "start": utc(2026, 10, 23, 1, 30), "end": utc(2026, 10, 23, 4), "band": "FM", "freq": "92.5"},
  ]


def test_nba_skips_postponed():
  html = fixture("nba-nuggets.html").replace('"9:00 pm ET"', '"PPD"')

  games = scrapers.nbaGames(html, team("Nuggets", id="DEN"))

  assert [g["name"] for g in games] == ["Nuggets at Thunder"]


def test_mlb_skips_spring_postponed_and_tbd_games():
  games = scrapers.mlbGames(json.loads(fixture("mlb-115.json")), team("Rockies", id=115, freq="94.1"))

  assert games == [
    {"team": "Rockies", "name": "Rockies vs. Phillies", "start": utc(2026, 4, 3, 20, 10), "end": utc(2026, 4, 3, 23, 10), "band": "FM", "freq": "94.1"},
    {"team": "Rockies", "name": "Rockies at Marlins", "start": utc(2026, 3, 27, 23, 10), "end": utc(2026, 3, 28, 2, 10), "band": "FM", "freq": "94.1"},
  ]


def test_fetch_schedule_dispatches_on_source(monkeypatch):
  urls = []

  def fakeFetch(url):
    urls.append(url)
    return fixture("nhl-COL.json")

  monkeypatch.setattr(scrapers, "fetch", fakeFetch)

  games = scrapers.fetchSchedule(team("Avalanche", source="nhl", id="COL"))

  assert urls == ["https://api-web.nhle.com/v1/club-schedule-season/COL/now"]
  assert len(games) == 2


def test_nfl_skips_games_without_a_set_time():
  games = scrapers.nflGames(json.loads(fixture("nfl-den.json")), team("Broncos", id="DEN", freq="94.1", hours=3.5))

  assert games == [
    {"team": "Broncos", "name": "Broncos vs. Seahawks", "start": utc(2026, 10, 16, 0, 15), "end": utc(2026, 10, 16, 3, 45), "band": "FM", "freq": "94.1"},
    {"team": "Broncos", "name": "Broncos at Cardinals", "start": utc(2026, 10, 25, 20, 5), "end": utc(2026, 10, 25, 23, 35), "band": "FM", "freq": "94.1"},
  ]


def test_nfl_skips_postponed():
  data = json.loads(fixture("nfl-den.json"))
  data["events"][0]["competitions"][0]["status"]["type"]["name"] = "STATUS_POSTPONED"

  games = scrapers.nflGames(data, team("Broncos", id="DEN"))

  assert [g["name"] for g in games] == ["Broncos at Cardinals"]


def test_nfl_fetches_regular_season_and_playoffs(monkeypatch):
  urls = []

  def fakeFetch(url):
    urls.append(url)
    return fixture("nfl-den.json") if url.endswith("seasontype=2") else '{"events": []}'

  monkeypatch.setattr(scrapers, "fetch", fakeFetch)

  games = scrapers.fetchSchedule(team("Broncos", source="nfl", id="DEN"))

  assert urls == [
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/den/schedule?seasontype=2",
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/den/schedule?seasontype=3",
  ]
  assert len(games) == 2
