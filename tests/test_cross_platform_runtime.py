import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "skills/image-to-editable-ppt/cli/editppt/runtime"
sys.path.insert(0, str(RUNTIME_DIR))

import _input_normalization as input_normalization  # noqa: E402
from platform_support import find_imagemagick, preview_font_candidates  # noqa: E402


class CrossPlatformRuntimeTest(unittest.TestCase):
    def test_ppt_normalization_passes_function_dpi_not_undefined_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_ppt = root / "中文演示.ppt"
            input_ppt.write_bytes(b"ppt")
            job_dir = root / "run"

            def fake_render(_pdf, pages_dir, dpi):
                self.assertEqual(222, dpi)
                page_dir = pages_dir / "page_001"
                page_dir.mkdir(parents=True, exist_ok=True)
                source = page_dir / "source.png"
                source.write_bytes(b"png")
                return [source]

            converted = root / "converted.pptx"
            converted.write_bytes(b"pptx")
            with mock.patch.object(
                input_normalization, "convert_ppt_to_pptx", return_value=converted
            ), mock.patch.object(
                input_normalization, "collect_notes_from_pptx", return_value=[]
            ), mock.patch.object(
                input_normalization, "convert_office_to_pdf", return_value=root / "rendered.pdf"
            ), mock.patch.object(
                input_normalization, "render_pdf_pages", side_effect=fake_render
            ):
                deck_path = input_normalization.normalize_inputs([input_ppt], job_dir=job_dir, dpi=222)

            self.assertTrue(deck_path.is_file())

    def test_imagemagick_discovery_uses_path_lookup(self):
        with mock.patch("shutil.which", side_effect=lambda name: "/usr/bin/magick" if name == "magick" else None):
            self.assertEqual("/usr/bin/magick", find_imagemagick())

    def test_preview_font_candidates_cover_windows_linux_and_macos(self):
        candidates = preview_font_candidates(None)
        joined = "\n".join(candidates)
        self.assertIn("msyh", joined.lower())
        self.assertIn("NotoSansCJK", joined)
        self.assertIn("PingFang", joined)


if __name__ == "__main__":
    unittest.main()
