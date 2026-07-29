#!/usr/bin/env python3
"""Export a prepared editppt run as a sanitized ChatGPT Web handoff bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from deck_run_state import load_deck, read_json, resolve_inside, run_dir_from_target
from web_bundle import json_bytes, sha256_bytes, sha256_file, utc_now_iso, write_zip_atomic


INSTRUCTION_FILES = (
    "web-batch-worker.md",
    "page-decision-tree.md",
    "manifest-schema.md",
    "web-bundle-protocol.md",
)


def _portable_deck(deck: dict) -> dict:
    pages = []
    for page in deck.get("pages", []):
        page_id = page["page_id"]
        page_dir = f"pages/{page_id}"
        pages.append(
            {
                "page_id": page_id,
                "page_index": page.get("page_index"),
                "source_page": page.get("source_page"),
                "source_image": f"{page_dir}/source.png",
                "page_dir": page_dir,
                "page_request": f"{page_dir}/page_request.json",
                "manifest": f"{page_dir}/manifest.json",
                "validation": f"{page_dir}/validation.json",
                "input": page.get("input"),
            }
        )
    return {
        "schema_version": deck.get("schema_version", 1),
        "run_id": deck["run_id"],
        "input_type": deck.get("input_type"),
        "page_count": len(pages),
        "inputs": [Path(value).name for value in deck.get("inputs", [])],
        "slide": deck.get("slide"),
        "output": Path(deck.get("output", "final/deck_edited.pptx")).name,
        "notes_manifest": "notes_manifest.json",
        "max_concurrent_pages": deck.get("max_concurrent_pages"),
        "image_backend": {
            "backend_id": "web-artifact",
            "requires_openai_api_key": False,
            "asset_delivery": "reconstruction-bundle",
            "fallback_allowed": False,
        },
        "pages": pages,
    }


def _portable_notes(notes: dict) -> dict:
    portable = []
    for note in notes.get("notes", []):
        portable.append(
            {
                key: note[key]
                for key in (
                    "page_index",
                    "text",
                    "text_sha256",
                    "source_slide",
                    "source_notes_part",
                )
                if key in note
            }
        )
    source = notes.get("source")
    return {"source": Path(source).name if source else None, "notes": portable}


def _portable_page_request(request: dict, page_id: str) -> dict:
    page_dir = f"pages/{page_id}"
    portable = {
        key: request[key]
        for key in (
            "schema_version",
            "run_id",
            "page_id",
            "page_index",
            "source_size_px",
            "slide",
            "content_box",
            "max_concurrent_pages",
            "image_backend",
        )
        if key in request
    }
    portable.update(
        {
            "page_dir": page_dir,
            "source_image": f"{page_dir}/source.png",
            "required_outputs": {
                "manifest": f"{page_dir}/manifest.json",
                "imagegen_jobs": f"{page_dir}/imagegen-jobs.json",
                "assets": f"{page_dir}/assets/",
            },
        }
    )
    return portable


def _default_instruction_paths() -> dict[str, Path]:
    skill_root = Path(__file__).resolve().parents[3]
    candidates = {
        "web-batch-worker.md": skill_root / "prompts/web-batch-worker.md",
        "page-decision-tree.md": skill_root / "references/page-decision-tree.md",
        "manifest-schema.md": skill_root / "references/manifest-schema.md",
        "web-bundle-protocol.md": skill_root / "references/web-bundle-protocol.md",
    }
    return candidates


def _instruction_paths(instructions_root: str | Path | None) -> dict[str, Path]:
    if instructions_root is None:
        return _default_instruction_paths()
    root = Path(instructions_root)
    return {name: root / name for name in INSTRUCTION_FILES}


def export_handoff(
    run: str | Path,
    out: str | Path,
    instructions_root: str | Path | None = None,
) -> dict:
    run_dir = run_dir_from_target(run)
    deck = load_deck(run_dir)
    notes_path = run_dir / deck.get("notes_manifest", "notes_manifest.json")
    notes = read_json(notes_path, default={"source": None, "notes": []})

    members: dict[str, bytes | Path] = {}
    portable_deck = _portable_deck(deck)
    members["deck_manifest.json"] = json_bytes(portable_deck)
    members["notes_manifest.json"] = json_bytes(_portable_notes(notes))

    envelope_pages = []
    for page in sorted(deck.get("pages", []), key=lambda item: int(item.get("page_index", 0))):
        page_id = page["page_id"]
        page_dir = resolve_inside(run_dir, page["page_dir"])
        source = resolve_inside(run_dir, page["source_image"])
        if not source.is_file():
            raise FileNotFoundError(source)
        request_path = page_dir / "page_request.json"
        if not request_path.is_file():
            raise FileNotFoundError(request_path)
        request = read_json(request_path)

        bundle_page_dir = f"pages/{page_id}"
        members[f"{bundle_page_dir}/source.png"] = source
        members[f"{bundle_page_dir}/page_request.json"] = json_bytes(
            _portable_page_request(request, page_id)
        )
        for optional in ("text_hints.json", "text_hints.png"):
            path = page_dir / optional
            if path.is_file():
                members[f"{bundle_page_dir}/{optional}"] = path

        envelope_pages.append(
            {
                "page_id": page_id,
                "page_index": page.get("page_index"),
                "source_path": f"{bundle_page_dir}/source.png",
                "source_sha256": sha256_file(source),
                "page_request": f"{bundle_page_dir}/page_request.json",
                "text_hints": f"{bundle_page_dir}/text_hints.json"
                if (page_dir / "text_hints.json").is_file()
                else None,
                "text_hints_overlay": f"{bundle_page_dir}/text_hints.png"
                if (page_dir / "text_hints.png").is_file()
                else None,
            }
        )

    instructions = _instruction_paths(instructions_root)
    for name, path in instructions.items():
        if not path.is_file():
            raise FileNotFoundError(path)
        members[f"instructions/{name}"] = path

    member_hashes = {}
    for name, source in members.items():
        payload = source.read_bytes() if isinstance(source, Path) else bytes(source)
        member_hashes[name] = sha256_bytes(payload)

    envelope = {
        "protocol": "editppt-web-bundle",
        "version": 1,
        "bundle_type": "handoff",
        "job_id": deck["run_id"],
        "created_at": utc_now_iso(),
        "pages": envelope_pages,
        "members": member_hashes,
        "instructions": [f"instructions/{name}" for name in INSTRUCTION_FILES],
        "output_contract": {
            "bundle_type": "reconstruction",
            "required_page_files": ["manifest.json", "imagegen-jobs.json"],
            "asset_root": "assets/",
            "paths": "POSIX-relative",
        },
    }
    members["bundle.json"] = json_bytes(envelope)
    out_path = write_zip_atomic(out, members)
    return {
        "bundle": str(out_path),
        "bundle_type": "handoff",
        "job_id": deck["run_id"],
        "pages": len(envelope_pages),
        "sha256": sha256_file(out_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a prepared run as a ChatGPT Web handoff ZIP.")
    parser.add_argument("run", help="Run directory or deck_manifest.json path.")
    parser.add_argument("--out", required=True, help="Output handoff ZIP path.")
    parser.add_argument("--instructions-root", help="Override instruction source directory for testing or customization.")
    args = parser.parse_args()
    result = export_handoff(args.run, args.out, instructions_root=args.instructions_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
