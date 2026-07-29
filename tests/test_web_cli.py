import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "skills/image-to-editable-ppt/cli/editppt/runtime"
sys.path.insert(0, str(RUNTIME_DIR))

from web_cli import build_parser  # noqa: E402


class WebCliTest(unittest.TestCase):
    def test_web_export_parser(self):
        args = build_parser().parse_args(["web", "export", "run", "--out", "handoff.zip"])
        self.assertEqual("web", args.command)
        self.assertEqual("export", args.web_command)
        self.assertEqual("handoff.zip", args.out)

    def test_web_import_parser(self):
        args = build_parser().parse_args(["web", "import", "run", "reconstruction.zip"])
        self.assertEqual("import", args.web_command)
        self.assertEqual("reconstruction.zip", args.bundle)

    def test_web_build_parser(self):
        args = build_parser().parse_args(["web", "build", "run"])
        self.assertEqual("build", args.web_command)

    def test_revision_commands(self):
        export_args = build_parser().parse_args(["revision", "export", "run", "--out", "revision.zip"])
        self.assertEqual("export", export_args.revision_command)
        apply_args = build_parser().parse_args(["revision", "apply", "run", "result.zip"])
        self.assertEqual("apply", apply_args.revision_command)


if __name__ == "__main__":
    unittest.main()
