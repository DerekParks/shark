#!/usr/bin/env python
"""
Parse schedule ics from MBA webite (http://www.nba.com/nuggets/schedule)

Usage:
  nuggets.py <pathICS> <outCSV>

Options:
  -h --help     Show this screen.
  --version     Show version.

"""

from docopt import docopt
from ics import Calendar
from dateutil.parser import parse
import csv

if __name__ == "__main__":
  arguments = docopt(__doc__, version='Read MBA ICS 0.1')

  with open(arguments["<pathICS>"],"r") as f:
    c = Calendar(f.read().decode('iso-8859-1'))
    with open(arguments["<outCSV>"],"w") as csvfile:
      writer = csv.DictWriter(csvfile, fieldnames=["team","name", "start", "end", "band", "freq"])
      writer.writeheader()
      for event in c.events:
        print event.name, event.begin, event.end
        writer.writerow({'name': event.name, 'start': event.begin, 'end': event.end, 'band': "AM", "freq":"950", "team": "Nuggets"})
        


