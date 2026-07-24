#!/usr/bin/env python3
"""Write a structured, ingest-shaped report.md to the working directory.

Deterministic sections (frontmatter, pacing numbers, transcript) are filled
by this script. Narrative sections (TL;DR, entities, concepts, etc.) are
emitted as `<!-- pending Claude fill: <hint> -->` markers so Claude (the
orchestrator) knows exactly what to write before offering ingest.

The schema is dictated by what an Obsidian-style Ingest op (see
`$VAULT_DIR/CLAUDE.md` if the user has one) needs to extract:
  - Entities (people, companies, tools) → wiki/entities/*
  - Concepts (frameworks, ideas) → wiki/concepts/*
  - Source page with TL;DR and citations → wiki/sources/*
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path


def _pending(hint: str) -> str:
    return f"<!-- pending Claude fill: {hint} -->"


def _fmt_time(seconds: float) -> str:
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _yaml_list(items: list[str]) -> str:
    if not items:
        return "[]"
    return "[" + ", ".join(items) + "]"


def write_report(
    out_path: Path,
    source: str,
    title: str,
    duration_seconds: float,
    intent: str,
    transcript_segments: list[dict],
    transcript_source: str | None,
    all_frames: list[dict],
    hero_frames: list[dict],
    pacing: dict,
    hook: dict,
    watched_at: _dt.datetime | None = None,
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    watched_at = watched_at or _dt.datetime.now().astimezone()

    hero_names = [Path(f["path"]).name for f in hero_frames]
    lines: list[str] = []

    lines.append("---")
    lines.append(f"source: {source}")
    lines.append(f"title: {title}")
    lines.append(f"duration: {_fmt_time(duration_seconds)}")
    lines.append(f"watched_at: {watched_at.isoformat()}")
    lines.append(f"intent: {intent or '(none)'}")
    lines.append(f"hero_frames: {_yaml_list(hero_names)}")
    lines.append(f"transcript_source: {transcript_source or 'none'}")
    lines.append("---")
    lines.append("")

    lines.append(f"# {title}")
    lines.append("")

    lines.append("## TL;DR")
    lines.append("")
    lines.append(_pending(
        f"3-5 bullets through the lens of: '{intent or 'general summary'}'"
    ))
    lines.append("")

    lines.append("## Key moments")
    lines.append("")
    lines.append(_pending(
        "5-10 bullets in `- **[MM:SS] <label>** — <description>` format. "
        "Cite hero_frames or other frames by filename when useful."
    ))
    lines.append("")

    lines.append("## Hook microscope (0-10s)")
    lines.append("")
    if not hook.get("ran"):
        reason = hook.get("skipped_reason", "n/a")
        lines.append(f"_Skipped: {reason}._")
    else:
        hook_frames = hook.get("frames", [])
        lines.append(f"- Frames: {len(hook_frames)} at 2 fps")
        # Emit the actual frame paths so Claude can Read them. Without this the
        # hook frames were extracted to disk but never surfaced — the section
        # was effectively dead. (Bug fix.)
        if hook_frames:
            lines.append("")
            lines.append("  **Read these hook frames with the Read tool:**")
            for hf in hook_frames:
                ts = hf.get("timestamp_seconds", 0.0)
                lines.append(f"  - `{hf['path']}` (t={ts:.1f}s)")
        words = hook.get("words", [])
        if words:
            lines.append("")
            lines.append(f"- Word-level transcript ({len(words)} words):")
            lines.append("")
            lines.append("```")
            for w in words:
                lines.append(f"  [{w['start']:6.2f}s] {w['word']}")
            lines.append("```")
        lines.append("")
        lines.append(_pending(
            "Frame-by-frame interpretation: what visual change happens at each "
            "0.5s tick, aligned to what's being said. Identify the hook pattern "
            "(question, contrarian claim, in-medias-res, demo-first, etc.)."
        ))
    lines.append("")

    lines.append("## Editorial profile")
    lines.append("")
    if pacing.get("shot_count", 0) > 0:
        lines.append(f"- Shots: {pacing['shot_count']}")
        lines.append(f"- Cuts/min: {pacing['cuts_per_minute']}")
        lines.append(f"- Mean shot length: {pacing['mean_shot_length']}s")
        lines.append(f"- Median shot length: {pacing['median_shot_length']}s")
        lines.append("- Talking-head ratio: n/a (opencv not installed)")
    else:
        lines.append("_No scene-change data — likely a static/screen-recorded source._")
    lines.append("")
    lines.append(_pending(
        "One-line style fingerprint: e.g. 'Tight Fireship-style cuts, B-roll-heavy, "
        "no on-screen text.' Inferred from pacing numbers + hero frames."
    ))
    lines.append("")

    lines.append("## Quotable moments")
    lines.append("")
    lines.append(_pending(
        "Top 3-5 quotable lines pulled from the transcript, each with [MM:SS]. "
        "Prefer punchy, standalone-comprehensible lines."
    ))
    lines.append("")

    lines.append("## Entities mentioned")
    lines.append("")
    lines.append("- People: " + _pending("comma-separated, [[wikilink]]-ready"))
    lines.append("- Companies: " + _pending("comma-separated"))
    lines.append("- Tools / products: " + _pending("comma-separated"))
    lines.append("- Places: " + _pending("comma-separated, or omit if none"))
    lines.append("")

    lines.append("## Concepts surfaced")
    lines.append("")
    lines.append(_pending(
        "List of concept: one-line gist. Frameworks, mental models, named "
        "patterns. These map to wiki/concepts/ pages."
    ))
    lines.append("")

    lines.append("## Transcript")
    lines.append("")
    if transcript_segments:
        lines.append(f"_Source: {transcript_source or 'unknown'}._")
        lines.append("")
        lines.append("```")
        for seg in transcript_segments:
            t = _fmt_time(seg.get("start", 0))
            lines.append(f"[{t}] {seg.get('text', '').strip()}")
        lines.append("```")
    else:
        lines.append("_No transcript available._")
    lines.append("")

    lines.append("## All frames")
    lines.append("")
    lines.append(f"_Total: {len(all_frames)}. Hero frames flagged with star._")
    lines.append("")
    hero_paths = {f["path"] for f in hero_frames}
    for f in all_frames:
        marker = "* " if f["path"] in hero_paths else "  "
        lines.append(f"{marker}`{f['path']}` (t={_fmt_time(f['timestamp_seconds'])})")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: report.py <kwargs.json> [<out.md>]", file=sys.stderr)
        raise SystemExit(2)
    payload = json.loads(Path(sys.argv[1]).read_text())
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("report.md")
    write_report(out_path=out, **payload)
    print(str(out.resolve()))
