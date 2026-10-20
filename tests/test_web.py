import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import httpx2 as httpx
from fastapi.testclient import TestClient

import merge, web

NOW = datetime(2026, 10, 17, 1, 30, tzinfo=timezone.utc)
ICECAST = "http://icecast:8000/live"


def game(team, name, hoursFromNow, hours=3):
  start = NOW + timedelta(hours=hoursFromNow)
  return {"team": team, "name": name, "start": start, "end": start + timedelta(hours=hours), "band": "FM", "freq": "92.5"}


def client(tmpdir, games=(), icecast=None, **kwargs):
  schedule = tmpdir.join("merged.csv")
  if games:
    merge.writeCsv(str(schedule), list(games))
  out = tmpdir.ensure("out", dir=True)
  app = web.createApp(str(schedule), str(out), ICECAST, clock=lambda: NOW,
                      transport=httpx.MockTransport(icecast) if icecast else None, enhancedDir=str(tmpdir.join("enhanced")),
                      trimmedDir=str(tmpdir.join("trimmed")))
  return TestClient(app, **kwargs)


def test_schedule_lists_on_air_then_upcoming_and_drops_finished(tmpdir):
  games = [
    game("Nuggets", "Nuggets vs. Jazz", 20),
    game("Avalanche", "Avalanche vs. Penguins", -0.5),
    game("Rockies", "Rockies vs. Giants", -10),
  ]

  schedule = client(tmpdir, games).get("/api/schedule").json()

  assert [(g["name"], g["onAir"]) for g in schedule] == [("Avalanche vs. Penguins", True), ("Nuggets vs. Jazz", False)]


def test_schedule_is_empty_before_first_build(tmpdir):
  assert client(tmpdir).get("/api/schedule").json() == []


def test_recordings_newest_first_and_served(tmpdir, mp3):
  out = tmpdir.mkdir("out")
  mp3(out.join("Avalanche-2026-10-14-1830.mp3"), 1, "Avalanche vs. Kings", "Avalanche")
  mp3(out.join("Broncos-2026-10-15-1815.mp3"), 1, "Broncos at Chiefs", "Broncos")
  out.join("notes.txt").write("ignored")
  c = client(tmpdir)

  recordings = c.get("/api/recordings").json()

  assert [r["title"] for r in recordings] == ["Broncos at Chiefs (Oct 15, 2026)", "Avalanche vs. Kings (Oct 14, 2026)"]
  assert c.get(recordings[0]["url"]).content.startswith(b"ID3")


def test_recordings_support_range_requests_for_seeking(tmpdir, mp3):
  mp3(tmpdir.mkdir("out").join("Broncos-2026-10-15-1815.mp3"), 1, "Broncos at Chiefs", "Broncos")

  response = client(tmpdir).get("/recordings/Broncos-2026-10-15-1815.mp3", headers={"Range": "bytes=0-9"})

  assert response.status_code == 206
  assert len(response.content) == 10


def test_enhanced_copy_replaces_the_recording_and_seeks(tmpdir, mp3):
  mp3(tmpdir.mkdir("out").join("Broncos-2026-10-15-1815.mp3"), 1, "Broncos at Chiefs", "Broncos")
  copy = mp3(tmpdir.mkdir("enhanced").join("Broncos-2026-10-15-1815.mp3"), 2)
  c = client(tmpdir)

  url = c.get("/api/recordings").json()[0]["url"]
  enclosure = ET.fromstring(c.get("/feed.xml").content).find("channel/item/enclosure").get("url")
  response = c.get(url, headers={"Range": "bytes=0-9"})

  assert url == "enhanced/Broncos-2026-10-15-1815.mp3"
  assert enclosure == "http://testserver/" + url
  assert response.status_code == 206
  assert response.content == copy.read_binary()[:10]
  assert ('src="%s"' % url) in c.get("/").text


def test_trimmed_copy_is_served_ahead_of_the_enhanced_one(tmpdir, mp3):
  mp3(tmpdir.mkdir("out").join("Broncos-2026-10-15-1815.mp3"), 1, "Broncos at Chiefs", "Broncos")
  mp3(tmpdir.mkdir("enhanced").join("Broncos-2026-10-15-1815.mp3"), 2)
  copy = mp3(tmpdir.mkdir("trimmed").join("Broncos-2026-10-15-1815.mp3"), 3)
  c = client(tmpdir)

  url = c.get("/api/recordings").json()[0]["url"]
  response = c.get(url, headers={"Range": "bytes=0-9"})

  assert url == "trimmed/Broncos-2026-10-15-1815.mp3"
  assert response.status_code == 206
  assert response.content == copy.read_binary()[:10]


def test_feed_urls_follow_the_host_it_was_requested_on(tmpdir, mp3):
  mp3(tmpdir.mkdir("out").join("Broncos-2026-10-15-1815.mp3"), 1, "Broncos at Chiefs", "Broncos")
  c = client(tmpdir, base_url="http://turnpike.lan:8771")

  local = ET.fromstring(c.get("/feed.xml").content)
  tailnet = ET.fromstring(c.get("/feed.xml", headers={
    "Host": "sharksports.example.ts.net", "X-Forwarded-Proto": "https", "X-Forwarded-For": "100.64.0.7"}).content)

  assert local.find("channel/item/enclosure").get("url") == "http://turnpike.lan:8771/recordings/Broncos-2026-10-15-1815.mp3"
  assert tailnet.find("channel/item/enclosure").get("url") == "https://sharksports.example.ts.net/recordings/Broncos-2026-10-15-1815.mp3"


def test_feed_aliases_and_cover(tmpdir):
  c = client(tmpdir)

  for path in ("/feed.xml", "/feed", "/rss", "/podcast.xml"):
    response = c.get(path)
    assert response.headers["content-type"] == "application/rss+xml"
    assert ET.fromstring(response.content).findtext("channel/title") == "Shark Sports"
  assert c.head("/feed.xml").status_code == 200
  assert c.get("/cover.jpg").content.startswith(b"\xff\xd8")


def test_live_relays_the_icecast_mount(tmpdir):
  requested = []

  async def frames():
    for _ in range(100):
      yield b"\xff\xfb"

  def icecast(request):
    requested.append(str(request.url))
    return httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=frames())

  response = client(tmpdir, icecast=icecast).get("/live")

  assert requested == [ICECAST]
  assert response.headers["content-type"] == "audio/mpeg"
  assert response.content == b"\xff\xfb" * 100


def test_live_is_unavailable_when_nothing_is_streaming(tmpdir):
  assert client(tmpdir, icecast=lambda request: httpx.Response(404)).get("/live").status_code == 503


def test_live_is_unavailable_when_icecast_is_down(tmpdir):
  def refused(request):
    raise httpx.ConnectError("refused")

  assert client(tmpdir, icecast=refused).get("/live").status_code == 503


def test_page_shows_live_player_feed_link_and_escapes_names(tmpdir):
  games = [game("Avalanche", "Avalanche vs. <Penguins>", -0.5)]

  page = client(tmpdir, games).get("/").text

  assert 'src="live"' in page
  assert 'href="feed.xml"' in page
  assert "Avalanche vs. &lt;Penguins&gt;" in page
  assert "<Penguins>" not in page


def test_page_title_and_cover_come_from_environment(tmpdir, monkeypatch):
  cover = tmpdir.join("mine.jpg")
  cover.write_binary(b"\xff\xd8custom")
  monkeypatch.setenv("SHARK_FEED_TITLE", "Porch <Radio>")
  monkeypatch.setenv("SHARK_COVER", str(cover))
  c = client(tmpdir)

  assert "<title>Porch &lt;Radio&gt;</title>" in c.get("/").text
  assert c.get("/cover.jpg").content == b"\xff\xd8custom"


def test_recording_with_a_space_in_its_team_name_is_served(tmpdir, mp3):
  mp3(tmpdir.mkdir("out").join("Trail Blazers-2026-10-22-2000.mp3"), 1, "Trail Blazers vs. Suns", "Trail Blazers")
  c = client(tmpdir)

  url = c.get("/api/recordings").json()[0]["url"]

  assert url == "recordings/Trail%20Blazers-2026-10-22-2000.mp3"
  assert c.get("/" + url).content.startswith(b"ID3")
