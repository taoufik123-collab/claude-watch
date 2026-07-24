"""Unit tests for even time-coverage sampling and pacing robustness."""
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

from frames import _evenly_sample  # noqa: E402
from pacing import compute_pacing  # noqa: E402


class TestEvenlySample(unittest.TestCase):

    def test_fast_intro_does_not_starve_rest(self):
        # 100 cuts crammed into the first 20s, then sparse cuts to t=800s.
        # The v2 bug took the first N cuts and never reached the body of the
        # video. The fix must spread coverage across the whole timeline.
        intro = [i * 0.2 for i in range(100)]        # 0..19.8s
        body = [50.0, 120.0, 300.0, 500.0, 700.0, 800.0]
        cuts = sorted(intro + body)

        picked = _evenly_sample(cuts, 20)
        self.assertLessEqual(len(picked), 20)
        # Coverage: at least one sample in the back half of the video.
        self.assertTrue(any(t > 400 for t in picked),
                        "sampling never reached the second half of the video")
        # First and last cuts retained.
        self.assertEqual(min(picked), cuts[0])
        self.assertEqual(max(picked), cuts[-1])

    def test_returns_all_when_fewer_than_budget(self):
        cuts = [0.0, 10.0, 20.0]
        self.assertEqual(_evenly_sample(cuts, 10), cuts)

    def test_single_budget(self):
        self.assertEqual(_evenly_sample([5.0, 6.0, 7.0], 1), [5.0])


class TestPacingRobustness(unittest.TestCase):

    def test_duplicate_timestamps_do_not_crush_median(self):
        # The "median 0.04s" bug: many near-identical timestamps create phantom
        # zero-length shots. The fix dedups and excludes sub-frame slivers.
        scene_times = [0.0] + [15.0] * 40 + [300.0, 600.0]
        result = compute_pacing(scene_times, video_duration=810.0)
        self.assertGreater(result["median_shot_length"], 1.0)
        self.assertGreater(result["mean_shot_length"], 1.0)

    def test_non_monotonic_input_is_tolerated(self):
        # Regressed/unsorted timestamps must not raise or produce negatives.
        result = compute_pacing([0.0, 50.0, 30.0, 80.0], video_duration=100.0)
        for shot in result["shots"]:
            self.assertGreaterEqual(shot["duration_seconds"], 0.0)


if __name__ == "__main__":
    unittest.main()
