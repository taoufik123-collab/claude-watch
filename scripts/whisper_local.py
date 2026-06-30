#!/usr/bin/env python3
"""Local Whisper bridge for /watch — runs faster-whisper instead of an API.

This script is invoked as a subprocess by an interpreter that has
faster-whisper (+ torch / CUDA) installed — which may differ from the skill's
own Python. whisper.py resolves that interpreter via $WATCH_WHISPER_LOCAL_PYTHON
(or the current interpreter if it can import faster_whisper):

    <python-with-faster-whisper> whisper_local.py <audio> [--words]

It transcribes a single audio file and prints JSON to stdout in the exact
shape whisper.py expects, so the local path is a drop-in for the Groq/OpenAI
backend:

    {"segments": [{"start": float, "end": float, "text": str}, ...],
     "words":    [{"word": str, "start": float, "end": float}, ...],   # [] unless --words
     "language": "en", "model": "large-v3", "device": "cuda",
     "backend": "local-faster-whisper"}

All diagnostics go to stderr; stdout is pure JSON so the caller can json.loads it.
Defaults (large-v3 / float16 / beam 1 / VAD on / greedy) favour accuracy; CUDA
is used when available, falling back to CPU/int8. Override with the flags below.
"""
from __future__ import annotations

import argparse
import json
import sys


# Defaults mirror TranscribeWhisper's transcribe.py config block.
DEFAULT_MODEL = "large-v3"
DEFAULT_COMPUTE = "float16"
DEFAULT_BEAM = 1


def _log(msg: str) -> None:
    print(f"[whisper-local] {msg}", file=sys.stderr, flush=True)


def _load_model(model_name: str, compute_type: str, device: str):
    """Build a WhisperModel, falling back from CUDA to CPU/int8 if needed."""
    from faster_whisper import WhisperModel  # imported here so --help works without it

    try:
        _log(f"loading model '{model_name}' on {device} (compute={compute_type})…")
        return WhisperModel(model_name, device=device, compute_type=compute_type), device, compute_type
    except Exception as exc:  # noqa: BLE001 — CUDA/cuDNN errors vary by driver
        if device == "cuda":
            _log(f"CUDA load failed ({type(exc).__name__}: {exc}); falling back to CPU/int8")
            return WhisperModel(model_name, device="cpu", compute_type="int8"), "cpu", "int8"
        raise


def main() -> int:
    ap = argparse.ArgumentParser(prog="whisper_local", description=__doc__)
    ap.add_argument("audio", help="Path to the audio (or video) file to transcribe")
    ap.add_argument("--words", action="store_true", help="Emit word-level timestamps")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--compute-type", default=DEFAULT_COMPUTE)
    ap.add_argument("--beam-size", type=int, default=DEFAULT_BEAM)
    ap.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    ap.add_argument(
        "--language", default=None,
        help="Force a language code (default: auto-detect)",
    )
    ap.add_argument(
        "--translate", action="store_true",
        help="Translate non-English audio to English (task=translate)",
    )
    args = ap.parse_args()

    model, device_used, compute_used = _load_model(args.model, args.compute_type, args.device)
    task = "translate" if args.translate else "transcribe"

    _log(f"transcribing (task={task}, beam={args.beam_size}, words={args.words})…")
    seg_iter, info = model.transcribe(
        args.audio,
        task=task,
        language=args.language,
        beam_size=args.beam_size,
        vad_filter=True,
        word_timestamps=args.words,
        temperature=0.0,
        condition_on_previous_text=False,
    )

    segments: list[dict] = []
    words: list[dict] = []
    for seg in seg_iter:  # generator — iterating is what actually runs inference
        text = (seg.text or "").strip()
        if text:
            segments.append({
                "start": round(float(seg.start or 0.0), 2),
                "end": round(float(seg.end or 0.0), 2),
                "text": text,
            })
        if args.words and getattr(seg, "words", None):
            for w in seg.words:
                wt = (w.word or "").strip()
                if not wt:
                    continue
                words.append({
                    "word": wt,
                    "start": round(float(w.start or 0.0), 3),
                    "end": round(float(w.end or 0.0), 3),
                })

    _log(f"done — {len(segments)} segments, {len(words)} words, lang={info.language}")
    json.dump(
        {
            "segments": segments,
            "words": words,
            "language": info.language,
            "model": args.model,
            "device": device_used,
            "compute_type": compute_used,
            "backend": "local-faster-whisper",
        },
        sys.stdout,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
