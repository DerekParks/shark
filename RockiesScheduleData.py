#!/usr/bin/env python
"""
Parse schedule csv from MLB webite (http://mlb.mlb.com/schedule/downloadable.jsp?c_id=col#csv-format)

Usage:
  RockiesScheduleData.py <pathCSV> <outCSV>

Options:
  -h --help     Show this screen.
  --version     Show version.

"""

from docopt import docopt
import re
import csv
from datetime import datetime
from dateutil import tz

EST = tz.gettz('America/New_York')

class RockiesGame:
  def __init__(self, row):
    self.startDateTime = datetime.strptime("%s %s" % (row["START DATE"],row["START TIME"]), "%x %I:%M %p")
    self.startDateTimeEST = datetime.strptime("%s %s" % (row["START DATE"],row["START TIME ET"]), "%x %I:%M %p").replace(tzinfo=EST)

    self.description = row["SUBJECT"]
    self.location = row["LOCATION"]
    
    self.endDateTime = datetime.strptime("%s %s" % (row["END DATE"],row["END TIME"]), "%x %I:%M %p")
    self.endDateTimeEST = datetime.strptime("%s %s" % (row["END DATE ET"],row["END TIME ET"]), "%x %I:%M %p").replace(tzinfo=EST)
    self.row = row
      
  def __repr__(self):
    return "Game: %s %s %s" % (self.startDateTime, self.description, self.location)

class RockiesScheduleData:
  
  def __init__(self, path):
    self.path = path
    
  def getNextGame(self):
    now = datetime.now(EST)
    for game in self.readGames():
      if game.startDateTimeEST > now:
        return game
  
  def readGames(self):
    with open(self.path, 'rb') as csvfile:
      csvReader = csv.DictReader(csvfile)
      for row in csvReader:
        yield RockiesGame(row)

if __name__ == "__main__":
  arguments = docopt(__doc__, version='Read MLB CSV 0.2')

  games = RockiesScheduleData(arguments["<pathCSV>"]).readGames()

  with open(arguments["<outCSV>"],"w") as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=["team","name", "start", "end", "band", "freq"])
    writer.writeheader()
    for game in games:
      print game.description, game.startDateTimeEST, game.endDateTimeEST
      writer.writerow({'name': game.description, 'start': game.startDateTimeEST, 'end': game.endDateTimeEST, 'band': "FM", "freq":"94.1", "team": "Rockies"})

