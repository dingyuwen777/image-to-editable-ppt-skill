#!/usr/bin/env python3
"""Inspect an editppt web bundle without modifying a run."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from web_bundle import inspect_zip, load_bundle_envelope, safe_extract, sha256_file


def inspect_bundle(bundle: str | Path) -> dict:
    bundle = Path(bundle).expanduser().resolve()
    members = inspect_zip(bundle)
    with tempfile.TemporaryDirectory(prefix="editppt-web-inspect-") as tmp:
        root = Path(tmp)
        safe_extract(bundle, root)
        envelope = load_bundle_envelope(root)
    return {
        "bundle": str(bundle),
        "sha256": sha256_file(bundle),
        "bundle_type": envelope["bundle_type"],
        "job_id": envelope["job_id"],
        "pages": envelope["pages"],
        "member_count": len(members),
        "uncompressed_size": sum(member.size for member in members),
        "members": [member.name for member in members],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a web handoff/reconstruction/revision ZIP.")
    parser.add_argument("bundle")
    args = parser.parse_args()
    print(json.dumps(inspect_bundle(args.bundle), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
