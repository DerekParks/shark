#!/usr/bin/env python
"""
Merge csv schedules from teams and remove conflicts.

Usage:
  merge.py <outCSV> <CSVfiles>...

Options:
  -h --help     Show this screen.
  --version     Show version.

"""
from docopt import docopt
import csv
from dateutil import parser
from SortedCollection import SortedCollection


def addFile(filename, games):
  
  with open(filename, 'r') as csvfile:
    reader = csv.DictReader(csvfile)
    for row in reader:
      row['start'] = parser.parse(row['start'])
      row['end'] = parser.parse(row['end'])
      try:
        item = games.find_le(row['start'])
        if item['end'] < row['start']:
          games.insert(row)
        else:
          print "Skipping game: %s,%s,%s it conflicts with %s,%s,%s" % (row['name'], row['start'], row['end'], item['name'], item['start'], item['end']) 
      except ValueError:
        games.insert(row)


if __name__ == "__main__":
  arguments = docopt(__doc__, version='Merge 0.1')
  mergedGames = SortedCollection([], key=lambda k: k['start'])

  for filename in arguments["<CSVfiles>"]:
    addFile(filename, mergedGames)

  with open(arguments["<outCSV>"],"w") as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=["team","name", "start", "end", "band", "freq"])
    writer.writeheader()
    for game in mergedGames:
      writer.writerow(game)
