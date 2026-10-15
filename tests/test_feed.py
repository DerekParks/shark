import xml.etree.ElementTree as ET
from datetime import datetime

import feed

BASE = "https://sharksports.example.ts.net/"
ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"


def render(directory, base=BASE):
  return ET.fromstring(feed.render(feed.episodes(str(directory)), base)).find("channel")


def test_one_item_per_recording_newest_first(tmpdir, mp3):
  mp3(tmpdir.join("Avalanche-2026-10-16-1900.mp3"), 2, "Avalanche vs. Penguins", "Avalanche")
  mp3(tmpdir.join("Broncos-2026-10-15-1815.mp3"), 2, "Broncos at Chiefs", "Broncos")
  tmpdir.join("notes.txt").write("ignored")
  tmpdir.join("Rockies-2026-10-16-1910.mp3.partial").write("in progress")

  items = render(tmpdir).findall("item")

  assert [(i.findtext("title"), i.findtext("description")) for i in items] == [
    ("Avalanche vs. Penguins (Oct 16, 2026)", "Avalanche"),
    ("Broncos at Chiefs (Oct 15, 2026)", "Broncos"),
  ]


def test_every_url_is_under_the_requested_base(tmpdir, mp3):
  mp3(tmpdir.join("Avalanche-2026-10-16-1900.mp3"), 2, "Avalanche vs. Penguins", "Avalanche")

  for base in (BASE, "http://turnpike.lan:8771/"):
    channel = render(tmpdir, base)
    enclosure = channel.find("item/enclosure")
    assert channel.findtext("link") == base
    assert channel.find(ITUNES + "image").get("href") == base + "cover.jpg"
    assert enclosure.get("url") == base + "recordings/Avalanche-2026-10-16-1900.mp3"


def test_guid_survives_relocation(tmpdir, mp3):
  mp3(tmpdir.join("Avalanche-2026-10-16-1900.mp3"), 2, "Avalanche vs. Penguins", "Avalanche")

  guids = {render(tmpdir, base).find("item/guid").text for base in (BASE, "http://localhost:8771/")}

  assert guids == {"Avalanche-2026-10-16-1900.mp3"}


def test_enclosure_has_size_type_and_duration(tmpdir, mp3):
  path = mp3(tmpdir.join("Broncos-2026-10-15-1815.mp3"), 3, "Broncos at Chiefs", "Broncos")

  item = render(tmpdir).find("item")

  assert item.find("enclosure").get("length") == str(path.size())
  assert item.find("enclosure").get("type") == "audio/mpeg"
  assert item.findtext(ITUNES + "duration") == "3"


def test_published_at_local_start_from_filename(tmpdir, mp3):
  mp3(tmpdir.join("Broncos-2026-10-15-1815.mp3"), 1, "Broncos at Chiefs", "Broncos")

  pubDate = render(tmpdir).find("item").findtext("pubDate")

  assert datetime.strptime(pubDate, "%a, %d %b %Y %H:%M:%S %z") == datetime(2026, 10, 15, 18, 15).astimezone()


def test_later_parts_of_a_rejoined_game_are_their_own_episodes(tmpdir, mp3):
  mp3(tmpdir.join("Avalanche-2026-10-16-1900.mp3"), 1, "Avalanche vs. Penguins", "Avalanche")
  mp3(tmpdir.join("Avalanche-2026-10-16-1900-2.mp3"), 1, "Avalanche vs. Penguins", "Avalanche")

  titles = [i.findtext("title") for i in render(tmpdir).findall("item")]

  assert titles == ["Avalanche vs. Penguins (Oct 16, 2026), part 2", "Avalanche vs. Penguins (Oct 16, 2026)"]


def test_untagged_or_unparseable_names_fall_back(tmpdir, mp3):
  mp3(tmpdir.join("mystery.mp3"), 1, mtime=1_000_000)

  item = render(tmpdir).find("item")

  assert item.findtext("title") == "mystery (%s)" % datetime.fromtimestamp(1_000_000).strftime("%b %-d, %Y")


def test_unreadable_recording_is_left_out(tmpdir, mp3):
  tmpdir.join("Nuggets-2026-10-20-1900.mp3").write("")
  mp3(tmpdir.join("Broncos-2026-10-15-1815.mp3"), 1, "Broncos at Chiefs", "Broncos")

  assert [i.findtext("guid") for i in render(tmpdir).findall("item")] == ["Broncos-2026-10-15-1815.mp3"]


def test_empty_directory_is_a_valid_empty_feed(tmpdir):
  channel = render(tmpdir.join("missing"))

  assert channel.findtext("title") == "Shark Sports"
  assert channel.findall("item") == []


def test_channel_details_come_from_environment(tmpdir, monkeypatch):
  monkeypatch.setenv("SHARK_FEED_TITLE", "Porch Radio")
  monkeypatch.setenv("SHARK_FEED_DESCRIPTION", "Games from the back porch.")
  monkeypatch.setenv("SHARK_FEED_AUTHOR", "Derek")

  channel = render(tmpdir)

  assert channel.findtext("title") == "Porch Radio"
  assert channel.findtext("description") == "Games from the back porch."
  assert channel.findtext(ITUNES + "author") == "Derek"


def test_enclosure_urls_are_escaped(tmpdir, mp3):
  mp3(tmpdir.join("Trail Blazers-2026-10-22-2000.mp3"), 1, "Trail Blazers vs. Suns", "Trail Blazers")

  enclosure = render(tmpdir).find("item/enclosure").get("url")

  assert enclosure == BASE + "recordings/Trail%20Blazers-2026-10-22-2000.mp3"
