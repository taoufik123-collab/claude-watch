"""Smoke tests for scene-change frame extraction."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

from frames import extract_scene_change, extract  # noqa: E402


def _make_test_video(out: Path, seconds: int = 6) -> Path:
    """Generate a synthetic test video with 3 distinct scenes (color changes)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c=red:size=320x240:duration=2",
        "-f", "lavfi", "-i", f"color=c=green:size=320x240:duration=2",
        "-f", "lavfi", "-i", f"color=c=blue:size=320x240:duration=2",
        "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
        "-map", "[v]",
        "-pix_fmt", "yuv420p",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


class TestSceneChange(unittest.TestCase):

    def setUp(self):
        if shutil.which("ffmpeg") is None:
            self.skipTest("ffmpeg not available")
        self.tmp = Path(tempfile.mkdtemp(prefix="watch-test-"))
        self.video = _make_test_video(self.tmp / "input.mp4", seconds=6)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_detects_scene_boundaries(self):
        out_dir = self.tmp / "frames"
        frames = extract_scene_change(
            str(self.video), out_dir,
            scene_threshold=0.3, resolution=128, max_frames=10,
        )
        self.assertGreaterEqual(len(frames), 2, "expected >=2 scene frames")
        self.assertLessEqual(len(frames), 10, "respect max_frames cap")
        for f in frames:
            self.assertTrue(Path(f["path"]).exists())
            self.assertIn("timestamp_seconds", f)

    def test_falls_back_to_uniform_when_no_scenes(self):
        static = self.tmp / "static.mp4"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=red:size=320x240:duration=4",
            "-pix_fmt", "yuv420p",
            str(static),
        ], check=True, capture_output=True)

        out_dir = self.tmp / "static_frames"
        frames = extract_scene_change(
            str(static), out_dir,
            scene_threshold=0.3, resolution=128,
            max_frames=10, uniform_fallback_min=5,
        )
        self.assertGreaterEqual(len(frames), 5, "fallback should produce >=5 frames")



    def test_ffmpeg_flag_fallback(self):
        """Verify automatic fallback from -fps_mode to -vsync when modern flag fails."""
        import unittest.mock as mock
        orig_run = subprocess.run
        ffmpeg_calls = []

        out_dir = self.tmp / "fallback_frames"
        out_dir.mkdir(parents=True, exist_ok=True)

        def fake_run(cmd, *args, **kwargs):
            if cmd and cmd[0] == "ffmpeg":
                ffmpeg_calls.append(list(cmd))
                if len(ffmpeg_calls) == 1 and "-fps_mode" in cmd:
                    return subprocess.CompletedProcess(
                        cmd, 1, stdout="", stderr="Unrecognized option 'fps_mode'."
                    )
                # Second call simulates legacy ffmpeg succeeding with -vsync
                (out_dir / "frame_0001.jpg").touch()
                (out_dir / "frame_0002.jpg").touch()
                return subprocess.CompletedProcess(
                    cmd, 0, stdout="pts_time:0.0\npts_time:1.0\n", stderr=""
                )
            return orig_run(cmd, *args, **kwargs)

        with mock.patch("subprocess.run", side_effect=fake_run):
            frames = extract_scene_change(
                str(self.video), out_dir,
                scene_threshold=0.3, resolution=128, max_frames=10,
                uniform_fallback_min=1,
            )
            self.assertEqual(len(ffmpeg_calls), 2)
            self.assertIn("-fps_mode", ffmpeg_calls[0])
            self.assertIn("-vsync", ffmpeg_calls[1])
            self.assertEqual(len(frames), 2)

if __name__ == "__main__":
    unittest.main()
