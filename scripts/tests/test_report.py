"""Tests for report.md emission."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

from report import write_report  # noqa: E402


class TestReport(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="watch-report-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_writes_all_required_sections(self):
        out = write_report(
            out_path=self.tmp / "report.md",
            source="https://youtu.be/test",
            title="Test Video",
            duration_seconds=125.0,
            intent="studying hook patterns",
            transcript_segments=[
                {"start": 0.0, "end": 2.0, "text": "Hello world."},
                {"start": 2.0, "end": 5.0, "text": "Second segment."},
            ],
            transcript_source="captions",
            all_frames=[
                {"index": 0, "timestamp_seconds": 0.0, "path": "/tmp/f1.jpg"},
                {"index": 1, "timestamp_seconds": 5.0, "path": "/tmp/f2.jpg"},
                {"index": 2, "timestamp_seconds": 60.0, "path": "/tmp/f3.jpg"},
            ],
            hero_frames=[
                {"index": 0, "timestamp_seconds": 0.0, "path": "/tmp/f1.jpg"},
                {"index": 1, "timestamp_seconds": 5.0, "path": "/tmp/f2.jpg"},
            ],
            pacing={
                "shot_count": 6,
                "cuts_per_minute": 2.88,
                "mean_shot_length": 20.83,
                "median_shot_length": 18.5,
                "shots": [],
            },
            hook={"frames": [], "words": [], "ran": False, "skipped_reason": "video <30s"},
        )

        text = out.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("source: https://youtu.be/test", text)
        self.assertIn("intent: studying hook patterns", text)
        self.assertIn("hero_frames:", text)
        for header in (
            "# Test Video",
            "## TL;DR",
            "## Key moments",
            "## Hook microscope",
            "## Editorial profile",
            "## Quotable moments",
            "## Entities mentioned",
            "## Concepts surfaced",
            "## Transcript",
        ):
            self.assertIn(header, text, f"missing: {header}")
        self.assertIn("<!-- pending agent fill", text)
        self.assertIn("Cuts/min: 2.88", text)
        self.assertIn("Mean shot length: 20.83", text)
        self.assertIn("Hello world.", text)


if __name__ == "__main__":
    unittest.main()
