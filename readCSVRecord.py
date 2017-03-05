#!/usr/bin/env python
"""Read CSV and Schedule Recording

Usage:
  readCSVRecord.py <pathCSV> <outPath>

Options:
  -h --help     Show this screen.
  --version     Show version.
"""

from docopt import docopt
from datetime import datetime
import csv, time, re, os, sched
from gaints import record

def ensure_dir(f):
  d = os.path.dirname(f)
  if not os.path.exists(d):
    os.makedirs(d)

if __name__ == "__main__":
  arguments = docopt(__doc__, version='Read CSV and Record 0.1')

  priority = 0
  scheduler = sched.scheduler(time.time, time.sleep)
  outPath = arguments["<outPath>"]
  ensure_dir(outPath)
  with open(arguments["<pathCSV>"],"r") as csvfile:
    reader = csv.DictReader(csvfile)
    for game in reader:
	print game
	priority = priority + 1  	
  """
  now = datetime.now(EST)
  
  for game in games.readGames():
    if game.startDateTimeEST > now and game.isOnStation:
      scheduler.enterabs(time.mktime(game.startDateTime.timetuple()), priority, record, (outPath, station, game, "mp3"))
  print "Next game", scheduler.queue[0]
  scheduler.run()
  """
