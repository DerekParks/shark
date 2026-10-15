#!/usr/bin/env python3
"""
Fetch every team's schedule and merge them by priority into one recording schedule.

Usage:
  buildSchedule.py [--teams=<toml>] [--every=<hours>] <outCSV>
  buildSchedule.py --check [--teams=<toml>]

Options:
  -h --help        Show this screen.
  --version        Show version.
  --teams=<toml>   Teams in priority order, highest first [default: teams.toml].
  --every=<hours>  Keep running and rebuild this often; a failed build is retried after an hour.
  --check          Validate the teams file and exit.

"""
from docopt import docopt
import time, tomllib, traceback

import merge, scrapers

RETRY_SEC = 3600
REQUIRED = ("name", "source", "id", "band", "freq", "hours")
REQUIRED_BY_SOURCE = {"nhl": (), "nfl": (), "mlb": (), "nba": ("slug",)}


def teamProblems(team):
  missing = [k for k in REQUIRED + REQUIRED_BY_SOURCE.get(team.get("source"), ()) if k not in team]
  if missing:
    return ["missing " + ", ".join(missing)]
  problems = []
  if team["source"] not in REQUIRED_BY_SOURCE:
    problems.append("source must be one of " + ", ".join(REQUIRED_BY_SOURCE))
  if str(team["band"]).upper() not in ("AM", "FM"):
    problems.append("band must be AM or FM")
  try:
    float(team["freq"])
  except ValueError:
    problems.append("freq must be a number")
  if not isinstance(team["hours"], (int, float)) or team["hours"] <= 0:
    problems.append("hours must be a positive number")
  if "/" in team["name"]:
    problems.append("name can't contain /")
  return problems

def loadTeams(path):
  try:
    with open(path, "rb") as f:
      teams = tomllib.load(f).get("team", [])
  except FileNotFoundError:
    raise SystemExit("No teams file at %s; start from teams.example.toml" % path)
  if not teams:
    raise SystemExit("%s has no [[team]] entries" % path)
  problems = ["team %d (%s): %s" % (i + 1, t.get("name", "?"), p) for i, t in enumerate(teams) for p in teamProblems(t)]
  if problems:
    raise SystemExit("Problems in %s:\n  " % path + "\n  ".join(problems))
  return [dict(t, freq=str(t["freq"])) for t in teams]

def prioritize(gamesByTeam):
  merged = []
  for games in gamesByTeam:
    merge.addGames(games, merged)
  return merged

def build(teamsPath, outCSV):
  merged = prioritize(scrapers.fetchSchedule(team) for team in loadTeams(teamsPath))
  merge.writeCsv(outCSV, merged)
  print("Scheduled %d games" % len(merged))

def refreshForever(rebuild, everySec, sleep=time.sleep):
  while True:
    try:
      rebuild()
      wait = everySec
    except Exception:
      traceback.print_exc()
      wait = RETRY_SEC
    sleep(wait)


if __name__ == "__main__":
  arguments = docopt(__doc__, version='Build Schedule 0.2')

  rebuild = lambda: build(arguments["--teams"], arguments["<outCSV>"])
  if arguments["--check"]:
    print("%d teams OK" % len(loadTeams(arguments["--teams"])))
  elif arguments["--every"]:
    refreshForever(rebuild, float(arguments["--every"]) * 3600)
  else:
    rebuild()
