#!/usr/bin/env python3
"""Apply a verified ChatGPT Web revision-result bundle and reset changed pages."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from deck_run_state import (
    load_deck,
    load_jobs,
    resolve_inside,
    run_dir_from_target,
    save_deck,
    save_jobs,
    set_run_status,
)
from import_web_reconstruction import (
    _apply_backend,
    _copy_page_to_stage,
    _page_map,
    _replace_targets,
    _validate_page_payload,
)
from web_bundle import (
    BundleValidationError,
    load_bundle_envelope,
    safe_extract,
    sha256_file,
    utc_now_iso,
)


ARCHIVE_NAMES = (
    "manifest.json",
    "imagegen-jobs.json",
    "web_import.json",
    "web_result.json",
    "page.pptx",
    "preview.png",
    "split_assets_contact.png",
    "validation.json",
    "page_result.json",
    "assets",
)
DERIVED_NAMES = (
    "page.pptx",
    "preview.png",
    "split_assets_contact.png",
    "validation.json",
    "page_result.json",
)


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _archive_page(page_dir: Path, archive: Path) -> None:
    archive.mkdir(parents=True, exist_ok=True)
    for name in ARCHIVE_NAMES:
        source = page_dir / name
        if source.is_dir() and not source.is_symlink():
            shutil.copytree(source, archive / name)
        elif source.is_file() and not source.is_symlink():
            shutil.copyfile(source, archive / name)


def _restore_page_snapshot(page_dir: Path, archive: Path) -> None:
    for name in ARCHIVE_NAMES:
        _remove_path(page_dir / name)
        source = archive / name
        if source.is_dir() and not source.is_symlink():
            shutil.copytree(source, page_dir / name)
        elif source.is_file() and not source.is_symlink():
            shutil.copyfile(source, page_dir / name)


def _remove_derived_page_outputs(page_dir: Path) -> None:
    for name in DERIVED_NAMES:
        _remove_path(page_dir / name)


def _reset_jobs(run_dir: Path, applied_pages: set[str]) -> None:
    jobs = load_jobs(run_dir)
    for page in jobs.get("pages", []):
        if page.get("page_id") not in applied_pages:
            continue
        page["status"] = "pending"
        page["dispatch"] = None
        page["result"] = None
        page["accepted"] = False
        page.pop("accepted_at", None)
    jobs["run_status"] = "revision_applied"
    save_jobs(run_dir, jobs)


def _snapshot_final(run_dir: Path, deck: dict, destination: Path) -> bool:
    final_dir = run_dir / "final"
    if final_dir.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copytree(final_dir, destination / "final")
        return True
    output = Path(deck.get("output", "final/deck_edited.pptx"))
    if not output.is_absolute():
        output = run_dir / output
    if output.is_file():
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(output, destination / output.name)
        return True
    return False


def _remove_final(run_dir: Path, deck: dict) -> None:
    final_dir = run_dir / "final"
    if final_dir.is_dir():
        shutil.rmtree(final_dir)
        return
    output = Path(deck.get("output", "final/deck_edited.pptx"))
    if not output.is_absolute():
        output = run_dir / output
    output.unlink(missing_ok=True)


def _restore_final(run_dir: Path, snapshot: Path) -> None:
    archived_dir = snapshot / "final"
    if archived_dir.is_dir():
        _remove_path(run_dir / "final")
        shutil.copytree(archived_dir, run_dir / "final")
        return
    files = [path for path in snapshot.iterdir() if path.is_file()] if snapshot.is_dir() else []
    if files:
        final_dir = run_dir / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        for path in files:
            shutil.copyfile(path, final_dir / path.name)


def apply_revision(run: str | Path, bundle: str | Path) -> dict:
    run_dir = run_dir_from_target(run)
    bundle = Path(bundle).expanduser().resolve()
    deck = load_deck(run_dir)
    pages_by_id = _page_map(deck)
    bundle_sha = sha256_file(bundle)

    with tempfile.TemporaryDirectory(prefix=".web-revision-", dir=run_dir) as temporary_name:
        temporary = Path(temporary_name)
        extracted = temporary / "extracted"
        safe_extract(bundle, extracted)
        envelope = load_bundle_envelope(extracted, expected_type="revision-result")
        if envelope["job_id"] != deck.get("run_id"):
            raise BundleValidationError(
                f"bundle job id mismatch: {envelope['job_id']!r} != {deck.get('run_id')!r}"
            )
        round_number = envelope.get("round")
        if not isinstance(round_number, int) or round_number < 1:
            raise BundleValidationError("revision-result bundle requires integer round >= 1")
        history_dir = run_dir / "revisions" / f"round-{round_number:02d}"
        history_target = history_dir / "before"
        if history_target.exists():
            raise BundleValidationError(f"revision round history already exists: {history_target}")

        staged_pages: dict[str, Path] = {}
        archive_root = temporary / "before"
        for entry in envelope.get("pages", []):
            page_id = entry["page_id"]
            if page_id not in pages_by_id:
                raise BundleValidationError(f"revision page is not part of this run: {page_id}")
            page = pages_by_id[page_id]
            source = resolve_inside(run_dir, page["source_image"])
            actual_hash = sha256_file(source)
            if entry["source_sha256"] != actual_hash:
                raise BundleValidationError(
                    f"source hash mismatch for {page_id}: {entry['source_sha256']} != {actual_hash}"
                )
            _manifest, incoming, _jobs = _validate_page_payload(extracted, page_id)
            stage = temporary / "stage" / page_id
            metadata = {
                "schema_version": 1,
                "bundle_type": "revision-result",
                "bundle_sha256": bundle_sha,
                "job_id": deck["run_id"],
                "page_id": page_id,
                "round": round_number,
                "source_sha256": actual_hash,
                "imported_at": utc_now_iso(),
                "backend": "web-artifact",
            }
            _copy_page_to_stage(incoming, stage, metadata)
            staged_pages[page_id] = stage
            _archive_page(resolve_inside(run_dir, page["page_dir"]), archive_root / page_id)

        if not staged_pages:
            raise BundleValidationError("revision-result bundle contains no pages")

        final_snapshot = archive_root / "deck"
        had_final = _snapshot_final(run_dir, deck, final_snapshot)
        deck_backup = (run_dir / "deck_manifest.json").read_bytes()
        jobs_backup = (run_dir / "page_jobs.json").read_bytes()
        state_path = run_dir / "run_state.json"
        state_backup = state_path.read_bytes() if state_path.is_file() else None
        request_backups: dict[Path, bytes] = {}
        for page in deck.get("pages", []):
            request_path = resolve_inside(
                run_dir, page.get("page_request", f"{page['page_dir']}/page_request.json")
            )
            if request_path.is_file():
                request_backups[request_path] = request_path.read_bytes()

        applied_page_dirs: list[tuple[Path, Path]] = []
        try:
            for page_id, stage in staged_pages.items():
                page_dir = resolve_inside(run_dir, pages_by_id[page_id]["page_dir"])
                backup = archive_root / page_id
                _replace_targets(page_dir, stage)
                _remove_derived_page_outputs(page_dir)
                applied_page_dirs.append((page_dir, backup))

            _apply_backend(run_dir, deck)
            deck.pop("completed_at", None)
            save_deck(run_dir, deck)
            _reset_jobs(run_dir, set(staged_pages))
            set_run_status(run_dir, "revision_applied", f"applied web revision round {round_number}")
            _remove_final(run_dir, deck)

            history_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(archive_root, history_target)
            shutil.copyfile(bundle, history_dir / "revision-result.zip")
            (history_dir / "result.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "round": round_number,
                        "bundle_sha256": bundle_sha,
                        "pages": sorted(staged_pages),
                        "applied_at": utc_now_iso(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        except Exception:
            for page_dir, backup in reversed(applied_page_dirs):
                _restore_page_snapshot(page_dir, backup)
            (run_dir / "deck_manifest.json").write_bytes(deck_backup)
            (run_dir / "page_jobs.json").write_bytes(jobs_backup)
            for path, payload in request_backups.items():
                path.write_bytes(payload)
            if state_backup is None:
                state_path.unlink(missing_ok=True)
            else:
                state_path.write_bytes(state_backup)
            if had_final:
                _restore_final(run_dir, final_snapshot)
            if history_dir.exists():
                shutil.rmtree(history_dir)
            raise

    return {
        "bundle": str(bundle),
        "bundle_sha256": bundle_sha,
        "job_id": deck["run_id"],
        "round": round_number,
        "applied_pages": sorted(staged_pages),
        "next_command": f"editppt web build {run_dir}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply a verified ChatGPT Web revision result bundle.")
    parser.add_argument("run")
    parser.add_argument("bundle")
    args = parser.parse_args()
    print(json.dumps(apply_revision(args.run, args.bundle), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
