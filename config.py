"""Settings read from the environment, with their defaults."""

import os

DEFAULTS = {
  "SHARK_ALSA_DEVICE": "hw:CARD=RadioSHARK,DEV=0",
  "SHARK_ICECAST_URL": "",
  "SHARK_BITRATE": "32",
  "SHARK_STREAM_BITRATE": "64",
  "SHARK_FEED_TITLE": "Shark Sports",
  "SHARK_FEED_DESCRIPTION": "Games recorded off the radio by a Griffin RadioSHARK.",
  "SHARK_FEED_AUTHOR": "Shark",
  "SHARK_COVER": os.path.join(os.path.dirname(os.path.abspath(__file__)), "cover.jpg"),
}

def setting(name):
  return os.environ.get(name) or DEFAULTS[name]
