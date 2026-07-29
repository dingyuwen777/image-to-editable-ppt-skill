import argparse
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "skills/image-to-editable-ppt/cli/editppt/runtime"
sys.path.insert(0, str(RUNTIME_DIR))

from configure_image_backend import backend_contract, web_artifact_contract  # noqa: E402
from main import build_parser  # noqa: E402


class WebArtifactBackendTest(unittest.TestCase):
    def test_web_artifact_contract_requires_no_api_and_disables_fallback(self):
        contract = web_artifact_contract()
        self.assertEqual("web-artifact", contract["backend_id"])
        self.assertFalse(contract["requires_openai_api_key"])
        self.assertEqual("reconstruction-bundle", contract["asset_delivery"])
        self.assertFalse(contract["fallback_policy"]["allowed"])
        self.assertIsNone(contract["model"])

    def test_backend_contract_returns_fixed_web_contract(self):
        args = argparse.Namespace(
            backend_id="web-artifact",
            tool_name=None,
            tool_call=None,
            fallback_command=None,
            runtime_home="~/.editppt",
            model="gpt-image-2",
            input_context_policy=None,
        )
        self.assertEqual(web_artifact_contract(), backend_contract(args))

    def test_cli_accepts_web_artifact_backend_for_prepare_and_run_backend(self):
        parser = build_parser()
        prepare = parser.parse_args(["prepare", "slide.png", "--image-backend", "web-artifact"])
        self.assertEqual("web-artifact", prepare.image_backend)
        backend = parser.parse_args(["run", "backend", "run-dir", "--mode", "web-artifact"])
        self.assertEqual("web-artifact", backend.mode)


if __name__ == "__main__":
    unittest.main()
