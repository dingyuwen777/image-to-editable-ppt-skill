#!/usr/bin/env python3
"""Import an untrusted ChatGPT Web reconstruction bundle into a prepared run."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from configure_image_backend import web_artifact_contract
from deck_run_state import (
    load_deck,
    load_jobs,
    read_json,
    resolve_inside,
    run_dir_from_target,
    save_deck,
    write_json,
)
from validate_pptx import normalize_for_validation, page_contract_violations, quality_contract_violations
from web_bundle import (
    BundleValidationError,
    load_bundle_envelope,
    normalize_member_name,
    safe_extract,
    sha256_file,
    utc_now_iso,
)


IMPORT_FILE_NAMES = ("manifest.json", "imagegen-jobs.json", "web_result.json")
DERIVED_FILE_NAMES = (
    "page.pptx",
    "preview.png",
    "split_assets_contact.png",
    "visual_diff.png",
    "visual_metrics.json",
    "validation.json",
    "page_result.json",
)
TARGET_NAMES = (*IMPORT_FILE_NAMES, "web_import.json", "assets", *DERIVED_FILE_NAMES)


def _page_map(deck: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for page in deck.get("pages", []):
        page_id = page.get("page_id")
        if not isinstance(page_id, str) or not page_id:
            raise BundleValidationError("deck contains a page without page_id")
        if page_id in result:
            raise BundleValidationError(f"deck contains duplicate page id: {page_id}")
        result[page_id] = page
    return result


def _job_map(run_dir: Path) -> dict[str, dict]:
    jobs = load_jobs(run_dir)
    result: dict[str, dict] = {}
    for page in jobs.get("pages", []):
        page_id = page.get("page_id")
        if isinstance(page_id, str):
            result[page_id] = page
    return result


def _asset_paths(manifest: dict) -> set[str]:
    paths: set[str] = set()
    images = manifest.get("images", [])
    if not isinstance(images, list):
        raise BundleValidationError("manifest images must be an array")
    for index, image in enumerate(images):
        if not isinstance(image, dict) or not isinstance(image.get("path"), str):
            raise BundleValidationError(f"manifest images[{index}].path is required")
        paths.add(image["path"])

    provenance = manifest.get("asset_provenance", [])
    if provenance is None:
        provenance = []
    if not isinstance(provenance, list):
        raise BundleValidationError("manifest asset_provenance must be an array")
    for index, item in enumerate(provenance):
        if not isinstance(item, dict):
            raise BundleValidationError(f"manifest asset_provenance[{index}] must be an object")
        for field in ("path", "source"):
            value = item.get(field)
            if isinstance(value, str) and value.startswith("assets/"):
                paths.add(value)
    return paths


def _validate_asset_path(value: str) -> str:
    try:
        normalized = normalize_member_name(value)
    except BundleValidationError as exc:
        raise BundleValidationError(f"invalid manifest asset path: {value!r}") from exc
    parts = PurePosixPath(normalized).parts
    if not parts or parts[0] != "assets" or len(parts) < 2:
        raise BundleValidationError(f"manifest asset path must remain under assets/: {value!r}")
    return normalized


def _validate_manifest_contract(manifest: dict, page_id: str) -> None:
    normalized, authoring_violations = normalize_for_validation(manifest)
    violations = (
        authoring_violations
        + page_contract_violations(normalized)
        + quality_contract_violations(manifest)
    )
    if violations:
        summary = "; ".join(
            f"{item.get('field', 'manifest')}: {item.get('reason', item)}"
            for item in violations[:12]
        )
        if len(violations) > 12:
            summary += f"; ... {len(violations) - 12} more"
        raise BundleValidationError(f"manifest contract failed for {page_id}: {summary}")


def _validate_page_payload(extracted_root: Path, page_id: str) -> tuple[dict, Path, dict]:
    incoming = extracted_root / "pages" / page_id
    manifest_path = incoming / "manifest.json"
    jobs_path = incoming / "imagegen-jobs.json"
    if not manifest_path.is_file():
        raise BundleValidationError(f"missing manifest for {page_id}")
    if not jobs_path.is_file():
        raise BundleValidationError(f"missing imagegen-jobs.json for {page_id}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        image_jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleValidationError(f"invalid JSON payload for {page_id}") from exc
    if not isinstance(manifest, dict):
        raise BundleValidationError(f"manifest for {page_id} must be an object")
    if not isinstance(image_jobs, dict):
        raise BundleValidationError(f"imagegen-jobs.json for {page_id} must be an object")

    _validate_manifest_contract(manifest, page_id)
    for raw_path in sorted(_asset_paths(manifest)):
        normalized = _validate_asset_path(raw_path)
        candidate = incoming.joinpath(*PurePosixPath(normalized).parts)
        if not candidate.is_file() or candidate.is_symlink():
            raise BundleValidationError(f"missing asset for {page_id}: {normalized}")
    return manifest, incoming, image_jobs


def _copy_page_to_stage(incoming: Path, stage: Path, metadata: dict) -> None:
    stage.mkdir(parents=True, exist_ok=True)
    for name in IMPORT_FILE_NAMES:
        source = incoming / name
        if source.is_file():
            shutil.copyfile(source, stage / name)
    assets = incoming / "assets"
    if assets.exists():
        if not assets.is_dir() or assets.is_symlink():
            raise BundleValidationError(f"assets must be a regular directory: {assets}")
        shutil.copytree(assets, stage / "assets")
    write_json(stage / "web_import.json", metadata)


def _remove_target(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _backup_targets(page_dir: Path, backup: Path) -> None:
    backup.mkdir(parents=True, exist_ok=True)
    for name in TARGET_NAMES:
        source = page_dir / name
        if source.is_dir() and not source.is_symlink():
            shutil.copytree(source, backup / name)
        elif source.is_file() and not source.is_symlink():
            shutil.copyfile(source, backup / name)


def _replace_targets(page_dir: Path, stage: Path) -> None:
    for name in TARGET_NAMES:
        target = page_dir / name
        source = stage / name
        _remove_target(target)
        if source.is_dir() and not source.is_symlink():
            shutil.copytree(source, target)
        elif source.is_file() and not source.is_symlink():
            shutil.copyfile(source, target)


def _restore_targets(page_dir: Path, backup: Path) -> None:
    for name in TARGET_NAMES:
        target = page_dir / name
        _remove_target(target)
        source = backup / name
        if source.is_dir() and not source.is_symlink():
            shutil.copytree(source, target)
        elif source.is_file() and not source.is_symlink():
            shutil.copyfile(source, target)


def _apply_backend(run_dir: Path, deck: dict) -> None:
    contract = web_artifact_contract()
    deck["image_backend"] = contract
    save_deck(run_dir, deck)
    for page in deck.get("pages", []):
        request_path = resolve_inside(run_dir, page.get("page_request", f"{page['page_dir']}/page_request.json"))
        if request_path.is_file():
            request = read_json(request_path)
            request["image_backend"] = contract
            write_json(request_path, request)


def import_reconstruction(run: str | Path, bundle: str | Path) -> dict:
    run_dir = run_dir_from_target(run)
    bundle = Path(bundle).expanduser().resolve()
    deck = load_deck(run_dir)
    pages_by_id = _page_map(deck)
    jobs_by_id = _job_map(run_dir)
    bundle_sha = sha256_file(bundle)

    with tempfile.TemporaryDirectory(prefix=".web-import-", dir=run_dir) as temporary_name:
        temporary = Path(temporary_name)
        extracted = temporary / "extracted"
        safe_extract(bundle, extracted)
        envelope = load_bundle_envelope(extracted, expected_type="reconstruction")
        if envelope["job_id"] != deck.get("run_id"):
            raise BundleValidationError(
                f"bundle job id mismatch: {envelope['job_id']!r} != {deck.get('run_id')!r}"
            )

        staged_pages: dict[str, Path] = {}
        for entry in envelope.get("pages", []):
            page_id = entry["page_id"]
            if page_id not in pages_by_id:
                raise BundleValidationError(f"bundle page is not part of this run: {page_id}")
            job = jobs_by_id.get(page_id)
            if job is None:
                raise BundleValidationError(f"page job is missing for reconstruction import: {page_id}")
            if job.get("status") != "pending":
                raise BundleValidationError(
                    f"initial reconstruction import requires pending page {page_id}; "
                    f"current status is {job.get('status')!r}. Use `editppt revision export/apply` after page processing starts."
                )
            page = pages_by_id[page_id]
            source = resolve_inside(run_dir, page["source_image"])
            actual_hash = sha256_file(source)
            if entry["source_sha256"] != actual_hash:
                raise BundleValidationError(
                    f"source hash mismatch for {page_id}: {entry['source_sha256']} != {actual_hash}"
                )
            _manifest, incoming, _image_jobs = _validate_page_payload(extracted, page_id)
            stage = temporary / "stage" / page_id
            metadata = {
                "schema_version": 1,
                "bundle_type": "reconstruction",
                "bundle_sha256": bundle_sha,
                "job_id": deck["run_id"],
                "page_id": page_id,
                "source_sha256": actual_hash,
                "imported_at": utc_now_iso(),
                "backend": "web-artifact",
            }
            _copy_page_to_stage(incoming, stage, metadata)
            staged_pages[page_id] = stage

        if not staged_pages:
            raise BundleValidationError("reconstruction bundle contains no pages")

        applied: list[tuple[Path, Path]] = []
        deck_backup = (run_dir / "deck_manifest.json").read_bytes()
        request_backups: dict[Path, bytes] = {}
        try:
            for page_id, stage in staged_pages.items():
                page_dir = resolve_inside(run_dir, pages_by_id[page_id]["page_dir"])
                backup = temporary / "backup" / page_id
                _backup_targets(page_dir, backup)
                applied.append((page_dir, backup))
                _replace_targets(page_dir, stage)
            for page in deck.get("pages", []):
                request_path = resolve_inside(
                    run_dir, page.get("page_request", f"{page['page_dir']}/page_request.json")
                )
                if request_path.is_file():
                    request_backups[request_path] = request_path.read_bytes()
            _apply_backend(run_dir, deck)
        except Exception:
            for page_dir, backup in reversed(applied):
                _restore_targets(page_dir, backup)
            (run_dir / "deck_manifest.json").write_bytes(deck_backup)
            for path, payload in request_backups.items():
                path.write_bytes(payload)
            raise

    return {
        "bundle": str(bundle),
        "bundle_sha256": bundle_sha,
        "job_id": deck["run_id"],
        "imported_pages": sorted(staged_pages),
        "image_backend": "web-artifact",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a verified ChatGPT Web reconstruction bundle.")
    parser.add_argument("run", help="Run directory or deck_manifest.json path.")
    parser.add_argument("bundle", help="Reconstruction ZIP bundle.")
    args = parser.parse_args()
    result = import_reconstruction(args.run, args.bundle)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
