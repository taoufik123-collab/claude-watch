"""Unit tests for VTT transcript parsing, dedupe, and formatting."""
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

from transcribe import filter_range, format_transcript, parse_vtt  # noqa: E402


VTT_WITH_ROLLING_DUPES = """WEBVTT

00:00:00.000 --> 00:00:02.000
Hello there

00:00:02.000 --> 00:00:04.000
Hello there
general

00:00:04.000 --> 00:00:06.000
general
kenobi
"""


class TestTranscribe(unittest.TestCase):

    def _write_vtt(self, content: str) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".vtt", delete=False)
        f.write(content)
        f.close()
        return f.name

    def test_dedupes_rolling_captions(self):
        path = self._write_vtt(VTT_WITH_ROLLING_DUPES)
        segments = parse_vtt(path)
        # "Hello there" is absorbed into the next cue (rolling prefix match),
        # then "general kenobi" drops the now-scrolled-off first word.
        self.assertEqual([seg["text"] for seg in segments], ["Hello there general", "general kenobi"])
        self.assertEqual(segments[0]["start"], 0.0)
        self.assertEqual(segments[0]["end"], 4.0)
        self.assertEqual(segments[-1]["end"], 6.0)

    def test_strips_tags_and_skips_blank_cues(self):
        vtt = (
            "WEBVTT\n\n"
            "00:00:01.500 --> 00:00:03.250\n"
            "<c>Styled</c> text\n\n"
            "00:00:04.000 --> 00:00:05.000\n"
            "\n"
        )
        path = self._write_vtt(vtt)
        segments = parse_vtt(path)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["text"], "Styled text")
        self.assertEqual(segments[0]["start"], 1.5)
        self.assertEqual(segments[0]["end"], 3.25)

    def test_filter_range_keeps_overlapping_segments(self):
        segments = [
            {"start": 0.0, "end": 5.0, "text": "a"},
            {"start": 5.0, "end": 10.0, "text": "b"},
            {"start": 20.0, "end": 25.0, "text": "c"},
        ]
        result = filter_range(segments, start_seconds=4.0, end_seconds=6.0)
        self.assertEqual([seg["text"] for seg in result], ["a", "b"])

    def test_filter_range_returns_all_when_unbounded(self):
        segments = [{"start": 0.0, "end": 5.0, "text": "a"}]
        self.assertEqual(filter_range(segments, None, None), segments)

    def test_format_transcript_adds_mmss_stamps(self):
        segments = [{"start": 65.0, "end": 70.0, "text": "hi"}]
        self.assertEqual(format_transcript(segments), "[01:05] hi")


if __name__ == "__main__":
    unittest.main()
