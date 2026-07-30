#!/usr/bin/env python3
"""Editorial pacing metrics: cuts/min, shot length distribution, motion.

Consumes scene-change timestamps (from frames.extract_scene_change) and an
optional list of per-shot motion scores. Produces a JSON blob the reporter
embeds in the editorial profile section.

Talking-head detection is intentionally out-of-scope here — it requires
opencv-python which is not in the skill's preflight. Leaving the field
nullable in the report; can be filled in later if/when opencv is added.
"""
from __future__ import annotations

import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path


def compute_pacing(
    scene_times: list[float],
    video_duration: float,
    motion_scores: list[float] | None = None,
) -> dict:
    """Build shot-by-shot pacing report.

    Args:
        scene_times: sorted list of shot-start timestamps (seconds). If the
            first entry is not ~0, treat 0 as the implicit shot 0 start.
        video_duration: total duration of the analysed range (seconds).
        motion_scores: per-shot motion score in [0,1]; len must match shot count.

    Returns:
        {
          "shot_count": int,
          "cuts_per_minute": float,
          "mean_shot_length": float,
          "median_shot_length": float,
          "shots": [
            {"start_seconds": float, "duration_seconds": float,
             "motion_score": float|null},
            ...
          ],
        }
    """
    if not scene_times or video_duration <= 0:
        return {
            "shot_count": 0,
            "cuts_per_minute": 0.0,
            "mean_shot_length": 0.0,
            "median_shot_length": 0.0,
            "shots": [],
        }

    times = sorted(scene_times)
    if times[0] > 0.01:
        times = [0.0] + times

    shots: list[dict] = []
    for i, start in enumerate(times):
        end = times[i + 1] if i + 1 < len(times) else video_duration
        duration = max(0.0, end - start)
        shot = {
            "start_seconds": round(start, 2),
            "duration_seconds": round(duration, 2),
            "motion_score": None,
        }
        if (
            motion_scores is not None
            and i < len(motion_scores)
            and motion_scores[i] is not None
        ):
            shot["motion_score"] = round(float(motion_scores[i]), 3)
        shots.append(shot)

    durations = [s["duration_seconds"] for s in shots]
    return {
        "shot_count": len(shots),
        "cuts_per_minute": round(len(shots) / (video_duration / 60.0), 2),
        "mean_shot_length": round(statistics.mean(durations), 2),
        "median_shot_length": round(statistics.median(durations), 2),
        "shots": shots,
    }


def _ydif_timeline(video_path: str, sample_fps: float = 4.0) -> list[tuple[float, float]]:
    """Sample whole-video motion as [(pts_time, YDIF), ...].

    Runs one ffmpeg pass with `signalstats`, whose YDIF metric is the mean
    absolute luma delta between consecutive frames — a cheap, dependency-free
    motion proxy. Frames are decimated to `sample_fps` first to keep it fast on
    long videos. Metadata goes to a temp file (not stdout) so it doesn't collide
    with the `-f null -` muxer. Returns [] if ffmpeg is missing or the run fails,
    so callers can fall back to a null motion signal.
    """
    if shutil.which("ffmpeg") is None:
        return []

    handle = tempfile.NamedTemporaryFile(
        mode="r", suffix=".txt", delete=False, encoding="utf-8"
    )
    handle.close()
    try:
        vf = f"fps={sample_fps},signalstats,metadata=mode=print:file={handle.name}"
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(Path(video_path).resolve()),
            "-vf", vf, "-an", "-f", "null", "-",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return []
        with open(handle.name, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass

    samples: list[tuple[float, float]] = []
    cur_t: float | None = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("frame:"):
            cur_t = None
            for tok in line.split():
                if tok.startswith("pts_time:"):
                    try:
                        cur_t = float(tok.split(":", 1)[1])
                    except ValueError:
                        cur_t = None
        elif "signalstats.YDIF" in line and cur_t is not None:
            try:
                samples.append((cur_t, float(line.split("=", 1)[1])))
            except (ValueError, IndexError):
                pass
    return samples


def _score_shots_from_timeline(
    shots: list[dict],
    timeline: list[tuple[float, float]],
) -> list[float | None]:
    """Average the YDIF timeline within each shot, normalised so the busiest
    shot scores 1.0. Pure function — no ffmpeg — so it is unit-testable.

    Returns all-None when the timeline is empty (motion signal unavailable),
    keeping motion_score nullable downstream.
    """
    if not shots:
        return []
    if not timeline:
        return [None] * len(shots)

    raw: list[float] = []
    for s in shots:
        start = s["start_seconds"]
        end = start + s["duration_seconds"]
        vals = [y for (t, y) in timeline if start <= t < end]
        if vals:
            raw.append(statistics.mean(vals))
        else:
            # Shot shorter than the sample interval — use the nearest sample.
            mid = (start + end) / 2.0
            raw.append(min(timeline, key=lambda ts: abs(ts[0] - mid))[1])

    peak = max(raw) if raw else 0.0
    if peak <= 0:
        return [0.0] * len(shots)
    return [round(r / peak, 3) for r in raw]


def motion_scores_for_shots(
    video_path: str,
    shots: list[dict],
    sample_fps: float = 4.0,
) -> list[float | None]:
    """Per-shot motion score in [0,1], normalised so the busiest shot = 1.0.

    Drives hero-frame selection (frames.select_hero_frames picks the
    highest-motion shot). Returns a list aligned with `shots`, or all-None if
    the motion signal can't be computed.
    """
    if not shots:
        return []
    return _score_shots_from_timeline(shots, _ydif_timeline(video_path, sample_fps))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: pacing.py <duration-seconds> <scene-time-1> [<scene-time-2> ...]",
              file=sys.stderr)
        raise SystemExit(2)
    duration = float(sys.argv[1])
    times = [float(x) for x in sys.argv[2:]]
    print(json.dumps(compute_pacing(times, duration), indent=2))
