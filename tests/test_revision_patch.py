import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "skills/image-to-editable-ppt/cli/editppt/runtime"
sys.path.insert(0, str(RUNTIME_DIR))

import apply_web_revision as revision_apply  # noqa: E402
from web_bundle import BundleValidationError, json_bytes, sha256_file, write_zip_atomic  # noqa: E402


class RevisionApplyTest(unittest.TestCase):
    def make_run(self, root: Path) -> Path:
        run = root / "job-001"
        page = run / "pages/page_001"
        (page / "assets").mkdir(parents=True)
        (run / "final").mkdir(parents=True)
        (page / "source.png").write_bytes(b"source")
        (page / "manifest.json").write_text(json.dumps({"version": "old", "images": []}), encoding="utf-8")
        (page / "imagegen-jobs.json").write_text(json.dumps({"jobs": []}), encoding="utf-8")
        (page / "validation.json").write_text(json.dumps({"passed": False}), encoding="utf-8")
        (page / "preview.png").write_bytes(b"old-preview")
        (page / "page.pptx").write_bytes(b"old-page-pptx")
        (page / "page_result.json").write_text(json.dumps({"status": "failed"}), encoding="utf-8")
        (page / "assets/old.png").write_bytes(b"old")
        (page / "page_request.json").write_text(json.dumps({"page_id": "page_001"}), encoding="utf-8")
        (run / "final/deck_edited.pptx").write_bytes(b"old-final")
        deck = {
            "run_id": "job-001",
            "page_count": 1,
            "output": "final/deck_edited.pptx",
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
        (run / "page_jobs.json").write_text(
            json.dumps(
                {
                    "run_id": "job-001",
                    "run_status": "pages_dispatched",
                    "pages": [
                        {
                            "page_id": "page_001",
                            "page_index": 1,
                            "status": "dispatched",
                            "page_dir": "pages/page_001",
                            "source": "pages/page_001/source.png",
                            "page_request": "pages/page_001/page_request.json",
                            "manifest": "pages/page_001/manifest.json",
                            "validation": "pages/page_001/validation.json",
                            "dispatch": {"agent_id": "web-batch"},
                            "result": None,
                            "accepted": False,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (run / "run_state.json").write_text(json.dumps({"status": "pages_dispatched", "history": []}), encoding="utf-8")
        return run

    def make_result_bundle(self, root: Path, run: Path, source_hash=None) -> Path:
        envelope = {
            "protocol": "editppt-web-bundle",
            "version": 1,
            "bundle_type": "revision-result",
            "job_id": "job-001",
            "created_at": "2026-07-30T00:00:00Z",
            "round": 1,
            "pages": [
                {
                    "page_id": "page_001",
                    "source_sha256": source_hash or sha256_file(run / "pages/page_001/source.png"),
                }
            ],
        }
        manifest = {
            "version": "new",
            "source": {"width_px": 100, "height_px": 50},
            "visual_inventory": [],
            "background_strategy": {"mode": "native-or-script", "comparison_note": "fixed"},
            "quality_checks": {
                "font_size_calibrated": True,
                "visual_inventory_matched": True,
                "background_strategy_checked": True,
                "shape_corner_geometry_checked": True,
            },
            "text_boxes": [],
            "shapes": [],
            "images": [{"path": "assets/new.png", "box_px": [0, 0, 10, 10]}],
            "asset_provenance": [
                {
                    "path": "assets/new.png",
                    "source_type": "asset-sheet-separated",
                    "source": "assets/sheet.png",
                    "provenance_note": "web revision",
                }
            ],
        }
        bundle = root / "revision-result.zip"
        write_zip_atomic(
            bundle,
            {
                "bundle.json": json_bytes(envelope),
                "pages/page_001/manifest.json": json_bytes(manifest),
                "pages/page_001/imagegen-jobs.json": json_bytes({"jobs": []}),
                "pages/page_001/assets/new.png": b"new",
                "pages/page_001/assets/sheet.png": b"sheet",
            },
        )
        return bundle

    def test_applies_revision_preserves_history_and_resets_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self.make_run(root)
            bundle = self.make_result_bundle(root, run)

            result = revision_apply.apply_revision(run, bundle)

            page = run / "pages/page_001"
            self.assertEqual(["page_001"], result["applied_pages"])
            manifest = json.loads((page / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("new", manifest["version"])
            self.assertTrue((page / "assets/new.png").is_file())
            self.assertFalse((page / "assets/old.png").exists())
            for stale in ("page.pptx", "preview.png", "validation.json", "page_result.json"):
                self.assertFalse((page / stale).exists(), stale)
            self.assertFalse((run / "final/deck_edited.pptx").exists())
            jobs = json.loads((run / "page_jobs.json").read_text(encoding="utf-8"))
            self.assertEqual("pending", jobs["pages"][0]["status"])
            self.assertIsNone(jobs["pages"][0]["dispatch"])
            history = run / "revisions/round-01/before/page_001"
            self.assertTrue((history / "manifest.json").is_file())
            self.assertEqual("old", json.loads((history / "manifest.json").read_text(encoding="utf-8"))["version"])
            self.assertEqual(b"old-preview", (history / "preview.png").read_bytes())
            self.assertEqual(
                b"old-final",
                (run / "revisions/round-01/before/deck/final/deck_edited.pptx").read_bytes(),
            )

    def test_hash_mismatch_does_not_modify_manifest_or_final(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self.make_run(root)
            bundle = self.make_result_bundle(root, run, source_hash="c" * 64)

            with self.assertRaisesRegex(BundleValidationError, "source hash"):
                revision_apply.apply_revision(run, bundle)

            manifest = json.loads((run / "pages/page_001/manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("old", manifest["version"])
            self.assertEqual(b"old-final", (run / "final/deck_edited.pptx").read_bytes())

    def test_mid_replace_failure_restores_page_state_and_final_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self.make_run(root)
            bundle = self.make_result_bundle(root, run)

            def corrupt_then_fail(page_dir, stage):
                (page_dir / "manifest.json").write_text(json.dumps({"version": "corrupt"}), encoding="utf-8")
                (page_dir / "preview.png").unlink(missing_ok=True)
                raise OSError("injected revision copy failure")

            with mock.patch.object(revision_apply, "_replace_targets", side_effect=corrupt_then_fail):
                with self.assertRaisesRegex(OSError, "injected revision copy failure"):
                    revision_apply.apply_revision(run, bundle)

            page = run / "pages/page_001"
            self.assertEqual("old", json.loads((page / "manifest.json").read_text(encoding="utf-8"))["version"])
            self.assertEqual(b"old-preview", (page / "preview.png").read_bytes())
            self.assertEqual(b"old-page-pptx", (page / "page.pptx").read_bytes())
            self.assertEqual(b"old-final", (run / "final/deck_edited.pptx").read_bytes())
            jobs = json.loads((run / "page_jobs.json").read_text(encoding="utf-8"))
            self.assertEqual("dispatched", jobs["pages"][0]["status"])
            self.assertFalse((run / "revisions/round-01").exists())


if __name__ == "__main__":
    unittest.main()
