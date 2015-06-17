#!/bin/env python
"""Read MLB CSV and Record
Reads in a schedule CSV from the MLB website records from Griffin RadioShark 1.

Usage:
  readCSVRecord.py <pathCSV> <stationID> (AM|FM) <outPath>

Options:
  -h --help     Show this screen.
  --version     Show version.
  AM AM station
  FM FM station
"""

from docopt import docopt
from datetime import datetime
from dateutil import tz
import csv, time, re, os, sched
from gaints import record
EST = tz.gettz('America/New_York')

class GameData:
  radioRegex = re.compile('.*Local Radio: (.*)')
  def __init__(self, row, stationRegx):
    self.startDateTime = datetime.strptime("%s %s" % (row["START_DATE"],row["START_TIME"]), "%x %I:%M %p")
    self.startDateTimeEST = datetime.strptime("%s %s" % (row["START_DATE"],row["START_TIME_ET"]), "%x %I:%M %p").replace(tzinfo=EST)

    self.description = row["SUBJECT"]
    self.location = row["LOCATION"]
    self.station = row["DESCRIPTION"]
    self.endDateTime = datetime.strptime("%s %s" % (row["END_DATE"],row["END_TIME"]), "%x %I:%M %p")
    self.endDateTimeEST = datetime.strptime("%s %s" % (row["END_DATE_ET"],row["END_TIME_ET"]), "%x %I:%M %p").replace(tzinfo=EST)
    self.row = row
    match = GameData.radioRegex.match(self.station)
    if match is not None:
      self.isOnStation = len(stationRegx.findall(match.group(0))) > 0 
    else:
      self.isOnStation = False
      
  def __repr__(self):
    return "Game: %s %s %s %s" % (self.startDateTime, self.description, self.location, self.isOnStation)
    
class AllGames:
  
  def __init__(self, path, station):
    self.path = path
    self.stationRegx = re.compile(station)
    
  def getNextGame(self):
    now = datetime.now(EST)
    for game in self.readGames():
      if game.startDateTimeEST > now and game.isOnStation:
        return game
  
  def readGames(self):
    with open(self.path, 'rb') as csvfile:
      csvReader = csv.DictReader(csvfile)
      for row in csvReader:
        yield GameData(row, self.stationRegx)

def ensure_dir(f):
  d = os.path.dirname(f)
  if not os.path.exists(d):
    os.makedirs(d)

if __name__ == "__main__":
  arguments = docopt(__doc__, version='Read MLB CSV and Record 0.1')

  games = AllGames( arguments["<pathCSV>"], arguments["<stationID>"])
  outPath = arguments["<outPath>"]
  ensure_dir(outPath)
  scheduler = sched.scheduler(time.time, time.sleep)
  priority = 0
  now = datetime.now(EST)
  
  if arguments["AM"] is not None:
    station = "-am " + arguments["<stationID>"]
  else:
    station = "-fm " + arguments["<stationID>"]
  
  for game in games.readGames():
    if game.startDateTimeEST > now and game.isOnStation:
      scheduler.enterabs(time.mktime(game.startDateTime.timetuple()), priority, record, (outPath, station, game, "mp3"))
      priority = priority + 1
  scheduler.run()
  
