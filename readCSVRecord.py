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
from dateutil import parser

import csv, time, re, os, sched
from fileutils import execute, ExecuteError

SharkAudioAddr="1"

def ensure_dir(f):
  d = os.path.dirname(f)
  if not os.path.exists(d):
    os.makedirs(d)

def gameToStr(game):
  return "%s-%s" % (game["team"],game["start"][:10]) 

def getGameDurationSec(game):
  start = parser.parse(game["start"])
  end = parser.parse(game["end"])

  return int((end - start).total_seconds())

def getRecordCommand(game):
  RecordingDurationSec = getGameDurationSec(game)
  print RecordingDurationSec

  recorder = ' '.join([
    'arecord'                        # audio recorder
  , '-q'                             # quiet
  , '-d {duration}'                  # recording time
  , '--max-file-time {duration}'     # recording time before switching files (must be >= recording time)
  , '-c 2'                           # input stream is 2 channels
  , '-f S16'                         # input stream is 16 bit signed
  , '-r 44100'                       # rate of input stream is 44.1kHz
  , '-d {device}'                    # audio generator
  , '-t raw'                         # output format is raw (don't use .wav, it cuts out after 3 hours and 22 minutes because of a size limit on .wav files)
  ]).format(
    duration = RecordingDurationSec, device = SharkAudioAddr
  )
  return recorder

def getMp3Command(filename, game):
  encoder = ' '.join([
      'lame'
    , '--quiet'               # quiet
    , '-r'               # raw format input
    #, '--resample 8'          # resample to rate
    #, '-V3'                   # ???
    #, '--vbr-new'             # ???
    #, '-q0'                   # quality level
    #, '-B16'                  # maximum bit rate
    #, '--lowpass 15.4'        # apply lowpass filter
    #, '--athaa-sensitivity 1' # ???
    , '--preset 32'           # average bitrate of 32kbps
    , '--tt "{title}"'        # title
    , '--ta "{artist}"'       # artist
    , '-'                     # read from standard input
    , '{filename}'            # write to filename
  ]).format(
      filename = filename
    , title = game["name"]
    , artist = game["team"]
    , date = game["start"]
  )
  return encoder

def runRecordGame(pipeline, game):
  try:
    freq = float(game['freq'])

    if game['band'] == 'am':
      freq = freq / 1000

    # Configure the shark (set station, turn fin red to indicate recording)
    execute('fm -q %.2f' % (freq))

    # Record the game
    print 'Recording ...', game
    execute(pipeline)
    print 'Recording complete.'
  except ExecuteError, err:
    print err

def postRecord(filename, game):
  print "Doing post record"

def recordGame(outpath, game):
  filename = os.path.join(outpath, gameToStr(game)+".mp3")
  recorder = getRecordCommand(game)
  encoder = getMp3Command(filename, game)

  pipeline = '{recorder} | {encoder}'.format(
        recorder=recorder, encoder=encoder
  )

  print pipeline
  
  postRecord(filename, game)

if __name__ == "__main__":
  arguments = docopt(__doc__, version='Read CSV and Record 0.1')

  priority = 0
  scheduler = sched.scheduler(time.time, time.sleep)
  outPath = arguments["<outPath>"]
  ensure_dir(outPath)
  
  now = datetime.utcnow()

  with open(arguments["<pathCSV>"],"r") as csvfile:
    reader = csv.DictReader(csvfile)
    for game in reader:
      start = parser.parse(game["start"]) 
      if start > datetime.now(start.tzinfo):
        print priority, game, gameToStr(game)
        scheduler.enterabs(time.mktime(start.timetuple()), priority, recordGame, (outPath, game))
        priority = priority + 1

  print "Next game:"

  for scheduledGame in scheduler.queue[0]:
    print scheduledGame

  next = scheduler.queue[0]
  next.action(*next.argument)
  scheduler.run()

