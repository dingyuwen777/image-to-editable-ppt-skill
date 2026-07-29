import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "skills/image-to-editable-ppt/cli/editppt/runtime"
sys.path.insert(0, str(RUNTIME_DIR))

from export_web_revision import export_revision  # noqa: E402
from web_bundle import load_bundle_envelope, safe_extract  # noqa: E402


class RevisionBundleTest(unittest.TestCase):
    def make_run(self, root: Path) -> Path:
        run = root / "job-001"
        pages = []
        jobs = []
        for index, status in ((1, "dispatched"), (2, "accepted")):
            page_id = f"page_{index:03d}"
            page_dir = run / "pages" / page_id
            page_dir.mkdir(parents=True)
            (page_dir / "source.png").write_bytes(f"source-{index}".encode())
            (page_dir / "manifest.json").write_text(
                json.dumps({"source": {"width_px": 100, "height_px": 50}, "text_boxes": [], "images": [], "shapes": []}),
                encoding="utf-8",
            )
            (page_dir / "validation.json").write_text(
                json.dumps({"passed": status == "accepted", "warnings": ["needs correction"] if status != "accepted" else []}),
                encoding="utf-8",
            )
            (page_dir / "preview.png").write_bytes(b"preview")
            (page_dir / "split_assets_contact.png").write_bytes(b"contact")
            (page_dir / "text_hints.json").write_text(json.dumps({"lines": []}), encoding="utf-8")
            (page_dir / "imagegen-jobs.json").write_text(json.dumps({"jobs": []}), encoding="utf-8")
            pages.append(
                {
                    "page_id": page_id,
                    "page_index": index,
                    "page_dir": f"pages/{page_id}",
                    "source_image": f"pages/{page_id}/source.png",
                    "manifest": f"pages/{page_id}/manifest.json",
                    "validation": f"pages/{page_id}/validation.json",
                }
            )
            jobs.append(
                {
                    "page_id": page_id,
                    "page_index": index,
                    "status": status,
                    "page_dir": f"pages/{page_id}",
                    "source": f"pages/{page_id}/source.png",
                    "page_request": f"pages/{page_id}/page_request.json",
                    "manifest": f"pages/{page_id}/manifest.json",
                    "validation": f"pages/{page_id}/validation.json",
                    "dispatch": {"agent_id": "web-batch"} if status == "dispatched" else None,
                    "result": {"validation_passed": True} if status == "accepted" else None,
                    "accepted": status == "accepted",
                }
            )
        (run / "deck_manifest.json").write_text(
            json.dumps({"run_id": "job-001", "page_count": 2, "pages": pages}), encoding="utf-8"
        )
        (run / "page_jobs.json").write_text(json.dumps({"run_id": "job-001", "pages": jobs}), encoding="utf-8")
        return run

    def test_exports_only_failed_or_unrecorded_pages_with_current_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self.make_run(root)
            out = root / "revision.zip"

            result = export_revision(run, out, round_number=1)

            self.assertEqual(["page_001"], result["pages"])
            with zipfile.ZipFile(out) as archive:
                names = set(archive.namelist())
                self.assertIn("pages/page_001/source.png", names)
                self.assertIn("pages/page_001/current-manifest.json", names)
                self.assertIn("pages/page_001/preview.png", names)
                self.assertIn("pages/page_001/validation.json", names)
                self.assertIn("pages/page_001/correction-request.json", names)
                self.assertFalse(any(name.startswith("pages/page_002/") for name in names))
            extract = root / "extract"
            safe_extract(out, extract)
            envelope = load_bundle_envelope(extract, expected_type="revision-request")
            self.assertEqual(1, envelope["round"])

    def test_raises_when_no_pages_need_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self.make_run(root)
            jobs_path = run / "page_jobs.json"
            jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
            for page in jobs["pages"]:
                page["status"] = "accepted"
                page["accepted"] = True
                page["result"] = {"validation_passed": True}
            jobs_path.write_text(json.dumps(jobs), encoding="utf-8")
            for page_id in ("page_001", "page_002"):
                (run / "pages" / page_id / "validation.json").write_text(json.dumps({"passed": True}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "no pages"):
                export_revision(run, root / "revision.zip")


if __name__ == "__main__":
    unittest.main()
