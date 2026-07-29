#!/usr/bin/env python3
"""CLI surface for local/ChatGPT-Web batch handoffs and revision rounds."""

from __future__ import annotations

import argparse
import json
import os


HELP_FORMATTER = argparse.RawDescriptionHelpFormatter


def _print(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_web_export(args: argparse.Namespace) -> int:
    from export_web_handoff import export_handoff

    return _print(export_handoff(args.run, args.out, instructions_root=args.instructions_root))


def cmd_web_inspect(args: argparse.Namespace) -> int:
    from inspect_web_bundle import inspect_bundle

    return _print(inspect_bundle(args.bundle))


def cmd_web_import(args: argparse.Namespace) -> int:
    from import_web_reconstruction import import_reconstruction

    return _print(import_reconstruction(args.run, args.bundle))


def cmd_web_build(args: argparse.Namespace) -> int:
    from build_web_run import build_web_run

    payload = build_web_run(args.run, finalize=not args.no_finalize)
    _print(payload)
    return 0 if payload["passed"] else 1


def cmd_revision_export(args: argparse.Namespace) -> int:
    from export_web_revision import export_revision

    return _print(export_revision(args.run, args.out, round_number=args.round))


def cmd_revision_apply(args: argparse.Namespace) -> int:
    from apply_web_revision import apply_revision

    return _print(apply_revision(args.run, args.bundle))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=os.environ.get("IMAGE_TO_EDITABLE_PPT_CLI_PROG", "editppt"),
        description="Batch handoff commands between local editppt and ChatGPT Web.",
        formatter_class=HELP_FORMATTER,
        epilog="""Typical workflow:
  editppt prepare deck.pdf
  editppt web export <run> --out handoff.zip
  # Upload handoff.zip to the web Skill and download reconstruction.zip.
  editppt web import <run> reconstruction.zip
  editppt web build <run>
  # When pages fail:
  editppt revision export <run> --out revision.zip
  editppt revision apply <run> revision-result.zip
  editppt web build <run>
""",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    web = sub.add_parser("web", help="Export, inspect, import, and build ChatGPT Web bundles.")
    web_sub = web.add_subparsers(dest="web_command", required=True)

    export = web_sub.add_parser("export", help="Export a prepared run as a web handoff ZIP.")
    export.add_argument("run")
    export.add_argument("--out", required=True)
    export.add_argument("--instructions-root")
    export.set_defaults(func=cmd_web_export)

    inspect = web_sub.add_parser("inspect", help="Inspect a web bundle without importing it.")
    inspect.add_argument("bundle")
    inspect.set_defaults(func=cmd_web_inspect)

    import_command = web_sub.add_parser("import", help="Import a verified reconstruction bundle.")
    import_command.add_argument("run")
    import_command.add_argument("bundle")
    import_command.set_defaults(func=cmd_web_import)

    build = web_sub.add_parser("build", help="Build, render, validate, record, and finalize imported pages.")
    build.add_argument("run")
    build.add_argument("--no-finalize", action="store_true")
    build.set_defaults(func=cmd_web_build)

    revision = sub.add_parser("revision", help="Export failed pages and apply a later web revision result.")
    revision_sub = revision.add_subparsers(dest="revision_command", required=True)

    revision_export = revision_sub.add_parser("export", help="Export failed or unrecorded pages for correction.")
    revision_export.add_argument("run")
    revision_export.add_argument("--out", required=True)
    revision_export.add_argument("--round", type=int)
    revision_export.set_defaults(func=cmd_revision_export)

    revision_apply = revision_sub.add_parser("apply", help="Apply a verified revision-result bundle.")
    revision_apply.add_argument("run")
    revision_apply.add_argument("bundle")
    revision_apply.set_defaults(func=cmd_revision_apply)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
