"""Unit tests for the auto-classification decision (no ffmpeg needed)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import classify  # noqa: E402


class TestClassify(unittest.TestCase):
    """We stub the ffmpeg probes so the decision logic is tested in isolation."""

    def _classify_with(self, motion, edges, pacing=None, duration=300.0):
        with mock.patch.object(classify, "_probe_motion", return_value=motion), \
             mock.patch.object(classify, "_probe_edges", return_value=edges):
            return classify.classify("dummy.mp4", pacing=pacing,
                                     duration_seconds=duration)

    def test_talking_head_is_transcript(self):
        # Lots of motion (a moving face), little visual detail -> low info-density.
        r = self._classify_with(motion=[0.15] * 30, edges=[0.06] * 20)
        self.assertEqual(r["mode"], "transcript")
        self.assertLessEqual(r["frame_budget"], 12)

    def test_dense_screencast_is_frames(self):
        # Near-static (low motion) but high edge detail (diagrams) -> dense.
        r = self._classify_with(motion=[0.02] * 30, edges=[0.16] * 20)
        self.assertEqual(r["mode"], "frames")
        self.assertEqual(r["frame_budget"], 80)

    def test_high_cut_rate_forces_frames(self):
        # Even with modest detail, a fast montage (many cuts/min) -> frames.
        r = self._classify_with(
            motion=[0.1] * 30, edges=[0.08] * 20,
            pacing={"cuts_per_minute": 20.0},
        )
        self.assertEqual(r["mode"], "frames")

    def test_short_video_budget_floor(self):
        # A short talking head still gets a non-trivial floor (hook matters).
        r = self._classify_with(motion=[0.15] * 30, edges=[0.06] * 20,
                                duration=45.0)
        self.assertGreaterEqual(r["frame_budget"], 24)

    def test_no_probe_data_is_safe(self):
        # ffmpeg returned nothing — must not crash, must not claim "dense".
        r = self._classify_with(motion=[], edges=[])
        self.assertIn(r["mode"], {"transcript", "balanced"})


if __name__ == "__main__":
    unittest.main()
