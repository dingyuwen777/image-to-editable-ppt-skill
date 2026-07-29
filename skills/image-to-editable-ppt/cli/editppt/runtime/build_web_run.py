#!/usr/bin/env python3
"""Build, render, compare, validate, record, and finalize imported web reconstruction pages."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from deck_run_state import (
    load_deck,
    load_jobs,
    now_iso,
    page_dir_for,
    run_dir_from_target,
    save_jobs,
    set_run_status,
    sha256_file,
    update_jobs_run_status,
    write_json,
)


SCRIPT_DIR = Path(__file__).resolve().parent
WEB_AGENT_ID = "web-batch"


def _run_script(name: str, args: list[str | Path]) -> subprocess.CompletedProcess:
    command = [sys.executable, str(SCRIPT_DIR / name), *[str(value) for value in args]]
    return subprocess.run(command, text=True, capture_output=True)


def _dispatch_for_web(run_dir: Path, jobs: dict, page: dict) -> None:
    status = page.get("status")
    if status == "pending":
        page_dir = page_dir_for(run_dir, page)
        import_metadata = page_dir / "web_import.json"
        if not import_metadata.is_file():
            raise FileNotFoundError(f"Missing web_import.json for {page['page_id']}: {import_metadata}")
        request = run_dir / page["page_request"]
        if not request.is_file():
            raise FileNotFoundError(f"Missing page_request.json for {page['page_id']}: {request}")
        page["dispatch"] = {
            "agent_id": WEB_AGENT_ID,
            "agent_nickname": "ChatGPT Web batch reconstruction",
            "prompt": str(import_metadata.relative_to(run_dir).as_posix()),
            "prompt_sha256": sha256_file(import_metadata),
            "page_request_sha256": sha256_file(request),
            "dispatched_at": now_iso(),
            "execution_mode": "web-batch",
        }
        page["status"] = "dispatched"
        update_jobs_run_status(jobs)
        save_jobs(run_dir, jobs)
        return
    if status == "dispatched":
        agent_id = (page.get("dispatch") or {}).get("agent_id")
        if agent_id != WEB_AGENT_ID:
            raise RuntimeError(
                f"{page['page_id']} is already dispatched to {agent_id!r}; refusing to replace an active worker"
            )
        return
    if status in {"recorded", "accepted"}:
        return
    raise RuntimeError(f"unsupported page status for web build: {page['page_id']}={status}")


def _page_result_payload(status: str, errors: list[str] | None = None) -> dict:
    return {
        "schema_version": 1,
        "status": status,
        "page_manifest": "manifest.json",
        "imagegen_jobs": "imagegen-jobs.json",
        "page_pptx": "page.pptx",
        "preview": "preview.png",
        "contact_sheet": "split_assets_contact.png",
        "visual_diff": "visual_diff.png",
        "visual_metrics": "visual_metrics.json",
        "validation": "validation.json",
        "page_result": "page_result.json",
        "errors": errors or [],
    }


def _ensure_failed_validation(page_dir: Path, errors: list[str]) -> None:
    validation = page_dir / "validation.json"
    if validation.is_file():
        try:
            payload = json.loads(validation.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
    else:
        payload = {}
    payload["passed"] = False
    payload.setdefault("warnings", [])
    payload["warnings"].extend(errors)
    write_json(validation, payload)


def _process_page(run_dir: Path, jobs: dict, page: dict) -> tuple[bool, list[str]]:
    page_id = page["page_id"]
    page_dir = page_dir_for(run_dir, page)
    if page.get("status") == "accepted":
        return True, []
    if page.get("status") == "recorded":
        previous = page.get("result") or {}
        if previous.get("validation_passed") is True:
            return True, []

    _dispatch_for_web(run_dir, jobs, page)
    errors: list[str] = []

    build = _run_script(
        "build_pptx_from_manifest.py",
        [page_dir / "manifest.json", "--out", page_dir / "page.pptx"],
    )
    if build.returncode != 0:
        errors.append((build.stdout + build.stderr).strip() or "page build failed")

    if not errors:
        preview = _run_script(
            "cross_platform_preview.py",
            [page_dir / "manifest.json", "--out", page_dir / "preview.png"],
        )
        if preview.returncode != 0:
            errors.append((preview.stdout + preview.stderr).strip() or "page preview failed")

    if not errors:
        contact = _run_script("make_page_contact_sheet.py", [page_dir])
        if contact.returncode != 0:
            errors.append((contact.stdout + contact.stderr).strip() or "contact sheet failed")

    if not errors:
        visual_diff = _run_script("make_visual_diff.py", [page_dir])
        if visual_diff.returncode != 0:
            errors.append((visual_diff.stdout + visual_diff.stderr).strip() or "visual diff failed")

    if not errors:
        validation = _run_script(
            "validate_pptx.py",
            [page_dir / "page.pptx", "--manifest", page_dir / "manifest.json", "--report", page_dir / "validation.json"],
        )
        if validation.returncode != 0:
            errors.append((validation.stdout + validation.stderr).strip() or "page validation failed")

    if errors:
        _ensure_failed_validation(page_dir, errors)
        write_json(page_dir / "page_result.json", _page_result_payload("failed", errors))
        return False, errors

    write_json(page_dir / "page_result.json", _page_result_payload("passed"))
    record = _run_script(
        "record_page_result.py",
        [run_dir, "--page", page_id, "--agent-id", WEB_AGENT_ID, "--page-result", "page_result.json"],
    )
    if record.returncode != 0:
        errors.append((record.stdout + record.stderr).strip() or "page record failed")
        _ensure_failed_validation(page_dir, errors)
        write_json(page_dir / "page_result.json", _page_result_payload("failed", errors))
        return False, errors
    return True, []


def build_web_run(run: str | Path, finalize: bool = True) -> dict:
    run_dir = run_dir_from_target(run)
    deck = load_deck(run_dir)
    jobs = load_jobs(run_dir)
    recorded_pages: list[str] = []
    failed_pages: list[dict] = []

    for page in sorted(jobs.get("pages", []), key=lambda item: int(item.get("page_index", 0))):
        try:
            passed, errors = _process_page(run_dir, jobs, page)
        except Exception as exc:
            passed, errors = False, [str(exc)]
            page_dir = page_dir_for(run_dir, page)
            _ensure_failed_validation(page_dir, errors)
            write_json(page_dir / "page_result.json", _page_result_payload("failed", errors))
        jobs = load_jobs(run_dir)
        page = next(item for item in jobs.get("pages", []) if item.get("page_id") == page["page_id"])
        if passed:
            recorded_pages.append(page["page_id"])
        else:
            failed_pages.append(
                {
                    "page_id": page["page_id"],
                    "status": page.get("status"),
                    "errors": errors,
                    "validation": str(page_dir_for(run_dir, page) / "validation.json"),
                }
            )

    finalized = False
    final_output = None
    if not failed_pages and finalize:
        final = _run_script("finalize_deck_run.py", [run_dir])
        if final.returncode != 0:
            failed_pages.append(
                {
                    "page_id": "deck",
                    "status": "finalize-failed",
                    "errors": [(final.stdout + final.stderr).strip() or "deck finalization failed"],
                }
            )
        else:
            finalized = True
            final_output = str(run_dir / deck.get("output", "final/deck_edited.pptx"))

    passed = not failed_pages
    if passed and not finalize:
        set_run_status(run_dir, "pages_recorded", "web pages built and recorded")
    summary = {
        "schema_version": 1,
        "run_id": deck.get("run_id"),
        "passed": passed,
        "finalized": finalized,
        "recorded_pages": recorded_pages,
        "failed_pages": failed_pages,
        "output": final_output,
        "completed_at": now_iso(),
    }
    write_json(run_dir / "web_build_summary.json", summary)
    write_json(run_dir / "failed_pages.json", {"pages": failed_pages})
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build, compare, validate, record, and finalize imported web pages.")
    parser.add_argument("run")
    parser.add_argument("--no-finalize", action="store_true")
    args = parser.parse_args()
    result = build_web_run(args.run, finalize=not args.no_finalize)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
