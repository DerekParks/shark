#!/usr/bin/env python3
"""Record each game in the schedule CSV, rereading it while waiting.

Usage:
  readCSVRecord.py <pathCSV> <outPath>

Options:
  -h --help     Show this screen.
  --version     Show version.
"""

from docopt import docopt
from datetime import datetime, timezone
from dateutil import parser

import csv, glob, os, shlex, subprocess, sys, time

from config import setting

RECHECK_SEC = 3600
SCHEDULE_WAIT_SEC = 60
PARTIAL = ".partial"
RELAY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "relay.py")

def execute(cmd):
  print(cmd)
  subprocess.run(["bash", "-o", "pipefail", "-c", cmd], check=True)

def gameToStr(game, zone=None):
  return "%s-%s" % (game["team"], parser.parse(game["start"]).astimezone(zone).strftime("%Y-%m-%d-%H%M"))

def recordingPath(outpath, game):
  base = os.path.join(outpath, gameToStr(game))
  path, part = base + ".mp3", 1
  while os.path.exists(path) or os.path.exists(path + PARTIAL):
    part += 1
    path = "%s-%d.mp3" % (base, part)
  return path

def publish(partial):
  if os.path.exists(partial) and os.path.getsize(partial) > 0:
    final = partial[:-len(PARTIAL)]
    os.replace(partial, final)
    return final
  if os.path.exists(partial):
    os.remove(partial)
  return None

def recoverPartials(outpath):
  for partial in glob.glob(os.path.join(glob.escape(outpath), "*.mp3" + PARTIAL)):
    print("Recovered interrupted recording:", publish(partial) or "empty, removed")

def gameKey(game):
  return (game["team"], game["start"])

def getRecordCommand(RecordingDurationSec):
  recorder = ' '.join([
    'arecord'                        # audio recorder
  , '-q'                             # quiet
  , '-d {duration}'                  # recording time
  , '--max-file-time {duration}'     # recording time before switching files (must be >= recording time)
  , '-c 2'                           # input stream is 2 channels
  , '-f S16'                         # input stream is 16 bit signed
  , '-r 44100'                       # rate of input stream is 44.1kHz
  , '-D {device}'                    # audio generator
  , '-t raw'                         # output format is raw (don't use .wav, it cuts out after 3 hours and 22 minutes because of a size limit on .wav files)
  ]).format(
    duration = RecordingDurationSec, device = setting("SHARK_ALSA_DEVICE")
  )
  return recorder

def getMp3Command(filename, game):
  encoder = ' '.join([
      'lame'
    , '--quiet'               # quiet
    , '-r'               # raw format input
    , '-a'                    # downmix to mono
    #, '--resample 8'          # resample to rate
    #, '-V3'                   # ???
    #, '--vbr-new'             # ???
    #, '-q0'                   # quality level
    #, '-B16'                  # maximum bit rate
    #, '--lowpass 15.4'        # apply lowpass filter
    #, '--athaa-sensitivity 1' # ???
    , '--preset {bitrate}'    # average bitrate in kbps
    , '--tt {title}'          # title
    , '--ta {artist}'         # artist
    , '-'                     # read from standard input
    , '{filename}'            # write to filename
  ]).format(
      filename = shlex.quote(filename)
    , bitrate = int(setting("SHARK_BITRATE"))
    , title = shlex.quote(game["name"])
    , artist = shlex.quote(game["team"])
  )
  return encoder

def getStreamCommand(icecastURL, game):
  return ' '.join([
      'ffmpeg'
    , '-nostdin -loglevel warning'
    , '-f s16le -ar 44100 -ac 2 -i -'  # raw stream from arecord
    , '-c:a libmp3lame -ac 1 -b:a {bitrate}k'
    , '-content_type audio/mpeg'
    , '-ice_name {title}'
    , '-f mp3 {url}'
  ]).format(
      title = shlex.quote(game["name"])
    , bitrate = int(setting("SHARK_STREAM_BITRATE"))
    , url = shlex.quote(icecastURL)
  )

def runRecordGame(pipeline, game):
  try:
    freq = float(game['freq'])

    if game['band'].lower() == 'am':
      freq = freq / 1000

    # Configure the shark (set station, turn fin red to indicate recording)
    execute('fm -q %.2f' % (freq))

    # Record the game
    print('Recording ...', game)
    execute(pipeline)
    print('Recording complete.')
  except subprocess.CalledProcessError as err:
    print(err)

def postRecord(filename, game):
  print("Doing post record")

def recordGame(outpath, game, durationSec):
  partial = recordingPath(outpath, game) + PARTIAL
  recorder = getRecordCommand(durationSec)
  encoder = getMp3Command(partial, game)

  stages = [recorder, encoder]
  icecastURL = setting("SHARK_ICECAST_URL")
  if icecastURL:
    stages.insert(1, shlex.join([sys.executable, RELAY, getStreamCommand(icecastURL, game)]))
  pipeline = ' | '.join(stages)

  runRecordGame(pipeline, game)
  filename = publish(partial)
  if filename:
    postRecord(filename, game)
  else:
    print("Nothing was recorded for", game["name"])

def readGames(pathCSV):
  with open(pathCSV, newline="") as csvfile:
    return list(csv.DictReader(csvfile))

def nextAction(games, now, recorded):
  pending = [g for g in games if parser.parse(g["end"]) > now and gameKey(g) not in recorded]
  if not pending:
    return ("sleep", RECHECK_SEC)
  game = min(pending, key=lambda g: parser.parse(g["start"]))
  wait = int((parser.parse(game["start"]) - now).total_seconds())
  if wait > 0:
    print("Next game in %ds: %s" % (wait, game["name"]))
    return ("sleep", min(wait, RECHECK_SEC))
  return ("record", game, int((parser.parse(game["end"]) - now).total_seconds()))

def run(pathCSV, outPath):
  os.makedirs(outPath, exist_ok=True)
  recoverPartials(outPath)
  recorded = set()
  while True:
    if not os.path.exists(pathCSV):
      print("Waiting for", pathCSV)
      time.sleep(SCHEDULE_WAIT_SEC)
      continue
    action = nextAction(readGames(pathCSV), datetime.now(timezone.utc), recorded)
    if action[0] == "sleep":
      time.sleep(action[1])
    else:
      _, game, durationSec = action
      recorded.add(gameKey(game))
      recordGame(outPath, game, durationSec)

if __name__ == "__main__":
  arguments = docopt(__doc__, version='Read CSV and Record 0.3')

  run(arguments["<pathCSV>"], arguments["<outPath>"])
