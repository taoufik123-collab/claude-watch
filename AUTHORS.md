# Authors & credits

## Original project

**Bradley Bonanno** — [bradautomates/claude-video](https://github.com/bradautomates/claude-video)

The original `/watch` skill: yt-dlp download, the ffmpeg frame pipeline, the Groq/OpenAI
Whisper backends, the multi-surface install flow, and the SessionStart hook. Released under
the MIT license, © 2026 Bradley Bonanno.

## This distribution — claude-watch

**Taoufik** — [taoufik123-collab](https://github.com/taoufik123-collab)

Scene-change frame extraction, the 0-10s hook microscope, the structured `report.md`, and
optional Obsidian auto-save, on top of Bradley's pipeline.

## Contributors

**MrBill700** — [MrBill700](https://github.com/MrBill700)

Local Whisper backend (`scripts/whisper_local.py`) — on-machine faster-whisper transcription
with no API key, as a drop-in alternative to the Groq/OpenAI backends.
