import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "skills/image-to-editable-ppt/cli/editppt/runtime"
sys.path.insert(0, str(RUNTIME_DIR))

from export_web_handoff import export_handoff  # noqa: E402
from web_bundle import load_bundle_envelope, safe_extract, sha256_file  # noqa: E402


class WebHandoffExportTest(unittest.TestCase):
    def make_run(self, root: Path) -> Path:
        run = root / "job-001"
        page = run / "pages/page_001"
        page.mkdir(parents=True)
        source = page / "source.png"
        source.write_bytes(b"source-image")
        (page / "text_hints.json").write_text(
            json.dumps({"lines": [{"text": "标题", "box_px": [10, 10, 100, 30]}]}),
            encoding="utf-8",
        )
        (page / "text_hints.png").write_bytes(b"overlay")
        (page / "page_request.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": "job-001",
                    "page_id": "page_001",
                    "page_index": 1,
                    "page_dir": str(page.resolve()),
                    "source_image": str(source.resolve()),
                    "source_size_px": {"width": 1280, "height": 720},
                    "slide": {"width": 13.333, "height": 7.5, "size_mode": "wide"},
                    "content_box": {"left": 0, "top": 0, "width": 13.333, "height": 7.5},
                    "allowed_write_scope": str(page.resolve()),
                    "forbidden_paths": [str((run / "input").resolve())],
                    "required_outputs": {"manifest": str((page / "manifest.json").resolve())},
                }
            ),
            encoding="utf-8",
        )
        deck = {
            "schema_version": 1,
            "run_id": "job-001",
            "job_dir": str(run.resolve()),
            "input_type": "pdf",
            "page_count": 1,
            "inputs": ["input/deck.pdf"],
            "slide": {"width": 13.333, "height": 7.5, "size_mode": "wide"},
            "output": "final/deck_edited.pptx",
            "notes_manifest": "notes_manifest.json",
            "pages": [
                {
                    "page_id": "page_001",
                    "page_index": 1,
                    "source_image": "pages/page_001/source.png",
                    "page_dir": "pages/page_001",
                    "page_request": "pages/page_001/page_request.json",
                    "manifest": "pages/page_001/manifest.json",
                    "validation": "pages/page_001/validation.json",
                }
            ],
        }
        (run / "deck_manifest.json").write_text(json.dumps(deck), encoding="utf-8")
        (run / "notes_manifest.json").write_text(
            json.dumps({"source": "input/deck.pdf", "notes": [{"page_index": 1, "text": "speaker note"}]}),
            encoding="utf-8",
        )
        (run / "page_jobs.json").write_text(
            json.dumps({"run_id": "job-001", "pages": [{"page_id": "page_001", "status": "pending"}]}),
            encoding="utf-8",
        )
        (run / "secret.env").write_text("OPENAI_API_KEY=must-not-export", encoding="utf-8")
        return run

    def make_instructions(self, root: Path) -> Path:
        instructions = root / "instructions"
        instructions.mkdir()
        (instructions / "web-batch-worker.md").write_text("# Worker", encoding="utf-8")
        (instructions / "page-decision-tree.md").write_text("# Decision", encoding="utf-8")
        (instructions / "manifest-schema.md").write_text("# Schema", encoding="utf-8")
        (instructions / "web-bundle-protocol.md").write_text("# Protocol", encoding="utf-8")
        return instructions

    def test_export_handoff_is_portable_allowlisted_and_hashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self.make_run(root)
            instructions = self.make_instructions(root)
            out = root / "handoff.zip"

            result = export_handoff(run, out, instructions_root=instructions)

            self.assertEqual(out, Path(result["bundle"]))
            self.assertTrue(out.is_file())
            with zipfile.ZipFile(out) as archive:
                names = set(archive.namelist())
                self.assertIn("bundle.json", names)
                self.assertIn("deck_manifest.json", names)
                self.assertIn("pages/page_001/source.png", names)
                self.assertIn("pages/page_001/page_request.json", names)
                self.assertIn("pages/page_001/text_hints.json", names)
                self.assertIn("instructions/web-batch-worker.md", names)
                self.assertNotIn("secret.env", names)
                all_bytes = b"\n".join(archive.read(name) for name in names)
                self.assertNotIn(str(run.resolve()).encode(), all_bytes)
                self.assertNotIn(b"OPENAI_API_KEY", all_bytes)

            extract = root / "extract"
            safe_extract(out, extract)
            envelope = load_bundle_envelope(extract, expected_type="handoff")
            self.assertEqual("job-001", envelope["job_id"])
            self.assertEqual(
                sha256_file(run / "pages/page_001/source.png"),
                envelope["pages"][0]["source_sha256"],
            )
            portable_request = json.loads(
                (extract / "pages/page_001/page_request.json").read_text(encoding="utf-8")
            )
            self.assertEqual("pages/page_001", portable_request["page_dir"])
            self.assertEqual("pages/page_001/source.png", portable_request["source_image"])
            self.assertNotIn("allowed_write_scope", portable_request)
            self.assertNotIn("forbidden_paths", portable_request)

    def test_export_is_atomic_when_required_source_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self.make_run(root)
            instructions = self.make_instructions(root)
            out = root / "handoff.zip"
            out.write_bytes(b"old")
            (run / "pages/page_001/source.png").unlink()

            with self.assertRaises(FileNotFoundError):
                export_handoff(run, out, instructions_root=instructions)

            self.assertEqual(b"old", out.read_bytes())


if __name__ == "__main__":
    unittest.main()
