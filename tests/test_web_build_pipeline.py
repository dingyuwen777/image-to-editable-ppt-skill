import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "skills/image-to-editable-ppt/cli/editppt/runtime"
sys.path.insert(0, str(RUNTIME_DIR))

from build_web_run import build_web_run  # noqa: E402


class WebBuildPipelineTest(unittest.TestCase):
    def make_run(self, root: Path, valid_manifest=True) -> Path:
        run = root / "job-001"
        page = run / "pages/page_001"
        page.mkdir(parents=True)
        Image.new("RGB", (160, 90), "white").save(page / "source.png")
        (page / "page_request.json").write_text(
            json.dumps({"run_id": "job-001", "page_id": "page_001"}), encoding="utf-8"
        )
        manifest = {
            "source": {"width_px": 160, "height_px": 90},
            "slide": {"width": 13.333, "height": 7.5, "background": "#FFFFFF"},
            "visual_inventory": [],
            "background_strategy": {
                "mode": "native-or-script",
                "comparison_note": "blank white source reproduced as native background",
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
        if not valid_manifest:
            manifest.pop("quality_checks")
        (page / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (page / "imagegen-jobs.json").write_text(
            json.dumps({"schema_version": 1, "run_id": "job-001", "page_id": "page_001", "jobs": []}),
            encoding="utf-8",
        )
        (page / "web_import.json").write_text(
            json.dumps({"bundle_type": "reconstruction", "backend": "web-artifact"}), encoding="utf-8"
        )
        deck = {
            "schema_version": 1,
            "run_id": "job-001",
            "job_dir": str(run),
            "input_type": "image",
            "page_count": 1,
            "slide": {"width": 13.333, "height": 7.5, "size_mode": "wide"},
            "output": "final/deck_edited.pptx",
            "notes_manifest": "notes_manifest.json",
            "pages": [
                {
                    "page_id": "page_001",
                    "page_index": 1,
                    "page_dir": "pages/page_001",
                    "source_image": "pages/page_001/source.png",
                    "page_request": "pages/page_001/page_request.json",
                    "manifest": "pages/page_001/manifest.json",
                    "validation": "pages/page_001/validation.json",
                }
            ],
        }
        (run / "deck_manifest.json").write_text(json.dumps(deck), encoding="utf-8")
        (run / "notes_manifest.json").write_text(json.dumps({"source": None, "notes": []}), encoding="utf-8")
        (run / "page_jobs.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": "job-001",
                    "run_status": "inputs_prepared",
                    "max_concurrent_pages": 6,
                    "pages": [
                        {
                            "page_id": "page_001",
                            "page_index": 1,
                            "status": "pending",
                            "page_dir": "pages/page_001",
                            "source": "pages/page_001/source.png",
                            "page_request": "pages/page_001/page_request.json",
                            "manifest": "pages/page_001/manifest.json",
                            "validation": "pages/page_001/validation.json",
                            "dispatch": None,
                            "result": None,
                            "accepted": False,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (run / "run_state.json").write_text(json.dumps({"status": "inputs_prepared", "history": []}), encoding="utf-8")
        return run

    def test_builds_records_valid_pages_and_finalizes_deck(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.make_run(Path(tmp))

            result = build_web_run(run)

            page = run / "pages/page_001"
            self.assertTrue(result["passed"])
            self.assertTrue(result["finalized"])
            self.assertEqual(["page_001"], result["recorded_pages"])
            self.assertTrue((page / "page.pptx").is_file())
            self.assertTrue((page / "preview.png").is_file())
            self.assertTrue((page / "split_assets_contact.png").is_file())
            self.assertTrue((page / "visual_diff.png").is_file())
            self.assertTrue((page / "visual_metrics.json").is_file())
            metrics = json.loads((page / "visual_metrics.json").read_text(encoding="utf-8"))
            self.assertGreaterEqual(metrics["changed_pixel_ratio"], 0.0)
            self.assertLessEqual(metrics["changed_pixel_ratio"], 1.0)
            page_result = json.loads((page / "page_result.json").read_text(encoding="utf-8"))
            self.assertEqual("visual_diff.png", page_result["visual_diff"])
            self.assertEqual("visual_metrics.json", page_result["visual_metrics"])
            self.assertTrue((run / "final/deck_edited.pptx").is_file())
            jobs = json.loads((run / "page_jobs.json").read_text(encoding="utf-8"))
            self.assertEqual("accepted", jobs["pages"][0]["status"])

    def test_invalid_page_is_reported_and_not_finalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.make_run(Path(tmp), valid_manifest=False)

            result = build_web_run(run)

            self.assertFalse(result["passed"])
            self.assertFalse(result["finalized"])
            self.assertEqual(["page_001"], [item["page_id"] for item in result["failed_pages"]])
            self.assertFalse((run / "final/deck_edited.pptx").exists())
            validation = json.loads((run / "pages/page_001/validation.json").read_text(encoding="utf-8"))
            self.assertFalse(validation["passed"])


if __name__ == "__main__":
    unittest.main()
