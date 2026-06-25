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
import statistics
import sys
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

    # Deduplicate and keep only strictly-increasing cut times. Repeated or
    # regressed timestamps (a known artifact of ffmpeg metadata parsing) would
    # otherwise create zero-length phantom shots and crush the median toward 0.
    times: list[float] = []
    for t in sorted(scene_times):
        if not times or t > times[-1] + 1e-3:
            times.append(t)
    if not times:
        return {
            "shot_count": 0, "cuts_per_minute": 0.0,
            "mean_shot_length": 0.0, "median_shot_length": 0.0, "shots": [],
        }
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
        if motion_scores is not None and i < len(motion_scores):
            shot["motion_score"] = round(float(motion_scores[i]), 3)
        shots.append(shot)

    # Statistics over real shots only — exclude sub-frame slivers (<0.1s) that
    # are parsing noise rather than genuine cuts. Keep them in `shots` for
    # downstream hero-frame selection, but don't let them skew the profile.
    durations = [s["duration_seconds"] for s in shots if s["duration_seconds"] >= 0.1]
    if not durations:
        durations = [s["duration_seconds"] for s in shots]

    return {
        "shot_count": len(shots),
        "cuts_per_minute": round(len(shots) / (video_duration / 60.0), 2),
        "mean_shot_length": round(statistics.mean(durations), 2),
        "median_shot_length": round(statistics.median(durations), 2),
        "shots": shots,
    }


def motion_scores_from_frames(frame_paths: list[str]) -> list[float]:
    """Cheap stub. Real implementation would run ffmpeg signalstats per shot.

    Returning zeros for now — the report works with motion_score=null. Worth
    revisiting only if a downstream feature actually drives off motion scores.
    """
    return [0.0 for _ in frame_paths]


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: pacing.py <duration-seconds> <scene-time-1> [<scene-time-2> ...]",
              file=sys.stderr)
        raise SystemExit(2)
    duration = float(sys.argv[1])
    times = [float(x) for x in sys.argv[2:]]
    print(json.dumps(compute_pacing(times, duration), indent=2))
