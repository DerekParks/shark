import os

import pytest
from mutagen.id3 import ID3, TIT2, TPE1

FRAME = b"\xff\xfb\x90\x64" + bytes(413)  # MPEG-1 Layer III, 128 kbps, 44.1 kHz, no padding
FRAMES_PER_SECOND = 44100 / 1152


def writeMp3(path, seconds, title=None, artist=None, mtime=None):
  path.write_binary(FRAME * round(seconds * FRAMES_PER_SECOND))
  if title:
    tags = ID3()
    tags.add(TIT2(encoding=3, text=title))
    tags.add(TPE1(encoding=3, text=artist))
    tags.save(str(path))
  if mtime is not None:
    os.utime(str(path), (mtime, mtime))
  return path


@pytest.fixture
def mp3():
  return writeMp3
