import json
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "skills/image-to-editable-ppt/cli/editppt/runtime"
sys.path.insert(0, str(RUNTIME_DIR))

import web_bundle  # noqa: E402
from web_bundle import (  # noqa: E402
    BundleLimits,
    BundleValidationError,
    inspect_zip,
    load_bundle_envelope,
    normalize_member_name,
    safe_extract,
    sha256_file,
)


class WebBundleSecurityTest(unittest.TestCase):
    def make_zip(self, members):
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "bundle.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, payload in members:
                if isinstance(payload, zipfile.ZipInfo):
                    archive.writestr(payload, b"target")
                else:
                    archive.writestr(name, payload)
        self.addCleanup(tmp.cleanup)
        return path

    def valid_envelope(self, bundle_type="handoff"):
        return {
            "protocol": "editppt-web-bundle",
            "version": 1,
            "bundle_type": bundle_type,
            "job_id": "job-001",
            "created_at": "2026-07-30T00:00:00Z",
            "pages": [{"page_id": "page_001", "source_sha256": "a" * 64}],
        }

    def test_sha256_file_hashes_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.bin"
            path.write_bytes(b"abc")
            self.assertEqual(
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
                sha256_file(path),
            )

    def test_normalize_member_name_accepts_posix_relative_path(self):
        self.assertEqual("pages/page_001/source.png", normalize_member_name("pages/page_001/source.png"))

    def test_normalize_member_name_rejects_unsafe_paths(self):
        unsafe = [
            "../escape.txt",
            "pages/../escape.txt",
            "/absolute.txt",
            "C:/windows.txt",
            "C:\\windows.txt",
            "pages\\page_001\\source.png",
            "./bundle.json",
            "pages//source.png",
            "",
            "nul\x00name",
        ]
        for value in unsafe:
            with self.subTest(value=value):
                with self.assertRaises(BundleValidationError):
                    normalize_member_name(value)

    def test_inspect_zip_rejects_duplicate_normalized_names(self):
        path = self.make_zip([("a.txt", b"one"), ("a.txt", b"two")])
        with self.assertRaisesRegex(BundleValidationError, "duplicate"):
            inspect_zip(path)

    def test_inspect_zip_rejects_symlink(self):
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        path = self.make_zip([("link", info)])
        with self.assertRaisesRegex(BundleValidationError, "symlink"):
            inspect_zip(path)

    def test_inspect_zip_enforces_member_and_total_limits(self):
        member_path = self.make_zip([("big.bin", b"12345")])
        with self.assertRaisesRegex(BundleValidationError, "member size"):
            inspect_zip(member_path, BundleLimits(max_member_size=4, max_total_size=100))

        total_path = self.make_zip([("a.bin", b"123"), ("b.bin", b"456")])
        with self.assertRaisesRegex(BundleValidationError, "total size"):
            inspect_zip(total_path, BundleLimits(max_member_size=10, max_total_size=5))

    def test_safe_extract_writes_only_valid_members(self):
        envelope = json.dumps(self.valid_envelope()).encode("utf-8")
        path = self.make_zip([("bundle.json", envelope), ("pages/page_001/source.png", b"png")])
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "extract"
            extracted = safe_extract(path, destination)
            self.assertEqual(
                {destination / "bundle.json", destination / "pages/page_001/source.png"},
                set(extracted),
            )
            self.assertEqual(b"png", (destination / "pages/page_001/source.png").read_bytes())

    def test_safe_extract_rejects_archive_changed_after_inspection(self):
        path = self.make_zip([("bundle.json", json.dumps(self.valid_envelope()).encode("utf-8"))])
        original_inspect = web_bundle.inspect_zip

        def inspect_then_replace(candidate, limits=None):
            members = original_inspect(candidate, limits)
            with zipfile.ZipFile(candidate, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("bundle.json", b"{}")
                archive.writestr("unexpected.txt", b"changed")
            return members

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            web_bundle, "inspect_zip", side_effect=inspect_then_replace
        ):
            with self.assertRaisesRegex(BundleValidationError, "changed during validation"):
                web_bundle.safe_extract(path, Path(tmp) / "extract")

    def test_load_bundle_envelope_validates_protocol_and_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bundle.json").write_text(json.dumps(self.valid_envelope()), encoding="utf-8")
            envelope = load_bundle_envelope(root, expected_type="handoff")
            self.assertEqual("job-001", envelope["job_id"])
            with self.assertRaisesRegex(BundleValidationError, "bundle type"):
                load_bundle_envelope(root, expected_type="reconstruction")

    def test_load_bundle_envelope_rejects_duplicate_page_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            envelope = self.valid_envelope()
            envelope["pages"].append(dict(envelope["pages"][0]))
            (root / "bundle.json").write_text(json.dumps(envelope), encoding="utf-8")
            with self.assertRaisesRegex(BundleValidationError, "duplicate page"):
                load_bundle_envelope(root)


if __name__ == "__main__":
    unittest.main()
