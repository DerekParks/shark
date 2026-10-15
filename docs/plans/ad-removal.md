# Ad removal for game recordings

Goal: the podcast feed serves each game with commercial breaks cut out. The
raw recording is kept.

## Why sports radio is a different problem from podcasts

- Ads are produced spots dropped into fixed break slots: between periods,
  quarters and innings, plus TV timeouts. They are not read by the hosts. The
  short in-game sponsor tags ("this power play brought to you by…") are read by
  the play-by-play crew and are arguably part of the game.
- The game side sounds the same all season: the same two or three voices over
  crowd noise.
- **The same spots air again and again**, across breaks, games and teams on the
  same station. Game audio never repeats.

The last two points open up options that podcast ad detection doesn't have.

## Approaches, cheapest signal first

### 1. Repetition (no labels, no ML)

Fingerprint every recording (Chromaprint, or a spectral-peak hash) and find
segments that occur in two or more different games. Repeated material is ads,
promos, station IDs and jingles. Play-by-play doesn't repeat.

- Gets better as the archive grows. A brand-new spot is missed the first time
  it airs and caught once it repeats, and it will repeat.
- Doubles as an **automatic labeller** for approach 2.

### 2. Audio embeddings + a small classifier (your idea)

Embed fixed windows of the raw audio (say 2–5 s, hopped) with a frozen
pretrained audio encoder. Classify each window as ad or game, then smooth over
time, since breaks are long and contiguous (median filter, HMM or CRF).

Encoder candidates:

- **CLAP** (LAION-CLAP or MS-CLAP): audio and text share an embedding space, so
  there's a **zero-shot baseline before any labels exist**. Score each window
  against prompts like "radio commercial with music" vs "live hockey
  play-by-play with crowd noise".
- **PANNs CNN14**: SotS already runs it on the GPU worker for its music/jingle
  timeline (`ml/forward/music_detector.py`). Its AudioSet classes (music,
  speech, crowd, cheering) are direct features, and its 2048-d embedding works
  for a linear probe.
- **BEATs / AST**: stronger general audio encoders if the two above aren't
  enough.

Add one more feature: **speaker identity**. Compare the speaker embedding
(ECAPA or pyannote) of each window with the team's broadcast crew, enrolled
from a few minutes of a recorded game. "Is this one of our announcers" probably
separates game from ad on its own for most windows.

Labels come from approach 1 (repeats are ads) and from hand-marking a few
games (see the labelling view in `web-ui.md`), or by running SotS's STT + LLM
classifier over a handful of games as a teacher. No STT is needed at inference
time.

### 3. STT + LLM (SotS as it is today)

Works without any sports data, but it's the most expensive per game. A 3 h game
is roughly 26 sliding-window LLM calls at SotS's 10 min / 3 min-overlap
windows. Its prompts are podcast-tuned ("HOST-READ ADS ARE ADS", the podcast
sponsor list), and its BiLSTM-CRF was trained on podcasts, so hybrid mode would
need to be bypassed. Best used as the **teacher** for approach 2 rather than as
the production path.

**Recommendation:** collect recordings first. Then build approach 1 plus a CLAP
zero-shot baseline, and score both against two or three hand-labelled games.
Add the embedding classifier only if those two fall short. I don't know how
accurate any of these will be on this audio until there are labelled games to
measure against.

## Getting data

None exists yet. Sources, in order of availability:

1. The NHL `radioLink` HLS streams for Avalanche games
   (`https://d2igy0yla8zi0u.cloudfront.net/COL/<season>/COL-radio.m3u8`). These
   return 403 outside games. Test during the next game (Fri 2026-10-16,
   7:00 PM MDT): `ffmpeg -i <radioLink> -t 60 -c copy probe.aac`.
2. The shark itself, once it's on turnpike (see `shark-runbook.md` in the
   playbooks repo).

About 10 games is enough to start: repetition needs several games, and
evaluation needs a few labelled ones.

## Seams in silence-of-the-spams

Read-only survey of SotS at `8f819fe`; nothing there was changed. Every
pipeline stage is keyed by `episode_id` and SQLite. The pieces that do the work
(`Transcriber.transcribe(path)`, `Classifier.classify_transcript(transcript)`,
`trim._content_blocks`) are already DB-free, so the seams are thin.

| # | Seam | Where | Shape |
|---|------|-------|-------|
| a | Local file in, no DB | new `processors/api.py` | `detect_ads(audio: Path, *, meta, profile, workdir) -> AdReport` that calls `Transcriber.transcribe` directly. Split `music.py:62` `scan_music` into a path-based `compute_music_timeline(path)` with the episode wrapper as a cache, and pass `music_timeline` into `Classifier` instead of loading it by `context["episode_id"]` (`classifier.py:267,321`) |
| b | Domain profile | `sliding_window.py:138` `build_window_prompt`, `classifier.py:256` | A `DomainProfile` holding intro line, ad and content signals, sponsor list, aggressiveness, marker wording, the OpenAI system prompt, and `classification_mode`. A `sports_radio` profile turns off the podcast-trained CRF demotion |
| c | Ad ranges out, nothing published | `models/classification.py:366`, `trim.py:18` | Pure `ad_ranges(ec, min_ad_duration) -> list[(start, end)]`. `run_model_chain` (`chain.py:21`) returns the `EpisodeClassification` instead of writing `<id>_results.json` |
| d | Reusable cutter | `trim.py:249` `trim_episode` | `cut_audio(src, keep, out, *, bitrate=None, beep=True, copy_tags=True)` over the existing path-only helpers. Today it re-encodes at a fixed 128 kbps (4× the size of shark's 32 kbps files) and drops ID3 tags |
| e | Detector contract | `processors/chain_models.py` | Generalise `ChainModel.classify(episode_id)` to `detect(audio, *, transcript=None, music_timeline=None, profile) -> list[Segment]`. Then the repetition and embedding detectors from approaches 1 and 2 plug into the existing AND/OR combiner (`pipeline/model_combiner.py:172`) next to the LLM. That is where approach 2 would live if it goes into SotS rather than shark |

Seam (a) cuts exactly the `pipeline` ↔ `processors` deferred-import cycle that
SotS's import-linter already flags as debt (`classifier.py:274,298`,
`chain_models.py:28,163`). SotS's own `docs/plans/backlog.md` (the HD HomeRun
DVR item) already sketches "a sibling project reusing the ml/ + trim
primitives" for broadcast commercials. That's this.

Shortcut that already exists: the SotS GPU worker on turnpike serves an
OpenAI-compatible `POST /v1/audio/transcriptions` on `:8090`, so shark can get
transcripts today without touching SotS code. Its 600 s per-request timeout
hasn't been tried with 3 h inputs.

## How it plugs into shark

`readCSVRecord.postRecord(filename, game)` is the hook. It should only
**enqueue** the finished recording: a separate unit or worker runs detection
and cutting, so a slow or crashing detector can never delay the next recording.
Outputs are `out/<name>.mp3` (raw, kept) and `out/trimmed/<name>.mp3`. The feed
points at the trimmed file once it exists and at the raw one until then.
