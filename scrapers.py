"""Fetch team schedules from league sites as merge-ready game rows."""

import json, re, urllib.request
from datetime import date, datetime, timedelta

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"

NHL_GAME_TYPES = {2, 3}
NBA_GAME_ID_PREFIXES = ("002", "004", "005", "006")
MLB_GAME_TYPES = {"R", "F", "D", "L", "W"}
NFL_SKIPPED_STATUSES = {"STATUS_POSTPONED", "STATUS_CANCELED"}
NFL_SEASON_TYPES = (2, 3)

def fetch(url):
  request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
  with urllib.request.urlopen(request, timeout=60) as response:
    return response.read().decode("utf-8")

def parseUTC(stamp):
  return datetime.fromisoformat(stamp.replace("Z", "+00:00"))

def gameRow(team, isHome, opponent, start):
  return {
    "team": team["name"],
    "name": "%s %s %s" % (team["name"], "vs." if isHome else "at", opponent),
    "start": start,
    "end": start + timedelta(hours=team["hours"]),
    "band": team["band"],
    "freq": team["freq"],
  }

def nhlGames(data, team):
  games = []
  for game in data["games"]:
    if game["gameType"] not in NHL_GAME_TYPES or game["gameScheduleState"] != "OK":
      continue
    isHome = game["homeTeam"]["abbrev"] == team["id"]
    opponent = game["awayTeam" if isHome else "homeTeam"]["commonName"]["default"]
    games.append(gameRow(team, isHome, opponent, parseUTC(game["startTimeUTC"])))
  return games

def nbaGames(html, team):
  nextData = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
  schedule = json.loads(nextData.group(1))["props"]["pageProps"]["scheduleData"]["schedule"]
  games = []
  for game in schedule:
    if not game["gameId"].startswith(NBA_GAME_ID_PREFIXES) or game["gameStatusText"].strip() == "PPD":
      continue
    isHome = game["homeTeam"]["teamTricode"] == team["id"]
    opponent = game["awayTeam" if isHome else "homeTeam"]["teamName"]
    games.append(gameRow(team, isHome, opponent, parseUTC(game["gameTimeUTC"])))
  return games

def mlbGames(data, team):
  games = []
  for day in data["dates"]:
    for game in day["games"]:
      status = game["status"]
      if game["gameType"] not in MLB_GAME_TYPES or status["startTimeTBD"] or status["detailedState"] in ("Postponed", "Cancelled"):
        continue
      isHome = game["teams"]["home"]["team"]["id"] == team["id"]
      opponent = game["teams"]["away" if isHome else "home"]["team"]["teamName"]
      games.append(gameRow(team, isHome, opponent, parseUTC(game["gameDate"])))
  return games

def nflGames(data, team):
  games = []
  for event in data["events"]:
    competition = event["competitions"][0]
    if not event["timeValid"] or competition["status"]["type"]["name"] in NFL_SKIPPED_STATUSES:
      continue
    sides = {c["homeAway"]: c["team"] for c in competition["competitors"]}
    isHome = sides["home"]["abbreviation"] == team["id"]
    opponent = sides["away" if isHome else "home"]["shortDisplayName"]
    games.append(gameRow(team, isHome, opponent, parseUTC(event["date"])))
  return games

def fetchSchedule(team):
  if team["source"] == "nhl":
    return nhlGames(json.loads(fetch("https://api-web.nhle.com/v1/club-schedule-season/%s/now" % team["id"])), team)
  if team["source"] == "nba":
    return nbaGames(fetch("https://www.nba.com/%s/schedule" % team["slug"]), team)
  if team["source"] == "mlb":
    today = date.today()
    url = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=%s&startDate=%s&endDate=%s&hydrate=team" % (team["id"], today, today + timedelta(days=365))
    return mlbGames(json.loads(fetch(url)), team)
  if team["source"] == "nfl":
    url = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/%s/schedule?seasontype=%d"
    return [g for seasonType in NFL_SEASON_TYPES for g in nflGames(json.loads(fetch(url % (team["id"].lower(), seasonType))), team)]
  raise ValueError("Unknown schedule source: %s" % team["source"])
