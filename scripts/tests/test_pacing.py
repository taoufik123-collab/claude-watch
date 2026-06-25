"""Unit tests for pacing math."""
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

from pacing import compute_pacing, _score_shots_from_timeline  # noqa: E402


class TestPacing(unittest.TestCase):

    def test_basic_metrics(self):
        scene_times = [0.0, 5.0, 13.0, 25.0, 35.0, 50.0]
        result = compute_pacing(
            scene_times=scene_times,
            video_duration=60.0,
            motion_scores=None,
        )
        self.assertEqual(result["shot_count"], 6)
        self.assertAlmostEqual(result["cuts_per_minute"], 6.0, places=1)
        self.assertAlmostEqual(result["mean_shot_length"], 10.0, places=1)
        self.assertEqual(len(result["shots"]), 6)
        self.assertAlmostEqual(result["shots"][0]["start_seconds"], 0.0)
        self.assertAlmostEqual(result["shots"][0]["duration_seconds"], 5.0)
        self.assertAlmostEqual(result["shots"][-1]["start_seconds"], 50.0)
        self.assertAlmostEqual(result["shots"][-1]["duration_seconds"], 10.0)

    def test_handles_single_shot(self):
        result = compute_pacing(
            scene_times=[0.0],
            video_duration=120.0,
            motion_scores=None,
        )
        self.assertEqual(result["shot_count"], 1)
        self.assertAlmostEqual(result["cuts_per_minute"], 0.5, places=1)
        self.assertAlmostEqual(result["mean_shot_length"], 120.0)

    def test_handles_empty_input(self):
        result = compute_pacing(scene_times=[], video_duration=60.0, motion_scores=None)
        self.assertEqual(result["shot_count"], 0)
        self.assertEqual(result["cuts_per_minute"], 0.0)
        self.assertEqual(result["mean_shot_length"], 0.0)
        self.assertEqual(result["shots"], [])

    def test_motion_scores_attached(self):
        result = compute_pacing(
            scene_times=[0.0, 10.0, 20.0],
            video_duration=30.0,
            motion_scores=[0.1, 0.5, 0.9],
        )
        scores = [s["motion_score"] for s in result["shots"]]
        self.assertEqual(scores, [0.1, 0.5, 0.9])

    def test_motion_scores_tolerates_none_entries(self):
        # A null motion signal must not crash attachment.
        result = compute_pacing(
            scene_times=[0.0, 10.0, 20.0],
            video_duration=30.0,
            motion_scores=[None, None, None],
        )
        scores = [s["motion_score"] for s in result["shots"]]
        self.assertEqual(scores, [None, None, None])


class TestMotionScoring(unittest.TestCase):

    def _shots(self, *spans):
        return [{"start_seconds": s, "duration_seconds": d} for s, d in spans]

    def test_normalises_to_busiest_shot(self):
        shots = self._shots((0.0, 2.0), (2.0, 2.0))
        timeline = [(0.5, 10.0), (1.5, 10.0), (2.5, 40.0), (3.5, 40.0)]
        scores = _score_shots_from_timeline(shots, timeline)
        self.assertEqual(scores, [0.25, 1.0])

    def test_empty_timeline_is_all_none(self):
        shots = self._shots((0.0, 2.0), (2.0, 2.0))
        self.assertEqual(_score_shots_from_timeline(shots, []), [None, None])

    def test_short_shot_uses_nearest_sample(self):
        # Shot shorter than the sample interval has no sample inside it.
        shots = self._shots((1.0, 0.05))
        timeline = [(0.0, 5.0), (1.5, 20.0)]
        # nearest sample to the shot midpoint (1.025s) is t=1.5 → peak → 1.0
        self.assertEqual(_score_shots_from_timeline(shots, timeline), [1.0])

    def test_all_zero_motion_stays_zero(self):
        shots = self._shots((0.0, 2.0), (2.0, 2.0))
        timeline = [(0.5, 0.0), (2.5, 0.0)]
        self.assertEqual(_score_shots_from_timeline(shots, timeline), [0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
