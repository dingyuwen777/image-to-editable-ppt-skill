from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


WEB_HELP = """
ChatGPT Web batch commands:
  editppt web export <run> --out handoff.zip
  editppt web inspect <bundle.zip>
  editppt web import <run> <reconstruction.zip>
  editppt web build <run>
  editppt revision export <run> --out revision.zip
  editppt revision apply <run> <revision-result.zip>

Run `editppt web --help` or `editppt revision --help` for details.
"""


def main() -> None:
    command_name = Path(sys.argv[0]).name or "editppt"
    if command_name in {"cli.py", "__main__.py"}:
        command_name = "editppt"
    runtime_dir = Path(__file__).resolve().parent / "runtime"
    is_web_command = len(sys.argv) > 1 and sys.argv[1] in {"web", "revision"}
    top_level_help = len(sys.argv) == 2 and sys.argv[1] in {"-h", "--help"}
    script = runtime_dir / ("web_cli.py" if is_web_command else "main.py")
    if not script.exists():
        raise RuntimeError(f"runtime entrypoint not found: {script}")

    os.environ.setdefault("IMAGE_TO_EDITABLE_PPT_CLI_PROG", command_name)
    sys.path.insert(0, str(runtime_dir))
    sys.argv = [command_name, *sys.argv[1:]]
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        if top_level_help and exc.code in (None, 0):
            print(WEB_HELP.rstrip())
        raise


if __name__ == "__main__":
    main()
