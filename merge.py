#!/usr/bin/env python3
"""
Merge csv schedules from teams and remove conflicts.

Usage:
  merge.py <outCSV> <CSVfiles>...

Options:
  -h --help     Show this screen.
  --version     Show version.

"""
from docopt import docopt
from bisect import bisect_left, bisect_right, insort_left
import csv, os
from dateutil import parser


def gameStart(game):
  return game['start']

def findConflict(games, row):
  i = bisect_right(games, row['start'], key=gameStart)
  if i and games[i-1]['end'] >= row['start']:
    return games[i-1]
  i = bisect_left(games, row['start'], key=gameStart)
  if i != len(games) and games[i]['start'] <= row['end']:
    return games[i]
  return None

def addGames(rows, games):
  for row in rows:
    item = findConflict(games, row)
    if item is None:
      insort_left(games, row, key=gameStart)
    else:
      print("Skipping game: %s,%s,%s it conflicts with %s,%s,%s" % (row['name'], row['start'], row['end'], item['name'], item['start'], item['end']))

def addFile(filename, games):
  with open(filename, newline='') as csvfile:
    rows = list(csv.DictReader(csvfile))
  for row in rows:
    row['start'] = parser.parse(row['start'])
    row['end'] = parser.parse(row['end'])
  addGames(rows, games)

def writeCsv(filename, games):
  partial = filename + ".partial"
  with open(partial, "w", newline="") as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=["team","name", "start", "end", "band", "freq"])
    writer.writeheader()
    for game in games:
      writer.writerow(game)
  os.replace(partial, filename)


if __name__ == "__main__":
  arguments = docopt(__doc__, version='Merge 0.2')
  mergedGames = []

  for filename in arguments["<CSVfiles>"]:
    addFile(filename, mergedGames)

  writeCsv(arguments["<outCSV>"], mergedGames)
