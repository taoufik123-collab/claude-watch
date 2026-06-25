#!/usr/bin/env python3
"""Decide whether a video is worth analysing frame-by-frame, or transcript-only.

The motivating finding (see CHANGELOG v3): for a *talking-head* video — one
person, one set, a near-static composition — the 80 extracted frames are
near-duplicates and add almost nothing over the transcript, while still costing
~200 image tokens each. For a *visually dense* video — a screencast, a tutorial,
B-roll with on-screen text/diagrams/code — the frames carry information the
transcript never states, and are worth every token.

Naively, you'd think "more motion = more worth looking at". The data says the
opposite: a screencast's diagram sits *still* for seconds while a talking head's
face and hands move constantly. Motion is not the signal. **Visual information
density is.** So we measure two cheap things with ffmpeg (no numpy/opencv):

  - motion       : mean luma delta between consecutive 1-fps frames (tblend).
  - edge_detail  : edge density via `edgedetect` — high when the frame is full
                   of text / diagrams / UI, low for a person on a soft backdrop.

The discriminator is detail-relative-to-motion:

    info_density = edge_detail_peak / (motion_median + EPS)

High when the frame is rich but stable (slides, code, diagrams) → frames help.
Low when the frame moves a lot but carries little detail (a talking head)
→ the transcript already has the content.

The output is a recommendation, not a hard gate — watch.py uses it to pick a
frame budget and to tell Claude which mode it's in, and the user can override
with --mode.
"""
from __future__ import annotations

import json
import shutil
import statistics
import subprocess
import sys
from pathlib import Path


# --- Tunables (documented so the thresholds aren't magic numbers) -----------

EPS = 0.05  # floor on motion so the ratio can't blow up on a frozen video.

# info_density = edge_peak / (motion_median + EPS), validated on three videos:
#   two talking heads scored ~0.55-0.58; a dense screencast scored ~1.69.
# We place the cut points conservatively wide around that gap.
DENSE_DENSITY_MIN = 1.10   # at/above => frames carry information -> full budget
STATIC_DENSITY_MAX = 0.70  # at/below => talking-head -> transcript-first

# A high cut rate alone is enough to warrant frames (fast B-roll montage), even
# if per-frame detail is modest.
DENSE_CUTS_PER_MIN = 12.0

# Sample at most this many probe frames — keeps the probe cheap on long videos.
PROBE_MOTION_FRAMES = 90
PROBE_EDGE_FRAMES = 40


def _run_signalstats(video_path: str, vf: str, max_frames: int) -> list[float]:
    """Run an ffmpeg filtergraph ending in signalstats+metadata=print, return
    the per-frame YAVG series normalised to 0..1. Empty on any failure."""
    if shutil.which("ffmpeg") is None:
        return []
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "info", "-y",
        "-i", str(Path(video_path).resolve()),
        "-vf", vf,
        "-frames:v", str(max_frames),
        "-an", "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    vals: list[float] = []
    for line in (result.stderr or "").splitlines():
        if "signalstats.YAVG=" in line:
            try:
                vals.append(float(line.split("signalstats.YAVG=", 1)[1].split()[0]) / 255.0)
            except (ValueError, IndexError):
                pass
    return vals


def _probe_motion(video_path: str) -> list[float]:
    """Mean luma delta vs previous frame, 1 fps, tiny frames. 0..1 per frame."""
    vf = ("fps=1.0,scale=64:-2,format=gray,"
          "tblend=all_mode=difference,signalstats=stat=tout,metadata=print")
    diffs = _run_signalstats(video_path, vf, PROBE_MOTION_FRAMES)
    # First tblend output is the frame vs itself (~0); drop a leading zero.
    if diffs and diffs[0] == 0.0:
        diffs = diffs[1:]
    return diffs


def _probe_edges(video_path: str) -> list[float]:
    """Edge density per frame (text/diagram richness), 0.5 fps. 0..1 per frame."""
    vf = ("fps=0.5,scale=320:-2,format=gray,"
          "edgedetect=low=0.1:high=0.3,signalstats=stat=tout,metadata=print")
    return _run_signalstats(video_path, vf, PROBE_EDGE_FRAMES)


def classify(
    video_path: str,
    pacing: dict | None = None,
    duration_seconds: float = 0.0,
) -> dict:
    """Return a recommendation dict for how to analyse this video.

    {
      "mode": "transcript" | "balanced" | "frames",
      "label": human string,
      "info_density": float,       # edge_peak / (motion_median + EPS)
      "motion_median": float,
      "edge_peak": float,
      "cuts_per_minute": float,
      "frame_budget": int,         # suggested max frames for the main pass
      "reason": str,
      "confident": bool,           # False when signals are ambiguous
    }

    mode meanings:
      - "transcript": near-static talking head. Pull the transcript; extract a
        thin set of frames (confirm setting/speaker/any slides) only.
      - "frames": visually dense. Extract the full frame budget — the images
        carry information the transcript doesn't.
      - "balanced": in between; moderate frame budget.
    """
    motion = _probe_motion(video_path)
    edges = _probe_edges(video_path)

    motion_median = round(statistics.median(motion), 4) if motion else 0.0
    edge_peak = round(max(edges), 4) if edges else 0.0
    info_density = round(edge_peak / (motion_median + EPS), 3) if (motion or edges) else 0.0

    cuts_per_min = float((pacing or {}).get("cuts_per_minute", 0.0) or 0.0)

    confident = True
    if info_density >= DENSE_DENSITY_MIN or cuts_per_min >= DENSE_CUTS_PER_MIN:
        mode, budget = "frames", 80
        label = "visually dense (screencast / diagrams / B-roll / on-screen text)"
        reason = (
            f"info-density {info_density:.2f} (edge-peak {edge_peak:.3f} over "
            f"motion-median {motion_median:.3f}), {cuts_per_min:.1f} cuts/min — "
            "frames carry information the transcript won't. Full frame budget."
        )
    elif info_density <= STATIC_DENSITY_MAX and cuts_per_min < DENSE_CUTS_PER_MIN:
        mode, budget = "transcript", 12
        label = "talking-head / near-static composition"
        reason = (
            f"info-density {info_density:.2f} — the frame moves but carries "
            "little visual detail (a person, not slides). Transcript holds the "
            "content; only a thin set of confirmation frames is worth the tokens."
        )
    else:
        mode, budget = "balanced", 40
        label = "mixed pacing / ambiguous"
        confident = False
        reason = (
            f"info-density {info_density:.2f}, {cuts_per_min:.1f} cuts/min — "
            "between talking-head and dense. Middle budget; let the hero frames "
            "settle it."
        )

    # Short videos: never starve. Cost is trivial; the hook matters more.
    if 0 < duration_seconds <= 60 and budget < 24:
        budget = 24

    return {
        "mode": mode,
        "label": label,
        "info_density": info_density,
        "motion_median": motion_median,
        "edge_peak": edge_peak,
        "cuts_per_minute": cuts_per_min,
        "frame_budget": budget,
        "reason": reason,
        "confident": confident,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: classify.py <video-path>", file=sys.stderr)
        raise SystemExit(2)
    out = classify(sys.argv[1])
    print(json.dumps(out, indent=2))
