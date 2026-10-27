#!/usr/bin/env python3
"""Probe video metadata and extract frames at an auto-scaled fps.

Auto-fps targets a frame budget, not a fixed rate. Token cost scales with frame
count, so budget-by-duration keeps short videos dense and long videos capped.
When a user-specified range is passed, focused-mode budgets denser (they are
zooming in for detail).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


MAX_FPS = 2.0


def _clamp_fps(fps: float, duration_seconds: float, max_frames: int) -> tuple[float, int]:
    fps = min(fps, MAX_FPS)
    target = min(max_frames, max(1, int(round(fps * duration_seconds))))
    return fps, target


def parse_time(value: str | float | int | None) -> float | None:
    """Parse SS, MM:SS, or HH:MM:SS (with optional .ms) into seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    parts = s.split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        pass
    raise SystemExit(f"Cannot parse time value: {value!r} (expected SS, MM:SS, or HH:MM:SS)")


def format_time(seconds: float) -> str:
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, sec = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def get_metadata(video_path: str) -> dict:
    if shutil.which("ffprobe") is None:
        raise SystemExit("ffprobe is not installed. Install with: brew install ffmpeg")

    result = subprocess.run(
        [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(Path(video_path).resolve()),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"ffprobe failed: {result.stderr.strip()}")

    data = json.loads(result.stdout or "{}")
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = float(fmt.get("duration") or video_stream.get("duration") or 0)
    return {
        "duration_seconds": duration,
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "codec": video_stream.get("codec_name"),
        "size_bytes": int(fmt.get("size") or 0),
        "has_audio": audio_stream is not None,
    }


def auto_fps(duration_seconds: float, max_frames: int = 100) -> tuple[float, int]:
    """Pick fps that targets a sensible frame budget for full-video scans."""
    if duration_seconds <= 0:
        return 1.0, 1

    if duration_seconds <= 30:
        target = min(max_frames, max(12, int(round(duration_seconds))))
    elif duration_seconds <= 60:
        target = min(max_frames, 40)
    elif duration_seconds <= 180:  # 3 min
        target = min(max_frames, 60)
    elif duration_seconds <= 600:  # 10 min
        target = min(max_frames, 80)
    else:
        target = max_frames

    return _clamp_fps(target / duration_seconds, duration_seconds, max_frames)


def auto_fps_focus(duration_seconds: float, max_frames: int = 100) -> tuple[float, int]:
    """Denser budget for user-specified ranges — they are zooming in for detail."""
    if duration_seconds <= 0:
        return min(MAX_FPS, 2.0), 2

    if duration_seconds <= 5:
        target = min(max_frames, max(10, int(round(duration_seconds * 6))))
    elif duration_seconds <= 15:
        target = min(max_frames, max(30, int(round(duration_seconds * 4))))
    elif duration_seconds <= 30:
        target = min(max_frames, 60)
    elif duration_seconds <= 60:
        target = min(max_frames, 80)
    elif duration_seconds <= 180:
        target = max_frames
    else:
        target = max_frames

    return _clamp_fps(target / duration_seconds, duration_seconds, max_frames)


def extract(
    video_path: str,
    out_dir: Path,
    fps: float,
    resolution: int = 512,
    max_frames: int = 100,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
) -> list[dict]:
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg is not installed. Install with: brew install ffmpeg")

    out_dir.mkdir(parents=True, exist_ok=True)
    for existing in out_dir.glob("frame_*.jpg"):
        existing.unlink()

    output_pattern = str(out_dir / "frame_%04d.jpg")
    cmd: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
    ]

    # -ss before -i = fast seek (keyframe-snap, good enough for preview frames).
    if start_seconds is not None:
        cmd += ["-ss", f"{start_seconds:.3f}"]
    if end_seconds is not None:
        cmd += ["-to", f"{end_seconds:.3f}"]

    cmd += [
        "-i", str(Path(video_path).resolve()),
        "-vf", f"fps={fps},scale={resolution}:-2",
        "-frames:v", str(max_frames),
        "-q:v", "4",
        output_pattern,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"ffmpeg frame extraction failed: {result.stderr.strip()}")

    offset = start_seconds or 0.0
    frames = sorted(out_dir.glob("frame_*.jpg"))
    return [
        {
            "index": i,
            "timestamp_seconds": round(offset + (i / fps if fps > 0 else 0.0), 2),
            "path": str(p),
        }
        for i, p in enumerate(frames)
    ]


def extract_scene_change(
    video_path: str,
    out_dir: Path,
    scene_threshold: float = 0.3,
    resolution: int = 512,
    max_frames: int = 100,
    uniform_fallback_min: int = 10,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
) -> list[dict]:
    """One frame per detected shot. Falls back to uniform sampling when too few scenes.

    Uses ffmpeg's `select='gt(scene,T)'` filter — scene change scores in [0,1],
    higher = more visual difference between frames. 0.3 is a permissive cut
    detector that catches hard cuts and most dissolves without firing on motion.

    Always emits the first frame of the range (scene filter only fires on
    *changes*, so without this you'd miss the opening shot).

    On `uniform_fallback_min`: static or near-static videos (screen recordings,
    long talking heads) yield very few scene changes. Fall back to uniform
    sampling — sparse frames > almost no frames.
    """
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg is not installed. Install with: brew install ffmpeg")

    out_dir.mkdir(parents=True, exist_ok=True)
    for existing in out_dir.glob("frame_*.jpg"):
        existing.unlink()

    # Build a select expression that emits frame 0 + every scene-change frame.
    select_expr = f"eq(n\\,0)+gt(scene\\,{scene_threshold})"
    vf = f"select='{select_expr}',metadata=mode=print:file=-,scale={resolution}:-2"

    output_pattern = str(out_dir / "frame_%04d.jpg")
    cmd: list[str] = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
    ]
    if start_seconds is not None:
        cmd += ["-ss", f"{start_seconds:.3f}"]
    if end_seconds is not None:
        cmd += ["-to", f"{end_seconds:.3f}"]
    cmd += [
        "-i", str(Path(video_path).resolve()),
        "-vf", vf,
        "-fps_mode", "vfr",
        "-frames:v", str(max_frames),
        "-q:v", "4",
        output_pattern,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"ffmpeg scene-change extraction failed: {result.stderr.strip()}")

    # Parse pts_time lines from stdout/stderr (ffmpeg version variance).
    pts_times: list[float] = []
    for stream in (result.stdout, result.stderr):
        for line in stream.splitlines():
            line = line.strip()
            if "pts_time" in line:
                for tok in line.split():
                    if tok.startswith("pts_time:"):
                        try:
                            pts_times.append(float(tok.split(":", 1)[1]))
                        except ValueError:
                            pass
                    elif tok.startswith("pts_time="):
                        try:
                            pts_times.append(float(tok.split("=", 1)[1]))
                        except ValueError:
                            pass

    frames = sorted(out_dir.glob("frame_*.jpg"))

    # Fallback: too few scene frames means this video is static-ish.
    if len(frames) < uniform_fallback_min:
        for f in frames:
            f.unlink()
        meta = get_metadata(video_path)
        full_duration = meta["duration_seconds"]
        eff_start = start_seconds if start_seconds is not None else 0.0
        eff_end = end_seconds if end_seconds is not None else full_duration
        eff_duration = max(0.1, eff_end - eff_start)
        fps, _ = auto_fps(eff_duration, max_frames=max_frames)
        return extract(
            video_path, out_dir,
            fps=fps, resolution=resolution, max_frames=max_frames,
            start_seconds=start_seconds, end_seconds=end_seconds,
        )

    offset = start_seconds or 0.0
    if len(pts_times) < len(frames):
        pts_times += [0.0] * (len(frames) - len(pts_times))

    return [
        {
            "index": i,
            "timestamp_seconds": round(offset + pts_times[i], 2),
            "path": str(p),
            "source": "scene-change",
        }
        for i, p in enumerate(frames)
    ]


def select_hero_frames(
    frames: list[dict],
    pacing: dict | None = None,
    hook_end_seconds: float = 10.0,
    max_hero: int = 5,
    min_hero: int = 3,
) -> list[dict]:
    """Pick 3-5 'hero' frames for embedding in the wiki source page.

    Heuristic, deterministic:
      1. First frame after a scene-change at or before `hook_end_seconds`.
      2. First frame of the highest-motion shot from pacing.shots.
      3. First frame of the longest sustained shot.
      4. Plus 1-2 evenly-spaced extras to round out to max_hero.

    Falls back to uniform picks from `frames` if pacing data is unavailable
    or any heuristic yields no candidate.
    """
    if not frames:
        return []

    chosen_indices: list[int] = []

    def _add(idx: int) -> None:
        if 0 <= idx < len(frames) and idx not in chosen_indices:
            chosen_indices.append(idx)

    for i, f in enumerate(frames):
        if f["timestamp_seconds"] <= hook_end_seconds:
            _add(i)
            break

    if pacing and pacing.get("shots"):
        shots = pacing["shots"]
        if shots:
            top_motion = max(shots, key=lambda s: s.get("motion_score", 0) or 0)
            longest = max(shots, key=lambda s: s.get("duration_seconds", 0))
            for shot in (top_motion, longest):
                start_t = shot.get("start_seconds", 0)
                for i, f in enumerate(frames):
                    if f["timestamp_seconds"] >= start_t:
                        _add(i)
                        break

    if len(chosen_indices) < min_hero:
        gap = max(1, len(frames) // max_hero)
        for i in range(0, len(frames), gap):
            _add(i)
            if len(chosen_indices) >= max_hero:
                break

    chosen_indices = sorted(set(chosen_indices))[:max_hero]
    return [frames[i] for i in chosen_indices]


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "usage: frames.py <video-path> <out-dir> [--fps F] [--resolution W] "
            "[--max-frames N] [--start T] [--end T]",
            file=sys.stderr,
        )
        raise SystemExit(2)

    video = sys.argv[1]
    out = Path(sys.argv[2])
    args = sys.argv[3:]

    fps_override = None
    resolution = 512
    max_frames = 100
    start_arg = None
    end_arg = None
    i = 0
    while i < len(args):
        if args[i] == "--fps":
            fps_override = float(args[i + 1]); i += 2
        elif args[i] == "--resolution":
            resolution = int(args[i + 1]); i += 2
        elif args[i] == "--max-frames":
            max_frames = int(args[i + 1]); i += 2
        elif args[i] == "--start":
            start_arg = args[i + 1]; i += 2
        elif args[i] == "--end":
            end_arg = args[i + 1]; i += 2
        else:
            i += 1

    meta = get_metadata(video)
    start_sec = parse_time(start_arg)
    end_sec = parse_time(end_arg)
    full_duration = meta["duration_seconds"]

    effective_start = start_sec if start_sec is not None else 0.0
    effective_end = end_sec if end_sec is not None else full_duration
    effective_duration = max(0.0, effective_end - effective_start)

    focused = start_sec is not None or end_sec is not None
    if focused:
        fps, target = auto_fps_focus(effective_duration, max_frames=max_frames)
    else:
        fps, target = auto_fps(effective_duration, max_frames=max_frames)
    if fps_override is not None:
        fps = fps_override
        target = max(1, int(round(fps * effective_duration)))

    frames = extract(
        video, out,
        fps=fps,
        resolution=resolution,
        max_frames=max_frames,
        start_seconds=start_sec,
        end_seconds=end_sec,
    )
    print(json.dumps(
        {"meta": meta, "fps": fps, "target": target, "focused": focused, "frames": frames},
        indent=2,
    ))
