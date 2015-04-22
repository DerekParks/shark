"""
My changes to: https://github.com/KenKundert/radioshark/gaints.py
"""

import os, sys
from fileutils import makePath, expandPath, execute, ExecuteError, remove, mkdir
SHARK_EXE = "/usr/bin/sudo ./shark"
RecordingDurationSec = 3600 * 4
SharkAudioAddr="hw:1,0"
SharkCtrlAddr=0
def record(path, station, nextGame, Encoder):
    filename = os.path.join(path, nextGame.startDateTime.strftime("%m-%d")+"."+Encoder)

    # build the commands
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
        duration = RecordingDurationSec, device = SharkAudioAddr
    )

    if Encoder == 'ogg':
        encoder = ' '.join([
            'oggenc'                     # Ogg encoder
          , '-Q'                         # quiet
          , '-r'                         # input format is raw
          , '--resample 8000'            # sample rate (8000 and 11025 are suitable choices for AM radio)
          , '--downmix'                  # convert from stereo to mono
          , '-q 0'                       # quality level (range is -1 to 10 with 10 being highest)
          , '--ignorelength'             # Allow input stream to exceed 4GB
          , '-o "{filename}"'            # output file name
          , '--title "{title} ({date})"' # title
          , '--album "{title}"'          # album
          , '--artist "{artist}"'        # artist
          , '--date "{date}"'            # date
          , '-'                          # read from standard input
        ]).format(
            filename = filename
          , title = nextGame.description
          , artist = nextGame.station
          , date = nextGame.startDateTime.__repr__()
        )
    elif Encoder == 'mp3':
        # DP- turned off old settings moved to 32kbps average; sounds much better
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
          , title = nextGame.description
          , artist = nextGame.station
          , date = nextGame.startDateTime.__repr__()
        )
    elif Encoder == 'spx':
        # This generates files that sound a little better than the ogg files but
        # are much larger (odd because it is based on ogg and it tailored for
        # the spoken word, perhaps it is because I cannot get the -vbr option to
        # work). I am using the wideband option because it sounded
        # better and took less space than the narrowband option.
        encoder = ' '.join([
            'speexenc'
          , '-w'                    # wideband
          #, '--16bit'              # 16 bit raw input stream
          #, '--le'                 # little endian input stream
          #, '--stereo'             # stereo input stream
          , '--title "{title}"'     # title
          , '--author "{artist}"'   # artist
          , '-'                     # read from standard input
          , '{filename}'            # write to filename
        ]).format(
            filename = filename
          , title = nextGame.description
          , artist = nextGame.station
          , date = nextGame.startDateTime.__repr__()
        )
    else:
        raise AssertionError, "%s: Unknown encoder" % encoder

    pipeline = '{recorder} | {encoder}'.format(
        recorder=recorder, encoder=encoder
    )

    try:
        # Configure the shark (set station, turn fin red to indicate recording)
        execute('%s %s %s' % (SHARK_EXE, station, SharkCtrlAddr))
        execute('%s -blue 0 %s' % (SHARK_EXE,SharkCtrlAddr))
        execute('%s -red 1 %s' % (SHARK_EXE,SharkCtrlAddr))

        # Record the game
        print 'Recording ...', nextGame
        execute(pipeline)
        print 'Recording complete.'

        # Turn the fin back to blue to indicate not recording
        execute('%s -red 0 %s' % (SHARK_EXE,SharkCtrlAddr))
        execute('%s -blue 63 %s' % (SHARK_EXE,SharkCtrlAddr))
        
        if os.path.exists("./postRec.sh"):
          os.system("/bin/sh " + "./postRec.sh")
        
    except ExecuteError, err:
        print err
        sys.exit()



