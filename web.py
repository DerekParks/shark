#!/usr/bin/env python3
"""Shark web app: what's on air, the live stream, upcoming games, recordings and the podcast feed.

Usage:
  web.py [--host=<host>] [--port=<port>] [--schedule=<csv>] [--recordings=<dir>] [--icecast=<url>]

Options:
  -h --help            Show this screen.
  --host=<host>        Address to bind [default: 127.0.0.1].
  --port=<port>        Port to bind [default: 8771].
  --schedule=<csv>     Merged schedule [default: merged.csv].
  --recordings=<dir>   Recordings directory [default: out].
  --icecast=<url>      Icecast mount relayed at /live [default: http://127.0.0.1:8770/live].
"""

import html, os
from datetime import datetime, timezone
from urllib.parse import quote

import httpx2 as httpx
from dateutil import parser
from docopt import docopt
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

import feed, readCSVRecord
from config import setting

UPCOMING_LIMIT = 20
LIVE_TIMEOUT = httpx.Timeout(10, read=30)

def schedule(path, now):
  if not os.path.exists(path):
    return []
  games = []
  for game in readCSVRecord.readGames(path):
    start, end = parser.parse(game["start"]), parser.parse(game["end"])
    if end > now:
      games.append(dict(game, start=start.isoformat(), end=end.isoformat(), onAir=start <= now))
  games.sort(key=lambda g: g["start"])
  return games[:UPCOMING_LIMIT]

def recordings(directory):
  return [{"file": e["file"], "title": e["title"], "team": e["team"], "start": e["start"].isoformat(),
           "bytes": e["bytes"], "seconds": e["seconds"], "url": "recordings/" + quote(e["file"])}
          for e in feed.episodes(directory)]

def localTime(stamp):
  return datetime.fromisoformat(stamp).astimezone().strftime("%a %b %-d, %-I:%M %p")

def renderPage(games, files):
  e = html.escape
  title = e(setting("SHARK_FEED_TITLE"))
  onAir = next((g for g in games if g["onAir"]), None)
  if onAir:
    hero = '<p class="live">On air: <b>%s</b></p><audio controls preload="none" src="live"></audio>' % e(onAir["name"])
  elif games:
    hero = '<p>Next up: <b>%s</b> — %s</p>' % (e(games[0]["name"]), e(localTime(games[0]["start"])))
  else:
    hero = "<p>Nothing scheduled.</p>"
  rows = "".join('<tr%s><td>%s</td><td>%s</td><td>%s %s</td></tr>' % (
    ' class="live"' if g["onAir"] else "", e(localTime(g["start"])), e(g["name"]), e(g["freq"]), e(g["band"])) for g in games)
  items = "".join('<li><span>%s</span><audio controls preload="none" src="%s"></audio></li>' % (
    e(f["title"]), e(f["url"])) for f in files)
  return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s</title>
<link rel="icon" href="cover.jpg">
<link rel="alternate" type="application/rss+xml" title="%s" href="feed.xml">
<style>
:root { color-scheme: light dark; --accent: #c8102e; }
body { font: 16px/1.4 system-ui, sans-serif; max-width: 46rem; margin: 0 auto; padding: 1rem; }
h2 { margin-top: 2rem; font-size: 1.1rem; }
table { width: 100%%; border-collapse: collapse; }
td { padding: .35rem .5rem .35rem 0; border-bottom: 1px solid color-mix(in srgb, currentColor 15%%, transparent); }
td:first-child, td:last-child { white-space: nowrap; }
.live, tr.live td { color: var(--accent); font-weight: 600; }
audio { width: 100%%; margin: .25rem 0 .75rem; }
ul { list-style: none; padding: 0; }
</style></head><body>
<h1>🦈 %s</h1>
%s
<h2>Upcoming</h2><table>%s</table>
<h2>Recordings</h2><p><a href="feed.xml">Podcast feed</a></p><ul>%s</ul>
</body></html>""" % (title, title, title, hero, rows or "<tr><td>None</td></tr>", items or "<li>None yet</li>")

def createApp(schedulePath, recordingsDir, icecastURL, clock=lambda: datetime.now(timezone.utc), transport=None):
  app = FastAPI(title="Shark")
  app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
  app.mount("/recordings", StaticFiles(directory=recordingsDir, check_dir=False), name="recordings")

  @app.get("/api/schedule")
  def apiSchedule():
    return schedule(schedulePath, clock())

  @app.get("/api/recordings")
  def apiRecordings():
    return recordings(recordingsDir)

  @app.api_route("/feed.xml", methods=["GET", "HEAD"])
  @app.api_route("/feed", methods=["GET", "HEAD"])
  @app.api_route("/rss", methods=["GET", "HEAD"])
  @app.api_route("/podcast.xml", methods=["GET", "HEAD"])
  def podcastFeed(request: Request):
    return Response(feed.render(feed.episodes(recordingsDir), str(request.base_url)), media_type="application/rss+xml")

  @app.get("/cover.jpg")
  def cover():
    return FileResponse(setting("SHARK_COVER"), media_type="image/jpeg")

  @app.get("/live")
  async def live():
    client = httpx.AsyncClient(timeout=LIVE_TIMEOUT, transport=transport)
    try:
      upstream = await client.send(client.build_request("GET", icecastURL), stream=True)
    except httpx.HTTPError:
      await client.aclose()
      raise HTTPException(503, "Live stream unavailable")
    if upstream.status_code != 200:
      await upstream.aclose()
      await client.aclose()
      raise HTTPException(503, "Nothing on air")

    async def relay():
      try:
        async for chunk in upstream.aiter_raw():
          yield chunk
      finally:
        await upstream.aclose()
        await client.aclose()

    return StreamingResponse(relay(), media_type=upstream.headers.get("content-type", "audio/mpeg"),
                             headers={"Cache-Control": "no-store"})

  @app.get("/", response_class=HTMLResponse)
  def page():
    return renderPage(schedule(schedulePath, clock()), recordings(recordingsDir))

  return app

if __name__ == "__main__":
  import uvicorn
  arguments = docopt(__doc__, version='Shark Web 0.2')
  app = createApp(arguments["--schedule"], arguments["--recordings"], arguments["--icecast"])
  uvicorn.run(app, host=arguments["--host"], port=int(arguments["--port"]), proxy_headers=False)
