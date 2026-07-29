# Web Batch Reconstruction Design

## Context

The original Skill tightly couples page reasoning, image generation/editing, deterministic PPTX construction, preview rendering, and validation inside a Codex/Page Worker loop. This produces strong page-level feedback but consumes significant subscription/model capacity and depends on an agent runtime with subagents, filesystem access, and image tools.

The new mode keeps the deterministic runtime local while moving semantic page reconstruction to ChatGPT Web. It avoids per-page local/web alternation by transferring page packets and reconstruction results in ZIP bundles. Real render feedback is handled in later revision rounds containing only failed pages.

## Architecture

### Local phase A: prepare and export

`editppt prepare` remains authoritative for input normalization, notes extraction, page rasterization, and text hints. `editppt web export RUN --out handoff.zip` packages a sanitized, content-addressed copy of the run data required by ChatGPT Web.

The handoff contains:

- `bundle.json`: bundle type/version, job id, source hashes, page list, and protocol constraints.
- `deck_manifest.json` and `notes_manifest.json`.
- Per-page `source.png`, `page_request.json`, `text_hints.json`, and `text_hints.png` when present.
- Web worker instructions and copies of the authoritative decision-tree and manifest-schema references.

No credentials, absolute local paths, OAuth data, or unrelated run artifacts are exported.

### Web phase: semantic reconstruction

A ChatGPT Web Skill reads the handoff, processes pages, uses web image generation/editing when required, and produces a reconstruction bundle. The bundle includes one `manifest.json` per processed page, generated assets, provenance records, and page result metadata. It does not include final PPTX files; deterministic construction remains local.

### Local phase B: import and build

`editppt web import RUN reconstruction.zip` verifies the bundle before modifying the run. Verification includes safe ZIP member validation, manifest schema checks, source/job/page hash matching, asset existence, provenance, size limits, and rejection of external paths. Import uses a staging directory and atomic replacement.

`editppt web build RUN` builds every imported page, creates previews/contact sheets, validates the page, writes the page result, records successful pages, and finalizes only when all pages pass. It emits a machine-readable summary and a failure list.

### Revision phase

`editppt revision export RUN --out revision.zip` packages only pages that failed or remain unrecorded. Each page packet contains the source, current preview, current manifest, validation result, text hints, available assets, and a structured correction request.

ChatGPT Web returns a revision result bundle containing replacement manifests/assets or constrained patch operations. `editppt revision apply RUN result.zip` validates and stages changes, preserving revision history. The next `editppt web build RUN` repeats deterministic build/render/validation.

## Bundle protocol

### Common envelope

Every bundle includes `bundle.json` with:

```json
{
  "protocol": "editppt-web-bundle",
  "version": 1,
  "bundle_type": "handoff|reconstruction|revision-request|revision-result",
  "job_id": "stable run identifier",
  "created_at": "UTC ISO-8601",
  "pages": [
    {
      "page_id": "page_001",
      "source_sha256": "..."
    }
  ]
}
```

### Path rules

- POSIX relative paths only.
- No empty names, `.`/`..`, drive letters, backslashes, NULs, or absolute paths.
- No symlinks or non-regular ZIP members.
- No duplicate normalized member names.
- Extraction must remain under a caller-provided staging directory.

### Integrity rules

- SHA-256 is computed from bytes, not timestamps.
- Reconstruction/revision page source hashes must match the prepared run.
- Assets listed in manifests must exist inside the same page directory after import.
- Import never trusts paths embedded in an incoming manifest without normalization and containment checks.

## Backend contract

Add `web-artifact` to the run backend contract. It declares:

- no API key requirement;
- no Codex OAuth requirement;
- assets arrive through a verified bundle;
- automatic fallback is disabled;
- missing or invalid assets fail validation.

The original `builtin-imagegen`, `editppt-image-cli`, and `openai-compatible-api` behavior remains unchanged.

## State model

Existing run/page state files remain authoritative. Web import adds page-local metadata under `web_import.json` and revision history under `revisions/`. The implementation does not invent a second competing page-state machine.

Imported pages are claimed with a deterministic agent id such as `web-batch`. Successful build/validation produces the same required page artifacts and uses the existing record/finalize commands.

## Failure handling

- Export failures leave no partial ZIP at the requested output path.
- Import failures leave authoritative run artifacts unchanged.
- One page failure does not erase successful pages.
- Finalization is blocked until every page is recorded.
- Revision bundles include explicit reasons and current evidence; they do not silently retry indefinitely.

## Compatibility

- Python remains >=3.10.
- No new mandatory runtime dependency is required for the bundle core; use the standard library (`zipfile`, `hashlib`, `json`, `tempfile`, `shutil`).
- Existing public commands continue to work.
- Existing documentation ownership rules remain intact: command syntax in `references/cli-helper.md`, protocol fields in a dedicated web protocol reference, parent workflow in the web Skill entry, and user procedures in repository docs.

## Security

Bundle import is treated as untrusted input. It must defend against ZIP Slip, symlink extraction, decompression bombs through configurable member/total-size limits, duplicate members, invalid UTF-8/path normalization ambiguity, and manifests that reference files outside the page directory.

Credentials are never exported. Handoff creation uses an allowlist of files rather than copying entire run directories.

## Testing strategy

- Unit tests for normalized safe paths, ZIP member rejection, hashing, envelope validation, and asset containment.
- Integration tests for export/import round trips using temporary fixture runs.
- CLI tests asserting help and command routing.
- Regression tests for existing backend contracts and `.ppt` normalization bug.
- GitHub Actions runs the complete unittest suite on Python 3.10, 3.11, and 3.12.

## Acceptance boundary

The implementation guarantees deterministic bundle integrity, editability/structure gates, and repeatable local construction. It does not guarantee universal pixel-perfect visual equivalence. Quality parity with the original Skill is established through a separate fixed A/B corpus and recorded metrics.