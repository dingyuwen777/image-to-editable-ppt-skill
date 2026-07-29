import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "skills/image-to-editable-ppt/cli/editppt/runtime"
sys.path.insert(0, str(RUNTIME_DIR))

from make_visual_diff import VisualDiffError, make_visual_diff  # noqa: E402


class VisualDiffTest(unittest.TestCase):
    def test_identical_images_have_zero_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp)
            image = Image.new("RGB", (120, 68), "white")
            image.save(page / "source.png")
            image.save(page / "preview.png")

            result = make_visual_diff(page)

            self.assertEqual(0.0, result["mean_absolute_error"])
            self.assertEqual(0.0, result["root_mean_square_error"])
            self.assertEqual(0.0, result["changed_pixel_ratio"])
            self.assertEqual(0, result["max_channel_error"])
            self.assertTrue((page / "visual_diff.png").is_file())
            metrics = json.loads((page / "visual_metrics.json").read_text(encoding="utf-8"))
            self.assertFalse(metrics["preview_resized_for_comparison"])

    def test_changed_and_resized_preview_reports_diagnostic_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp)
            Image.new("RGB", (120, 68), "white").save(page / "source.png")
            Image.new("RGB", (60, 34), "black").save(page / "preview.png")

            result = make_visual_diff(page, changed_threshold=8)

            self.assertGreater(result["mean_absolute_error"], 0.99)
            self.assertGreater(result["root_mean_square_error"], 0.99)
            self.assertEqual(1.0, result["changed_pixel_ratio"])
            self.assertEqual(255, result["max_channel_error"])
            self.assertTrue(result["preview_resized_for_comparison"])
            self.assertIn("Diagnostic only", result["interpretation"])

    def test_missing_preview_is_a_hard_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp)
            Image.new("RGB", (20, 10), "white").save(page / "source.png")
            with self.assertRaisesRegex(VisualDiffError, "missing preview"):
                make_visual_diff(page)


if __name__ == "__main__":
    unittest.main()
