import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "skills/image-to-editable-ppt/cli/editppt/runtime"
sys.path.insert(0, str(RUNTIME_DIR))

from build_web_run import build_web_run  # noqa: E402
from export_web_handoff import export_handoff  # noqa: E402
from import_web_reconstruction import import_reconstruction  # noqa: E402
from web_bundle import json_bytes, load_bundle_envelope, safe_extract, write_zip_atomic  # noqa: E402


class WebBatchEndToEndTest(unittest.TestCase):
    def blank_manifest(self, width, height):
        return {
            "source": {"width_px": width, "height_px": height},
            "slide": {"width": 13.333, "height": 7.5, "background": "#FFFFFF"},
            "visual_inventory": [],
            "background_strategy": {
                "mode": "native-or-script",
                "comparison_note": "blank white source reproduced by native background",
            },
            "quality_checks": {
                "font_size_calibrated": True,
                "visual_inventory_matched": True,
                "background_strategy_checked": True,
                "shape_corner_geometry_checked": True,
            },
            "required_text": [],
            "text_boxes": [],
            "images": [],
            "shapes": [],
            "asset_provenance": [],
        }

    def test_prepare_export_import_build_finalize_two_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "第一页.png"
            second = root / "第二页.png"
            Image.new("RGB", (160, 90), "white").save(first)
            Image.new("RGB", (160, 90), "white").save(second)
            run = root / "runtime-data/中文任务"

            prepare = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME_DIR / "prepare_deck_run.py"),
                    str(first),
                    str(second),
                    "--job-dir",
                    str(run),
                    "--image-backend",
                    "web-artifact",
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, prepare.returncode, prepare.stdout + prepare.stderr)
            self.assertTrue((run / "deck_manifest.json").is_file())
            self.assertTrue((run / "pages/page_001/text_hints.json").is_file())
            self.assertTrue((run / "pages/page_002/text_hints.json").is_file())

            handoff = root / "handoff.zip"
            export_result = export_handoff(run, handoff)
            self.assertEqual(2, export_result["pages"])

            extracted = root / "handoff-extracted"
            safe_extract(handoff, extracted)
            envelope = load_bundle_envelope(extracted, expected_type="handoff")
            self.assertEqual(2, len(envelope["pages"]))

            reconstruction_members = {}
            reconstruction_pages = []
            for page in envelope["pages"]:
                page_id = page["page_id"]
                source = Image.open(extracted / page["source_path"])
                reconstruction_pages.append(
                    {
                        "page_id": page_id,
                        "page_index": page["page_index"],
                        "source_sha256": page["source_sha256"],
                    }
                )
                prefix = f"pages/{page_id}"
                reconstruction_members[f"{prefix}/manifest.json"] = json_bytes(
                    self.blank_manifest(source.width, source.height)
                )
                reconstruction_members[f"{prefix}/imagegen-jobs.json"] = json_bytes(
                    {
                        "schema_version": 1,
                        "run_id": envelope["job_id"],
                        "page_id": page_id,
                        "jobs": [],
                    }
                )
                reconstruction_members[f"{prefix}/web_result.json"] = json_bytes(
                    {
                        "schema_version": 1,
                        "page_id": page_id,
                        "status": "completed",
                        "summary": "blank page integration fixture",
                        "warnings": [],
                    }
                )

            reconstruction_members["bundle.json"] = json_bytes(
                {
                    "protocol": "editppt-web-bundle",
                    "version": 1,
                    "bundle_type": "reconstruction",
                    "job_id": envelope["job_id"],
                    "created_at": "2026-07-30T00:00:00Z",
                    "pages": reconstruction_pages,
                }
            )
            reconstruction = root / "reconstruction.zip"
            write_zip_atomic(reconstruction, reconstruction_members)

            imported = import_reconstruction(run, reconstruction)
            self.assertEqual(["page_001", "page_002"], imported["imported_pages"])
            result = build_web_run(run)

            self.assertTrue(result["passed"], result)
            self.assertTrue(result["finalized"], result)
            self.assertEqual(["page_001", "page_002"], result["recorded_pages"])
            self.assertTrue(Path(result["output"]).is_file())
            for page_id in ("page_001", "page_002"):
                page_dir = run / "pages" / page_id
                self.assertTrue((page_dir / "page.pptx").is_file())
                self.assertTrue((page_dir / "preview.png").is_file())
                self.assertTrue((page_dir / "visual_diff.png").is_file())
                self.assertTrue((page_dir / "validation.json").is_file())


if __name__ == "__main__":
    unittest.main()
