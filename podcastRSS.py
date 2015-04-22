#!/bin/env python
"""Create an rss file from a directory of podcasts

Usage:
  podcastRSS.py <audioDirectory> <baseURL>

Options:
  -h --help     Show this screen.
  --version     Show version.
"""

from docopt import docopt
from feedgen.feed import FeedGenerator
from mutagen.id3 import ID3
import os

MIME_TYPES = { '.ogg': 'audio/ogg', '.mp3': 'audio/mpeg' , '.spx': 'audio/ogg' }

class Feed:
  def __init__(self, baseURL, audioDir):
    self.baseURL = baseURL
    self.dir = audioDir
    self.fg = FeedGenerator()
    self.fg.load_extension('podcast')
    self.fg.id(baseURL)
    self.fg.title('Yesterdays Baseball')
    self.fg.author( name='MLB' )
    self.fg.link( href=baseURL, rel='alternate' )
    self.fg.logo('http://en.wikipedia.org/wiki/Major_League_Baseball_logo#/media/File:Major_League_Baseball.svg')
    self.fg.icon('http://en.wikipedia.org/wiki/Major_League_Baseball_logo#/media/File:Major_League_Baseball.svg')
    self.fg.subtitle("Awright, 'arry? See that ludicrous display last night?")
    self.fg.link( href=baseURL+'podcast.xml', rel='self' )
    self.fg.language('en')
    self.fg.podcast.itunes_explicit('no')
    self.fg.podcast.itunes_complete('no')
    self.fg.podcast.itunes_new_feed_url(baseURL+'podcast.xml')
    self.fg.podcast.itunes_summary("Awright, 'arry? See that ludicrous display last night?")
    self.addAllEntries()

  def __repr__(self):
    return self.fg.rss_str(pretty=True)

  def addAllEntries(self):
    for root, dirs, files in os.walk(self.dir):
      for f in files:
        if os.path.splitext(f)[1] in MIME_TYPES.keys(): 
          self.addEntry(root,f)

  def addEntry(self,root,f):
    path = os.path.join(root,f)
    fileName, fileExtension = os.path.splitext(f)
    print "Adding...",path
    fe = self.fg.add_entry()
    fe.id(self.baseURL+f)
    mediafile = ID3(path)

    fe.title(mediafile['TIT2'].text[0] + " " + fileName)
    fe.summary(mediafile['TPE1'].text[0])
    fe.content(mediafile['TPE1'].text[0])

    fe.enclosure(self.baseURL+f, 0, MIME_TYPES[fileExtension])

if __name__ == "__main__":
  arguments = docopt(__doc__, version='Podcast Directory to RSS 0.1')
  baseURL = arguments['<baseURL>']
  dirOut = arguments['<audioDirectory>']
  feed = Feed(arguments['<baseURL>'], dirOut)
  
  print feed
  feed.fg.rss_file(os.path.join(dirOut,"podcast.xml"))
  
  
      
