#!/usr/bin/env python3
"""Download a video via yt-dlp, or resolve a local file path.

Also fetches subtitles (manual first, then auto-generated) in VTT format so
transcribe.py can parse them without needing Whisper.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".flv", ".wmv"}

# Fallback chain when we cannot determine the video's native language.
# Kept deliberately short — the real selection is native-language-first (see
# resolve_sub_langs). The model understands any language, so we never need to
# force English; we just need *a* transcript in *some* language.
DEFAULT_SUB_FALLBACK = ["en", "en-US", "en-orig"]


def _probe_metadata(url: str) -> dict:
    """Single --dump-json probe: title, language, and available sub tracks.

    Returns {} on any failure — callers fall back to the default lang chain.
    """
    if shutil.which("yt-dlp") is None:
        return {}
    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--skip-download", "--no-playlist", "--", url],
            capture_output=True, text=True, timeout=90,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {}
        return json.loads(result.stdout.splitlines()[0])
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return {}


def resolve_sub_langs(meta: dict) -> tuple[list[str], str | None]:
    """Decide which subtitle languages to request, native-language-first.

    Order of precedence:
      1. $WATCH_SUB_LANGS env override (comma-separated) — user is in control.
      2. The video's native language (from yt-dlp's `language` field), if it has
         a subtitle or automatic-caption track. The model reads any language;
         the native track is the most faithful source (no MT round-trip).
      3. Any manually-authored subtitle track (creator-provided > auto).
      4. The DEFAULT_SUB_FALLBACK chain (English variants), then "any auto track".

    Returns (sub_langs, detected_native) where sub_langs is ordered by
    preference and detected_native is the chosen native code (or None).
    """
    env = os.environ.get("WATCH_SUB_LANGS", "").strip()
    if env:
        return [s.strip() for s in env.split(",") if s.strip()], None

    # yt-dlp tags placeholder tracks that are never a usable transcript.
    NON_TRANSCRIPT = {"live_chat"}
    manual = set((meta.get("subtitles") or {}).keys()) - NON_TRANSCRIPT
    auto = set((meta.get("automatic_captions") or {}).keys()) - NON_TRANSCRIPT
    available = manual | auto

    native = meta.get("language")  # e.g. "de", "en", "de-DE" (may be None)
    # yt-dlp's `language` is often a regional tag (de-DE) while the actually
    # downloadable caption tracks are the base code + an -orig variant (de,
    # de-orig). Reduce to the base so we match what's really fetchable.
    native_base = native.split("-")[0] if native else None

    ordered: list[str] = []

    def _push(code: str | None) -> None:
        if code and code not in ordered:
            ordered.append(code)

    # 1. Native language first (the faithful source). Prefer tracks that ACTUALLY
    #    exist for this video, matching on the base language code so de-DE also
    #    catches the downloadable `de` / `de-orig` tracks.
    if native_base:
        variants = sorted(
            c for c in available
            if c == native_base or c.startswith(f"{native_base}-")
        )
        # Put the "-orig" (creator's original audio language) track first when
        # present — it's the most faithful auto-caption source.
        variants.sort(key=lambda c: (not c.endswith("-orig"), c))
        for c in variants:
            _push(c)
        # Fall back to requesting the base code even if not pre-listed — auto
        # captions are frequently generatable on demand.
        _push(native_base)
        if native and native != native_base:
            _push(native)  # also try the exact regional tag, last among natives

    # 2. Manually-authored tracks (any language) outrank auto.
    for c in sorted(manual):
        _push(c)

    # 3. English fallback chain (only the variants actually available, plus a
    #    bare "en" as a generatable auto-caption request).
    for c in DEFAULT_SUB_FALLBACK:
        if c == "en" or c in available:
            _push(c)

    if not ordered:
        ordered = list(DEFAULT_SUB_FALLBACK)

    # Cap the request: native + manual + EN is enough. We never want to ask
    # yt-dlp for hundreds of machine-translated auto tracks (slow, rate-limits).
    return ordered[:6], native


def is_url(source: str) -> bool:
    if source.startswith("-"):
        return False
    parsed = urlparse(source)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def resolve_local(path: str) -> dict:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise SystemExit(f"File not found: {p}")
    if p.suffix.lower() not in VIDEO_EXTS:
        print(
            f"[watch] warning: {p.suffix} is not a known video extension, proceeding anyway",
            file=sys.stderr,
        )
    return {
        "video_path": str(p),
        "subtitle_path": None,
        "info": {"title": p.name, "url": str(p)},
        "downloaded": False,
    }


def _pick_subtitle(out_dir: Path, sub_langs: list[str] | None = None) -> Path | None:
    """Pick the best downloaded .vtt, honouring the resolved language order.

    sub_langs is the preference order from resolve_sub_langs; we return the
    first track whose language code matches the earliest preference. This keeps
    the native-language-first intent even when yt-dlp wrote several tracks.
    """
    candidates = sorted(out_dir.glob("video*.vtt"))
    if not candidates:
        return None
    if sub_langs:
        for lang in sub_langs:
            for c in candidates:
                # filenames look like video.de.vtt / video.en-orig.vtt
                if f".{lang}." in c.name:
                    return c
    return candidates[0]


def _pick_video(out_dir: Path) -> Path | None:
    for ext in (".mp4", ".mkv", ".webm", ".mov"):
        for candidate in out_dir.glob(f"video*{ext}"):
            return candidate
    for candidate in out_dir.glob("video.*"):
        if candidate.suffix.lower() in VIDEO_EXTS:
            return candidate
    return None


def download_url(url: str, out_dir: Path) -> dict:
    if shutil.which("yt-dlp") is None:
        raise SystemExit("yt-dlp is not installed. Install with: brew install yt-dlp")

    out_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(out_dir / "video.%(ext)s")

    # Probe once for native language + available subtitle tracks, then request
    # the native track first instead of hardcoding English (the v2 behaviour).
    meta = _probe_metadata(url)
    sub_langs, native = resolve_sub_langs(meta)
    if native:
        print(f"[watch] native language detected: {native}", file=sys.stderr)
    print(f"[watch] requesting subtitle langs: {','.join(sub_langs)}", file=sys.stderr)

    cmd = [
        "yt-dlp",
        "-N", "8",
        "-f", "bv*[height<=720]+ba/b[height<=720]/bv+ba/b",
        "--merge-output-format", "mp4",
        "--write-info-json",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs", ",".join(sub_langs),
        "--sub-format", "vtt",
        "--convert-subs", "vtt",
        "--no-playlist",
        "--ignore-errors",
        "-o", output_template,
        "--",
        url,
    ]

    # yt-dlp may exit non-zero if a subtitle variant fails (e.g. 429) even when
    # the video itself downloaded fine. Treat "video file present" as success.
    result = subprocess.run(cmd, stdout=sys.stderr, stderr=sys.stderr)
    video = _pick_video(out_dir)
    if video is None:
        raise SystemExit(
            f"yt-dlp did not produce a video file in {out_dir} (exit {result.returncode})"
        )

    subtitle = _pick_subtitle(out_dir, sub_langs)
    info_path = out_dir / "video.info.json"
    info: dict = {}
    if info_path.exists():
        try:
            raw = json.loads(info_path.read_text(encoding="utf-8"))
            info = {
                "title": raw.get("title"),
                "uploader": raw.get("uploader") or raw.get("channel"),
                "duration": raw.get("duration"),
                "url": raw.get("webpage_url") or url,
                "language": raw.get("language") or native,
            }
        except Exception as exc:
            print(f"[watch] info.json parse failed: {exc}", file=sys.stderr)
            info = {"url": url}

    if subtitle is not None:
        # Surface which language we actually got, so the caller/report is honest.
        print(f"[watch] subtitle track selected: {subtitle.name}", file=sys.stderr)
    else:
        print("[watch] no subtitle track downloaded (will try Whisper fallback)",
              file=sys.stderr)

    return {
        "video_path": str(video),
        "subtitle_path": str(subtitle) if subtitle else None,
        "info": info or {"url": url},
        "subtitle_lang": _lang_from_name(subtitle) if subtitle else None,
        "native_language": native,
        "downloaded": True,
    }


def _lang_from_name(path: Path | None) -> str | None:
    """Extract the language code from a video.<lang>.vtt filename."""
    if path is None:
        return None
    parts = path.name.split(".")
    # video.de.vtt -> ["video", "de", "vtt"]; video.en-orig.vtt -> [..., "en-orig", ...]
    if len(parts) >= 3:
        return parts[-2]
    return None


def download(source: str, out_dir: Path) -> dict:
    if is_url(source):
        return download_url(source, out_dir)
    return resolve_local(source)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: download.py <url-or-path> <out-dir>", file=sys.stderr)
        raise SystemExit(2)
    result = download(sys.argv[1], Path(sys.argv[2]))
    print(json.dumps(result, indent=2))
