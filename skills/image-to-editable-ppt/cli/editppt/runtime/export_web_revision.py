#!/usr/bin/env python3
"""Export only failed/unrecorded pages for a later ChatGPT Web correction round."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from deck_run_state import load_deck, load_jobs, read_json, resolve_inside, run_dir_from_target, write_json
from web_bundle import json_bytes, sha256_file, utc_now_iso, write_zip_atomic


def _next_round(run_dir: Path) -> int:
    revisions = run_dir / "revisions"
    found = []
    if revisions.is_dir():
        for child in revisions.iterdir():
            if child.is_dir() and child.name.startswith("round-"):
                try:
                    found.append(int(child.name.split("-", 1)[1]))
                except ValueError:
                    continue
    return max(found, default=0) + 1


def _validation_passed(run_dir: Path, page: dict) -> bool:
    path = resolve_inside(run_dir, page.get("validation", f"{page['page_dir']}/validation.json"))
    if not path.is_file():
        return False
    try:
        return read_json(path).get("passed") is True
    except Exception:
        return False


def _needs_revision(run_dir: Path, page: dict) -> bool:
    result = page.get("result") or {}
    if page.get("status") in {"recorded", "accepted"} and result.get("validation_passed") is True:
        return False
    return not _validation_passed(run_dir, page)


def _correction_request(page_id: str, page_dir: Path, page: dict, round_number: int) -> dict:
    validation = read_json(page_dir / "validation.json", default={})
    page_result = read_json(page_dir / "page_result.json", default={})
    errors = []
    errors.extend(page_result.get("errors", []) if isinstance(page_result.get("errors"), list) else [])
    errors.extend(validation.get("warnings", []) if isinstance(validation.get("warnings"), list) else [])
    for field in (
        "page_contract_violations",
        "missing_required_text",
        "missing_manifest_images",
        "missing_asset_provenance",
        "invalid_asset_provenance",
        "media_hash_mismatches",
    ):
        value = validation.get(field)
        if value:
            errors.append({"field": field, "details": value})
    return {
        "schema_version": 1,
        "page_id": page_id,
        "round": round_number,
        "current_status": page.get("status"),
        "goal": "Correct semantic/visual reconstruction issues while preserving source-pixel authoring, editability, asset provenance, and all quality contracts.",
        "errors": errors,
        "required_output": {
            "manifest": "manifest.json",
            "imagegen_jobs": "imagegen-jobs.json",
            "assets": "assets/",
        },
    }


def export_revision(
    run: str | Path,
    out: str | Path,
    round_number: int | None = None,
) -> dict:
    run_dir = run_dir_from_target(run)
    deck = load_deck(run_dir)
    jobs = load_jobs(run_dir)
    round_number = round_number or _next_round(run_dir)
    if round_number < 1:
        raise ValueError("round number must be >= 1")

    members: dict[str, bytes | Path] = {}
    envelope_pages = []
    exported_pages = []
    for page in sorted(jobs.get("pages", []), key=lambda item: int(item.get("page_index", 0))):
        if not _needs_revision(run_dir, page):
            continue
        page_id = page["page_id"]
        page_dir = resolve_inside(run_dir, page["page_dir"])
        source = resolve_inside(run_dir, page.get("source", f"{page['page_dir']}/source.png"))
        if not source.is_file():
            raise FileNotFoundError(source)
        prefix = f"pages/{page_id}"
        members[f"{prefix}/source.png"] = source
        for source_name, bundle_name in (
            ("manifest.json", "current-manifest.json"),
            ("preview.png", "preview.png"),
            ("split_assets_contact.png", "split_assets_contact.png"),
            ("validation.json", "validation.json"),
            ("page_result.json", "page_result.json"),
            ("text_hints.json", "text_hints.json"),
            ("text_hints.png", "text_hints.png"),
            ("imagegen-jobs.json", "current-imagegen-jobs.json"),
        ):
            path = page_dir / source_name
            if path.is_file():
                members[f"{prefix}/{bundle_name}"] = path
        assets = page_dir / "assets"
        if assets.is_dir():
            for asset in sorted(assets.rglob("*")):
                if asset.is_file() and not asset.is_symlink():
                    relative = asset.relative_to(page_dir).as_posix()
                    members[f"{prefix}/{relative}"] = asset
        correction = _correction_request(page_id, page_dir, page, round_number)
        members[f"{prefix}/correction-request.json"] = json_bytes(correction)
        source_hash = sha256_file(source)
        envelope_pages.append(
            {
                "page_id": page_id,
                "page_index": page.get("page_index"),
                "source_sha256": source_hash,
                "correction_request": f"{prefix}/correction-request.json",
            }
        )
        exported_pages.append(page_id)

    if not exported_pages:
        raise ValueError("no pages need revision")

    envelope = {
        "protocol": "editppt-web-bundle",
        "version": 1,
        "bundle_type": "revision-request",
        "job_id": deck["run_id"],
        "created_at": utc_now_iso(),
        "round": round_number,
        "pages": envelope_pages,
        "output_contract": {
            "bundle_type": "revision-result",
            "replacement_mode": "full-page-manifest-and-assets",
        },
    }
    members["bundle.json"] = json_bytes(envelope)
    out_path = write_zip_atomic(out, members)

    history = run_dir / "revisions" / f"round-{round_number:02d}"
    history.mkdir(parents=True, exist_ok=True)
    archived_bundle = history / "revision-request.zip"
    if out_path.resolve() != archived_bundle.resolve():
        shutil.copyfile(out_path, archived_bundle)
    write_json(
        history / "request.json",
        {
            "schema_version": 1,
            "round": round_number,
            "bundle": str(archived_bundle),
            "bundle_sha256": sha256_file(out_path),
            "pages": exported_pages,
            "created_at": envelope["created_at"],
        },
    )
    return {
        "bundle": str(out_path),
        "bundle_sha256": sha256_file(out_path),
        "job_id": deck["run_id"],
        "round": round_number,
        "pages": exported_pages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export failed pages for a ChatGPT Web revision round.")
    parser.add_argument("run")
    parser.add_argument("--out", required=True)
    parser.add_argument("--round", type=int)
    args = parser.parse_args()
    print(json.dumps(export_revision(args.run, args.out, args.round), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
