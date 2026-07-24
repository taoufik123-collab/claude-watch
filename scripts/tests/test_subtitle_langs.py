"""Unit tests for native-language subtitle resolution (the v2 en-only bug)."""
import os
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

from download import resolve_sub_langs  # noqa: E402


class TestResolveSubLangs(unittest.TestCase):

    def test_german_video_requests_german_first(self):
        # The exact failure from the v2 review: a German talking-head whose
        # downloadable auto-caption tracks are `de` and `de-orig`, while the
        # `language` field is the regional tag `de-DE`.
        meta = {
            "language": "de-DE",
            "subtitles": {},
            "automatic_captions": {"de": [], "de-orig": [], "en": [], "fr": []},
        }
        langs, native = resolve_sub_langs(meta)
        self.assertEqual(native, "de-DE")
        # German must come before English.
        self.assertLess(langs.index("de"), langs.index("en"))
        # The faithful "-orig" track is preferred first.
        self.assertEqual(langs[0], "de-orig")

    def test_english_video_still_works(self):
        meta = {
            "language": "en-US",
            "subtitles": {},
            "automatic_captions": {"en": [], "en-orig": [], "de": []},
        }
        langs, native = resolve_sub_langs(meta)
        self.assertIn("en", langs)
        self.assertEqual(langs[0].split("-")[0], "en")

    def test_manual_subs_outrank_auto(self):
        meta = {
            "language": None,
            "subtitles": {"es": []},
            "automatic_captions": {"en": []},
        }
        langs, _ = resolve_sub_langs(meta)
        self.assertIn("es", langs)

    def test_live_chat_is_dropped(self):
        meta = {
            "language": "de",
            "subtitles": {},
            "automatic_captions": {"de": [], "live_chat": []},
        }
        langs, _ = resolve_sub_langs(meta)
        self.assertNotIn("live_chat", langs)

    def test_env_override_wins(self):
        os.environ["WATCH_SUB_LANGS"] = "fr, es"
        try:
            langs, native = resolve_sub_langs({"language": "de"})
            self.assertEqual(langs, ["fr", "es"])
            self.assertIsNone(native)
        finally:
            del os.environ["WATCH_SUB_LANGS"]

    def test_request_is_capped(self):
        # A video with dozens of auto tracks must not produce a huge request.
        meta = {
            "language": "ja",
            "subtitles": {},
            "automatic_captions": {c: [] for c in
                                   ["ja", "ja-orig", "en", "de", "fr", "es",
                                    "it", "pt", "ru", "zh", "ko", "ar"]},
        }
        langs, _ = resolve_sub_langs(meta)
        self.assertLessEqual(len(langs), 6)
        self.assertEqual(langs[0], "ja-orig")


if __name__ == "__main__":
    unittest.main()
