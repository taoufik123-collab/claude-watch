# Changelog

All notable changes to `/watch` are documented here.

## [0.3.0] — 2026-06-25

A reliability + cost pass driven by a head-to-head review of `/watch` against a
plain transcript-only approach on three real videos (two German talking heads,
one English screencast). The review surfaced four concrete issues; all are
fixed here. **No new dependencies** — still pure ffmpeg + yt-dlp + stdlib.

### Fixed
- **Non-English videos got no transcript.** `download.py` hardcoded
  `--sub-langs en,en-US,en-GB,en-orig`, so a German (or any non-English) video
  fell through to "no captions" even though YouTube had native auto-captions.
  It now probes the video's native language (`yt-dlp --dump-json`) and requests
  the native track first, reducing the regional tag (`de-DE`) to the actually
  downloadable base/`-orig` tracks (`de`, `de-orig`), with English as fallback.
  Override with `$WATCH_SUB_LANGS`. The model reads any language and answers in
  the user's — no machine translation in the pipeline.
- **Fast-cut intros starved the rest of the video.** Scene extraction capped
  with `-frames:v max_frames` in a single pass, so a montage intro with 100+
  cuts in the first 20s consumed the whole budget and the remaining minutes
  were never sampled. Now two-pass: detect *all* cuts, then sample for even
  coverage *in time* (bucketed), snapping each pick to a real scene boundary.
- **Pacing median collapsed to ~0.04s.** Timestamp parsing (`metadata=print`)
  mis-aligned with written frames and padded gaps with `0.0`, creating phantom
  zero-length shots. Switched to `showinfo` parsing, plus `compute_pacing` now
  dedups non-increasing timestamps and excludes sub-frame slivers from the
  mean/median.
- **Hook-microscope frames were extracted but never surfaced.** The 0-10s
  frames were written to disk but never listed in `report.md` or the stdout
  stream, so they couldn't be Read. They're now emitted in both.

### Added
- **Auto-classification (`scripts/classify.py`).** Decides whether a video is
  worth a full frame pass or is better served transcript-first. The signal is
  *visual information density*, not motion: `edge_peak / (motion_median + ε)` —
  high for slides/diagrams/UI/code (frames carry info the transcript doesn't),
  low for a talking head (the transcript already has the content). A
  talking-head video drops to a thin confirmation set (~12 frames), saving
  ~14k image tokens per video; a dense screencast keeps the full budget.
- **`--mode auto|transcript|balanced|frames`** in `watch.py` (default `auto`).
  The chosen mode and a one-line rationale are printed to the report so the
  reader knows whether to lean on the frames or the transcript.
- 16 new unit tests (`test_classify.py`, `test_subtitle_langs.py`,
  `test_sampling.py`) covering classification, native-language resolution,
  even-coverage sampling, and pacing robustness. 23 tests total, all stdlib.

## [0.2.0] — 2026-05-25

Based on [bradautomates/claude-video](https://github.com/bradautomates/claude-video) v0.1.3 by Bradley Bonanno (MIT). Its pipeline (yt-dlp + ffmpeg + Whisper) is preserved; everything below is additive.

### Added
- Scene-change frame extraction in `scripts/frames.py` — `extract_scene_change()` + `select_hero_frames()` using ffmpeg's `select=gt(scene,...)` filter. One frame per detected shot instead of uniform every-N-seconds sampling. Keeps token cost flat on long videos. Uniform sampling still available as a fallback for static/screen-recorded sources.
- 0-10s hook microscope in `scripts/hook.py` — 2 fps frames + word-level Whisper transcript on the opening 10 seconds, so the report can tell you what's on screen *as each word lands*.
- Editorial pacing metrics in `scripts/pacing.py` — shot count, cuts/min, mean + median shot length.
- Structured `report.md` emitter in `scripts/report.py` — fixed-schema ingest-ready report with `<!-- pending Claude fill: ... -->` markers for narrative sections (TL;DR, key moments, hook breakdown, editorial profile, quotable moments, entities, concepts).
- Word-level timestamps in `scripts/whisper.py` (Groq + OpenAI backends extended).
- New CLI flags in `scripts/watch.py`: `--intent`, `--no-scene-change`, `--no-hook-microscope`.
- Step 4.4 (stage to Obsidian vault) + Step 4.5 (ingest gate) in `SKILL.md` — optional auto-save to your Obsidian vault. Path resolved via `$WATCH_VAULT_DIR` or auto-detected from `~/Second brain/`, `~/Documents/Obsidian/`, `~/Obsidian/`. Skips cleanly when no vault is detected.
- 7 unit tests under `scripts/tests/` (stdlib `unittest`, no pytest dependency).

### Changed
- `SKILL.md` is now a v2 contract — describes the structured report, the marker-fill step, and the vault config. Backwards-compatible with /watch invocations that don't care about ingest.
- README documents the added features and the `$WATCH_VAULT_DIR` configuration.

## [0.1.3] — 2026-05-09

### Fixed
- Windows: `video.info.json` is read as UTF-8 (#4). Previously `Path.read_text()` defaulted to cp1252 on Windows and crashed on yt-dlp's UTF-8 output, silently dropping Title/Uploader from the report. Same fix applied to `.env` reads/writes in `whisper.py` and `setup.py`.
- `download.py` now logs info.json parse failures to stderr instead of swallowing them.

### Security
- Hardened subprocess argv against option injection (#2): inserted `--` before the URL in the yt-dlp argv, and tightened `is_url` to reject `-`-prefixed sources and require a non-empty netloc. Resolved video/audio paths to absolute via `Path.resolve()` before passing to `ffmpeg`/`ffprobe`, so a relative path starting with `-` can't be misinterpreted as a flag.

## [0.1.2] — 2026-04-24

### Fixed
- Windows console crash: removed the emoji from the long-video warning in `watch.py`; cp1252 consoles couldn't encode it.
- `setup.py` now prints `winget` / `pip` install commands on Windows instead of "unsupported platform" — matches what the README already promised.

### Changed
- `SKILL.md` notes that on Windows the scripts must be invoked with `python`, not `python3` (the latter is the Microsoft Store stub on Windows).

## [0.1.1] — 2026-04-24

### Fixed
- Added `commands/watch.md` shim so `/watch` is callable when installed as a Claude Code plugin. Without it, the plugin loaded but the skill wasn't exposed as a slash command.
- `scripts/build-skill.sh` now strips `commands/` from the claude.ai `.skill` bundle alongside `hooks/` and `.claude-plugin/`.

## [0.1.0] — 2026-04-24

Initial marketplace release.

### Added
- `/watch <url-or-path> [question]` slash command.
- yt-dlp download with native caption extraction (manual + auto-subs).
- ffmpeg frame extraction with auto-scaled fps (≤2 fps, ≤100 frames, duration-aware budget).
- `--start` / `--end` focused mode with denser frame budget and transcript range filtering.
- Whisper fallback (Groq preferred, OpenAI secondary) for videos without captions.
- `setup.py` preflight: silent `--check`, structured `--json`, and installer that auto-runs `brew install` on macOS.
- Session-start hook that prints a one-line status on first run / partial config.
- `.skill` bundle packaging for claude.ai upload via `scripts/build-skill.sh`.
