"""Podcast RSS for a directory of game recordings, serving the enhanced copy of a recording once it exists,
with every URL under the base URL it was requested from."""

import os, re
from urllib.parse import quote
from datetime import datetime
from pathlib import Path

from feedgen.feed import FeedGenerator
from mutagen import MutagenError
from mutagen.mp3 import MP3

from config import setting

RECORDING_NAME = re.compile(r"^(?P<team>.+)-(?P<stamp>\d{4}-\d{2}-\d{2}-\d{4})(?:-(?P<part>\d+))?$")

def served(path, enhanced):
  copy = Path(enhanced, path.name) if enhanced else None
  return copy if copy and copy.is_file() else path

def episode(path, enhanced=None):
  match = RECORDING_NAME.match(path.stem)
  start = datetime.strptime(match["stamp"], "%Y-%m-%d-%H%M").astimezone() if match else datetime.fromtimestamp(path.stat().st_mtime).astimezone()
  tags = MP3(path).tags or {}
  name = tags["TIT2"].text[0] if "TIT2" in tags else path.stem
  part = int(match["part"]) if match and match["part"] else 1
  audio = served(path, enhanced)
  return {
    "file": path.name,
    "url": ("recordings/" if audio == path else "enhanced/") + quote(path.name),
    "title": "%s (%s)%s" % (name, start.strftime("%b %-d, %Y"), ", part %d" % part if part > 1 else ""),
    "team": tags["TPE1"].text[0] if "TPE1" in tags else (match["team"] if match else ""),
    "start": start,
    "part": part,
    "bytes": audio.stat().st_size,
    "seconds": round(MP3(audio).info.length),
  }

def episodes(directory, enhanced=None):
  eps = []
  for path in Path(directory).glob("*.mp3") if os.path.isdir(directory) else []:
    try:
      eps.append(episode(path, enhanced))
    except MutagenError as err:
      print("Skipping unreadable recording %s: %s" % (path.name, err))
  return sorted(eps, key=lambda e: (e["start"], e["part"]), reverse=True)

def render(eps, baseURL):
  title, summary, author = setting("SHARK_FEED_TITLE"), setting("SHARK_FEED_DESCRIPTION"), setting("SHARK_FEED_AUTHOR")
  fg = FeedGenerator()
  fg.load_extension("podcast")
  fg.id(baseURL)
  fg.title(title)
  fg.description(summary)
  fg.author(name=author)
  fg.link(href=baseURL + "feed.xml", rel="self")
  fg.link(href=baseURL, rel="alternate")
  fg.image(baseURL + "cover.jpg", title, baseURL)
  fg.language("en")
  fg.podcast.itunes_author(author)
  fg.podcast.itunes_image(baseURL + "cover.jpg")
  fg.podcast.itunes_explicit("no")
  fg.podcast.itunes_summary(summary)
  for e in reversed(eps):
    fe = fg.add_entry()
    fe.guid(e["file"], permalink=False)
    fe.title(e["title"])
    fe.description(e["team"])
    fe.published(e["start"])
    fe.enclosure(baseURL + e["url"], str(e["bytes"]), "audio/mpeg")
    fe.podcast.itunes_duration(e["seconds"])
  return fg.rss_str(pretty=True)
