# /watch

**Give Claude the ability to watch any video.**

> Paste a URL or a local file and Claude *watches* it — **scene-change frame extraction** (one frame per cut instead of every-N-seconds), a **0-10s hook microscope** (dense frames + word-level Whisper on the opening, where every video earns or loses your attention), and **optional Obsidian auto-save** so a watched video becomes a connected wiki entry without copy-paste.

Claude Code:
```
/plugin marketplace add taoufik123-collab/claude-watch
/plugin install watch@claude-watch
```

claude.ai (web): [download `watch.skill`](https://github.com/taoufik123-collab/claude-watch/releases/latest) and drop it into Settings → Capabilities → Skills.

Codex / generic skills:
```bash
git clone https://github.com/taoufik123-collab/claude-watch.git ~/.codex/skills/watch
```

Zero config to start — `yt-dlp` and `ffmpeg` install on first run via `brew` on macOS (Linux/Windows print exact commands). Captions cover most public videos for free. A Whisper backend is only needed when a video has no captions — use a [local faster-whisper](#local-whisper-no-api-key) install (no key) or a Groq/OpenAI key. Set `$WATCH_VAULT_DIR` to point at your Obsidian vault for auto-save, or leave it unset and the skill skips the ingest step quietly.

## What's inside

- **Scene-change frame extraction** — `scripts/frames.py` grabs one frame per detected shot via ffmpeg's `select=gt(scene,...)`, not a uniform tick every N seconds. Token cost stays flat on long videos because the frame count is bounded by the number of cuts, not the duration.
- **0-10s hook microscope** — `scripts/hook.py` runs a denser 2 fps pass on the opening 10 seconds plus a word-level Whisper transcript, so the report tells you what was on screen *as each word landed*. The first 10 seconds is where every video either earns your attention or loses it.
- **Structured `report.md` with Claude-fill markers** — `scripts/report.py` emits a fixed-schema report (TL;DR, key moments, hook breakdown, editorial profile, quotable moments, entities, concepts, transcript) where narrative sections are explicit `<!-- pending Claude fill: ... -->` markers. Claude has a job-list to walk before ingest, not a blank doc.
- **Optional Obsidian auto-save** — Step 4.4 stages the report into `$VAULT_DIR/raw/watched/<slug>/` and opens it via the `obsidian://` URL scheme. Step 4.5 offers ingest into the vault's wiki. Both steps skip cleanly when no vault is detected. Vault path is resolved from `$WATCH_VAULT_DIR` or auto-detected from `~/Second brain/`, `~/Documents/Obsidian/`, `~/Obsidian/`.

The core pipeline — yt-dlp download, ffmpeg frames, Groq/OpenAI Whisper backends, the `--start`/`--end` focused mode, the SessionStart hook, the multi-surface install — comes from the original `claude-video` project and works unchanged (see [Credits](#credits)).

---

Claude can read a webpage, run a script, browse a repo. What it can't do, out of the box, is *watch a video*. You paste a YouTube link and it has to either guess from the title or pull a transcript that's missing 90% of what's on screen.

With Claude Video `/watch` you can paste a URL or a local path, ask a question, and Claude downloads the video, extracts frames at an auto-scaled rate, pulls a timestamped transcript (free captions when available, Whisper API as fallback), and `Read`s every frame as an image. By the time it answers, it has *seen* the video and *heard* the audio.

```
/watch https://youtu.be/dQw4w9WgXcQ what happens at the 30 second mark?
```

## Why this exists

I built this because I'm constantly using video to keep up with content. If I see a YouTube video that's blowing up, I want to know how the creator structured the hook — what's on screen in the first 3 seconds, what they said, why it worked. That used to mean watching it myself with a notepad. Now I just paste the URL and ask.

The other half is summarization. Most YouTube videos don't deserve 20 minutes of my attention. I hand the URL to Claude, it pulls the transcript, and tells me what actually happened. If the visual matters, frames come along too. If it's a podcast or a talking head, transcript is enough.

Claude is great at reading and synthesizing — but until now, video was the one input I couldn't hand it. Pasting a YouTube link got you nothing useful. `/watch` closes that gap.

## What people actually use it for

**Analyze someone else's content.** `/watch https://youtu.be/<viral-video> what hook did they open with?` Claude looks at the first frames, reads the opening transcript, breaks down the structure. Same for ad creative, competitor launches, podcast intros, anything where the *how* matters as much as the *what*.

**Diagnose a bug from a video.** Someone sends you a screen recording of something broken. `/watch bug-repro.mov what's going wrong?` Claude watches the recording, finds the frame where the issue appears, describes what's on screen, often catches the cause without you ever opening the file.

**Summarize a video.** `/watch https://youtu.be/<long-thing> summarize this` does the obvious thing — pulls the structure, the key moments, what was actually said and shown. Faster than watching at 2x.

## How it works

1. **You paste a video and a question.** URL (anything yt-dlp supports — YouTube, Loom, TikTok, X, Instagram, plus a few hundred more) or a local path (`.mp4`, `.mov`, `.mkv`, `.webm`).
2. **`yt-dlp` downloads it.** For URLs, into a temp working directory. For local files, no download — just probed in place.
3. **`ffmpeg` extracts frames at an auto-scaled rate.** The frame budget is duration-aware: ≤30s gets ~30 frames, 30-60s gets ~40, 1-3min gets ~60, 3-10min gets ~80, longer gets 100 sparsely. Hard ceilings: 2 fps, 100 frames. JPEGs at 512px wide by default — bump with `--resolution 1024` if Claude needs to read on-screen text.
4. **The transcript comes from one of two places.** First try: `yt-dlp` pulls native captions (manual or auto-generated) from the source. Free, instant, accurate-ish. Fallback: extract a mono 16 kHz audio clip and ship it to Whisper — Groq's `whisper-large-v3` (preferred — cheaper and faster) or OpenAI's `whisper-1`.
5. **Frames + transcript are handed to Claude.** The script prints frame paths with `t=MM:SS` markers and the transcript with timestamps. Claude `Read`s each frame in parallel — JPEGs render directly as images in its context.
6. **Claude answers grounded in what's actually on screen and in the audio.** Not "based on the description" or "according to the title." It saw the frames. It heard the transcript. It answers the way someone who watched the video would.
7. **Cleanup.** The script prints a working directory at the end. If you're not asking follow-ups, Claude removes it.

## Frame budget — why it matters

Token cost is dominated by frames. Every frame is an image; image tokens add up fast. The script's auto-fps logic exists so you don't blow your context budget on a sparse scan of a 30-minute video that would have been better answered by a focused 30-second window.

| Duration | Default frame budget | What you get |
|----------|---------------------|--------------|
| ≤30 s | ~30 frames | Dense — basically every key moment |
| 30 s - 1 min | ~40 frames | Still dense |
| 1 - 3 min | ~60 frames | Comfortable |
| 3 - 10 min | ~80 frames | Sparse but workable |
| > 10 min | 100 frames | "Sparse scan" warning — re-run focused |

When the user names a moment ("around 2:30", "the last 30 seconds", "from 0:45 to 1:00"), pass `--start` / `--end`. Focused mode gets denser per-second budgets, capped at 2 fps. Far more useful than a sparse pass over the whole thing.

## Install

| Surface | Install |
|---------|---------|
| **Claude Code** | `/plugin marketplace add taoufik123-collab/claude-watch` then `/plugin install watch@claude-watch` |
| **claude.ai** (web) | [Download `watch.skill`](https://github.com/taoufik123-collab/claude-watch/releases/latest) → Settings → Capabilities → Skills → `+` |
| **Codex** | `git clone https://github.com/taoufik123-collab/claude-watch.git ~/.codex/skills/watch` |
| **Manual / dev** | `git clone https://github.com/taoufik123-collab/claude-watch.git ~/.claude/skills/watch` |
| **Configuration** | Optional: `export WATCH_VAULT_DIR=/path/to/your/obsidian/vault` to enable auto-save. Auto-detects `~/Second brain/`, `~/Documents/Obsidian/`, `~/Obsidian/`. |

### Claude Code

```
/plugin marketplace add taoufik123-collab/claude-watch
/plugin install watch@claude-watch
```

Update later with `/plugin update watch@claude-watch`.

### claude.ai (web)

1. [Download `watch.skill`](https://github.com/taoufik123-collab/claude-watch/releases/latest) from the latest release.
2. Go to Settings → Capabilities → Skills.
3. Click `+` and drop the file in.

Enable "Code execution and file creation" under Capabilities first — the skill shells out to `ffmpeg` and `yt-dlp`, so it won't run without it.

### Codex

```bash
git clone https://github.com/taoufik123-collab/claude-watch.git ~/.codex/skills/watch
```

### Manual (developer)

```bash
git clone https://github.com/taoufik123-collab/claude-watch.git ~/.claude/skills/watch
```

## First run

On the first `/watch` call, the skill runs `scripts/setup.py --check`. If `ffmpeg` / `yt-dlp` aren't on your PATH, or no Whisper API key is set, it walks you through fixing it:

- **macOS** — auto-runs `brew install ffmpeg yt-dlp`.
- **Linux** — prints the exact `apt` / `dnf` / `pipx` commands.
- **Windows** — prints the `winget` / `pip` commands.
- **API key** — scaffolds `~/.config/watch/.env` (mode `0600`) with commented placeholders for `GROQ_API_KEY` (preferred) and `OPENAI_API_KEY`.

After setup, preflight is silent and `/watch` just works. The check is a sub-100ms lookup, so it doesn't slow you down on subsequent runs.

## Bring your own keys

Captions cover the majority of public videos for free. The Whisper fallback only kicks in when a video genuinely has no caption track — typically local files, TikToks, some Vimeos, and the occasional caption-less YouTube upload.

| Capability | What you need | Cost |
|------------|---------------|------|
| Download + native captions | `yt-dlp` + `ffmpeg` | Free |
| Whisper fallback (local, no key) | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) + `WATCH_WHISPER_LOCAL=1` | Free, on-machine, private |
| Whisper fallback (preferred) | [Groq API key](https://console.groq.com/keys) — `whisper-large-v3` | Cheap, fast |
| Whisper fallback (alt) | [OpenAI API key](https://platform.openai.com/api-keys) — `whisper-1` | Standard pricing |
| Disable Whisper entirely | `--no-whisper` | Free, frames-only when no captions |

### Local Whisper (no API key)

Prefer to keep audio on your machine, or just don't want to manage an API key? Point the Whisper fallback at a local [faster-whisper](https://github.com/SYSTRAN/faster-whisper) install instead of Groq/OpenAI.

```bash
export WATCH_WHISPER_LOCAL=1
# Optional: an interpreter whose env has faster-whisper (e.g. a GPU venv).
# Omit it and the skill uses its own interpreter if faster-whisper is importable there.
export WATCH_WHISPER_LOCAL_PYTHON="/path/to/python-with-faster-whisper"
```

When `WATCH_WHISPER_LOCAL` is set and a faster-whisper interpreter is resolvable, it becomes the default backend: captions are still tried first, and when a video has none the audio is transcribed locally via `scripts/whisper_local.py` — same `{start, end, text}` (and word-level) output the API backends produce, so frame/transcript alignment and the hook microscope work identically. `setup.py --check` treats this as "ready" (no key needed). Force it explicitly with `--whisper local`, or override per-run with `--whisper groq|openai`.

Defaults mirror a typical accuracy-first config (`large-v3` / `float16` / beam 1 / VAD on), using CUDA when available and falling back to CPU/int8. Note the model loads per invocation, so local transcription adds a few seconds of startup over an API call.

## Usage

```
/watch https://youtu.be/dQw4w9WgXcQ what happens at the 30 second mark?
/watch https://www.tiktok.com/@user/video/123 summarize this
/watch ~/Movies/screen-recording.mp4 when does the UI break?
/watch https://vimeo.com/123 what tools does she mention?
```

Focused on a specific section — denser frame budget, lower token cost:
```
/watch https://youtu.be/abc --start 2:15 --end 2:45
/watch video.mp4 --start 50 --end 60
/watch "$URL" --start 1:12:00            # from 1h12m to end
```

Other knobs (passed to `scripts/watch.py`):

- `--max-frames N` — lower the frame cap for a tighter token budget.
- `--resolution W` — bump frame width to 1024 px when Claude needs to read on-screen text (slides, terminals, code).
- `--fps F` — override the auto-fps calculation (still capped at 2 fps).
- `--whisper groq|openai|local` — force a specific Whisper backend (`local` = on-machine faster-whisper, see [Local Whisper](#local-whisper-no-api-key)).
- `--no-whisper` — disable transcription entirely; frames only.
- `--out-dir DIR` — keep working files somewhere specific (default: auto-generated tmp dir).

## Limits

- **Best accuracy: under 10 minutes.** Past that the script prints a "sparse scan" warning — re-run focused on the part you actually care about with `--start`/`--end`.
- **Hard caps: 2 fps, 100 frames.** Frame count drives token cost; the script enforces this even when the auto-fps math would imply higher.
- **Whisper upload limit: 25 MB.** At mono 16 kHz that's about 50 minutes of audio. Longer videos need either captions or `--start`/`--end` to a smaller window.
- **No private platforms.** This skill doesn't log into anything. Public URLs and local files only. If yt-dlp can't reach it without auth, neither can `/watch`.

## Structure

```
.
├── SKILL.md                 # skill contract — loaded by all three surfaces
├── scripts/
│   ├── watch.py             # entry point — orchestrates download → frames → transcript
│   ├── download.py          # yt-dlp wrapper
│   ├── frames.py            # ffmpeg frame extraction + auto-fps logic
│   ├── transcribe.py        # VTT parsing + dedupe + Whisper orchestration
│   ├── whisper.py           # Groq / OpenAI clients (pure stdlib) + local backend dispatch
│   ├── whisper_local.py     # local faster-whisper bridge (no API key)
│   ├── setup.py             # preflight + installer
│   └── build-skill.sh       # build dist/watch.skill for claude.ai upload
├── hooks/                   # SessionStart status hook (Claude Code only)
├── .claude-plugin/          # plugin.json + marketplace.json (Claude Code)
├── .codex-plugin/           # codex packaging
└── .github/workflows/       # release.yml — auto-builds watch.skill on tag push
```

## Develop

```bash
# Build the claude.ai upload bundle:
bash scripts/build-skill.sh      # → dist/watch.skill
```

Releasing: tag `vX.Y.Z`, push the tag. The workflow builds `dist/watch.skill` and attaches it to the GitHub release.

See [CHANGELOG.md](CHANGELOG.md) for version history.

## Credits

`/watch` is built on **[claude-video](https://github.com/bradautomates/claude-video)** by **[Bradley Bonanno](https://github.com/bradautomates)**. The original `/watch` skill — the yt-dlp download, the ffmpeg pipeline, the Groq/OpenAI Whisper backends, the install flow, and the SessionStart hook — is his work, released under the MIT license. This repo extends it with scene-change frame extraction, the 0-10s hook microscope, the structured `report.md`, and Obsidian auto-save.

Original author and copyright holder: **Bradley Bonanno** (see [LICENSE](LICENSE)). Contributors are listed in [AUTHORS.md](AUTHORS.md).

## Open source

MIT license.

Built on `yt-dlp`, `ffmpeg`, and Claude's multimodal `Read` tool. Whisper transcription via [Groq](https://groq.com) or [OpenAI](https://openai.com).

---

[github.com/taoufik123-collab/claude-watch](https://github.com/taoufik123-collab/claude-watch) · [Credits](#credits) · [LICENSE](LICENSE)
