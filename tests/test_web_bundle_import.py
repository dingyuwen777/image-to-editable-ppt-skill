import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "skills/image-to-editable-ppt/cli/editppt/runtime"
sys.path.insert(0, str(RUNTIME_DIR))

import import_web_reconstruction as reconstruction_import  # noqa: E402
from web_bundle import BundleValidationError, json_bytes, sha256_file, write_zip_atomic  # noqa: E402


class WebBundleImportTest(unittest.TestCase):
    def make_run(self, root: Path) -> Path:
        run = root / "job-001"
        page = run / "pages/page_001"
        page.mkdir(parents=True)
        (page / "source.png").write_bytes(b"source-image")
        (page / "manifest.json").write_text('{"old": true}', encoding="utf-8")
        (page / "page_request.json").write_text(
            json.dumps({"run_id": "job-001", "page_id": "page_001"}), encoding="utf-8"
        )
        (page / "page.pptx").write_bytes(b"stale-page")
        (page / "preview.png").write_bytes(b"stale-preview")
        (page / "validation.json").write_text(json.dumps({"passed": False}), encoding="utf-8")
        deck = {
            "schema_version": 1,
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

    def valid_manifest(self):
        return {
            "source": {"width_px": 1280, "height_px": 720},
            "slide": {"width": 13.333, "height": 7.5, "background": "#FFFFFF"},
            "visual_inventory": [],
            "background_strategy": {"mode": "native-or-script", "comparison_note": "checked"},
            "quality_checks": {
                "font_size_calibrated": True,
                "visual_inventory_matched": True,
                "background_strategy_checked": True,
                "shape_corner_geometry_checked": True,
            },
            "text_boxes": [],
            "shapes": [],
            "images": [
                {
                    "path": "assets/icon.png",
                    "box_px": [0, 0, 10, 10],
                    "left": 0,
                    "top": 0,
                    "width": 1,
                    "height": 1,
                }
            ],
            "asset_provenance": [
                {
                    "path": "assets/icon.png",
                    "source_type": "asset-sheet-separated",
                    "source": "assets/icon-sheet.png",
                    "provenance_note": "generated in ChatGPT Web",
                }
            ],
        }

    def make_bundle(
        self,
        root: Path,
        run: Path,
        *,
        job_id="job-001",
        source_hash=None,
        manifest=None,
        include_asset=True,
    ) -> Path:
        source_hash = source_hash or sha256_file(run / "pages/page_001/source.png")
        manifest = manifest or self.valid_manifest()
        envelope = {
            "protocol": "editppt-web-bundle",
            "version": 1,
            "bundle_type": "reconstruction",
            "job_id": job_id,
            "created_at": "2026-07-30T00:00:00Z",
            "pages": [{"page_id": "page_001", "source_sha256": source_hash}],
        }
        members = {
            "bundle.json": json_bytes(envelope),
            "pages/page_001/manifest.json": json_bytes(manifest),
            "pages/page_001/imagegen-jobs.json": json_bytes(
                {"schema_version": 1, "run_id": "job-001", "page_id": "page_001", "jobs": []}
            ),
        }
        if include_asset:
            members["pages/page_001/assets/icon.png"] = b"icon"
            members["pages/page_001/assets/icon-sheet.png"] = b"sheet"
        bundle = root / "reconstruction.zip"
        write_zip_atomic(bundle, members)
        return bundle

    def test_imports_verified_manifest_assets_and_removes_stale_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self.make_run(root)
            bundle = self.make_bundle(root, run)

            result = reconstruction_import.import_reconstruction(run, bundle)

            page = run / "pages/page_001"
            self.assertEqual(["page_001"], result["imported_pages"])
            manifest = json.loads((page / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("assets/icon.png", manifest["images"][0]["path"])
            self.assertEqual(b"icon", (page / "assets/icon.png").read_bytes())
            metadata = json.loads((page / "web_import.json").read_text(encoding="utf-8"))
            self.assertEqual("reconstruction", metadata["bundle_type"])
            self.assertEqual(sha256_file(bundle), metadata["bundle_sha256"])
            self.assertFalse((page / "page.pptx").exists())
            self.assertFalse((page / "preview.png").exists())
            self.assertFalse((page / "validation.json").exists())

    def test_rejects_mismatched_job_without_modifying_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self.make_run(root)
            bundle = self.make_bundle(root, run, job_id="other-job")

            with self.assertRaisesRegex(BundleValidationError, "job id"):
                reconstruction_import.import_reconstruction(run, bundle)

            self.assertEqual('{"old": true}', (run / "pages/page_001/manifest.json").read_text(encoding="utf-8"))

    def test_rejects_source_hash_mismatch_without_modifying_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self.make_run(root)
            bundle = self.make_bundle(root, run, source_hash="b" * 64)

            with self.assertRaisesRegex(BundleValidationError, "source hash"):
                reconstruction_import.import_reconstruction(run, bundle)

            self.assertEqual('{"old": true}', (run / "pages/page_001/manifest.json").read_text(encoding="utf-8"))

    def test_rejects_missing_manifest_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self.make_run(root)
            bundle = self.make_bundle(root, run, include_asset=False)

            with self.assertRaisesRegex(BundleValidationError, "missing asset"):
                reconstruction_import.import_reconstruction(run, bundle)

    def test_rejects_asset_path_outside_assets_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self.make_run(root)
            manifest = self.valid_manifest()
            manifest["images"][0]["path"] = "../source.png"
            manifest["asset_provenance"] = []
            bundle = self.make_bundle(root, run, manifest=manifest)

            with self.assertRaisesRegex(BundleValidationError, "asset path"):
                reconstruction_import.import_reconstruction(run, bundle)

    def test_rejects_schema_invalid_manifest_before_modifying_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self.make_run(root)
            manifest = self.valid_manifest()
            del manifest["quality_checks"]
            bundle = self.make_bundle(root, run, manifest=manifest)

            with self.assertRaisesRegex(BundleValidationError, "manifest contract"):
                reconstruction_import.import_reconstruction(run, bundle)

            self.assertEqual('{"old": true}', (run / "pages/page_001/manifest.json").read_text(encoding="utf-8"))

    def test_rejects_initial_import_after_page_processing_started(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self.make_run(root)
            jobs_path = run / "page_jobs.json"
            jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
            jobs["pages"][0]["status"] = "dispatched"
            jobs["pages"][0]["dispatch"] = {"agent_id": "web-batch"}
            jobs_path.write_text(json.dumps(jobs), encoding="utf-8")
            bundle = self.make_bundle(root, run)

            with self.assertRaisesRegex(BundleValidationError, "revision"):
                reconstruction_import.import_reconstruction(run, bundle)

    def test_mid_replace_failure_restores_current_page_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self.make_run(root)
            bundle = self.make_bundle(root, run)
            original_replace = reconstruction_import._replace_targets

            def corrupt_then_fail(page_dir, stage):
                (page_dir / "manifest.json").write_text('{"corrupt": true}', encoding="utf-8")
                (page_dir / "preview.png").unlink(missing_ok=True)
                raise OSError("injected copy failure")

            with mock.patch.object(reconstruction_import, "_replace_targets", side_effect=corrupt_then_fail):
                with self.assertRaisesRegex(OSError, "injected copy failure"):
                    reconstruction_import.import_reconstruction(run, bundle)

            page = run / "pages/page_001"
            self.assertEqual('{"old": true}', (page / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(b"stale-preview", (page / "preview.png").read_bytes())
            self.assertEqual(b"stale-page", (page / "page.pptx").read_bytes())


if __name__ == "__main__":
    unittest.main()
