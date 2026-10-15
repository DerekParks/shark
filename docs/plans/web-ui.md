# Web UI

A tailnet-only page on turnpike for checking on the shark and listening, from a
phone or laptop.

## v0 — read-only (built)

`web.py`, FastAPI, one server-rendered page plus JSON:

- **On air / next up**: the game whose window contains now, or the next one,
  with a live `<audio>` player pointed at the Icecast mount.
- **Upcoming**: the next games from `merged.csv`, by priority-merged start
  time.
- **Recordings**: newest first, each with an inline player, served from `out/`.
- `GET /api/schedule`, `GET /api/recordings` for scripts.

Runs as the `web` service of the compose stack on `:8771`; tsdproxy publishes it
as `sharksports`. It also serves the podcast feed (`/feed.xml`) and relays the
Icecast mount at `/live`, with every URL built from the requesting host, so the
LAN and tailnet addresses both work.

## Next, roughly in order

1. **Skipped games**: `buildSchedule.py` also writes the conflicts it dropped
   ("Nuggets at Bulls — overlaps Broncos vs. Raiders"), so the page shows
   what *won't* be recorded and why.
2. **Overrides**: skip a scheduled game or force one in, stored in
   `overrides.toml` and applied by `buildSchedule.py`. That covers the
   occasional case where you'd rather hear the lower-priority game.
3. **Recorder status**: `readCSVRecord.py` writes `state.json` (idle /
   recording, current game, bytes written, stream up or down), so "on air"
   reflects reality rather than the schedule.
4. **Ad labelling**: waveform view of a recording where you drag to mark
   breaks. It saves `(file, start, end, label)` rows, the evaluation and
   training data for `ad-removal.md`, and later shows the detector's cuts for
   review before they're applied.
