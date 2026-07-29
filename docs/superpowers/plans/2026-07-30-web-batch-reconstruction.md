# Web Batch Reconstruction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a secure, low-API-cost batch handoff and revision workflow between local `editppt` and ChatGPT Web without breaking the original Skill workflow.

**Architecture:** Local `editppt` exports sanitized page packets, ChatGPT Web returns manifests/assets, and local `editppt` performs deterministic import, build, render, validation, record, and finalization. Later rounds exchange only failed pages through revision bundles.

**Tech Stack:** Python 3.10+, standard-library ZIP/JSON/hash/path modules, existing editppt runtime, unittest, GitHub Actions.

## Global Constraints

- Preserve all existing CLI behavior and tests.
- Web mode must not require OpenAI API credentials or Codex OAuth.
- Bundle import is untrusted and must be staged, validated, and atomic.
- Existing `manifest.json` and run state remain authoritative.
- Do not accept full-slide source overlays as editable reconstruction.
- Support Windows, macOS, Linux, UTF-8, and Chinese paths.
- Use test-first implementation for every behavior change.

---

### Task 1: Continuous verification workflow

**Files:**
- Create: `.github/workflows/web-batch-tests.yml`

**Interfaces:**
- Consumes: repository `tests/` and skill-local CLI package.
- Produces: Python 3.10/3.11/3.12 CI signal on feature-branch pushes and pull requests.

- [ ] **Step 1: Add workflow** that installs `skills/image-to-editable-ppt/cli` editable and runs `python -m unittest discover -s tests -v`.
- [ ] **Step 2: Push and verify** the workflow completes on the feature branch.

### Task 2: Secure bundle primitives

**Files:**
- Create: `tests/test_web_bundle_security.py`
- Create: `skills/image-to-editable-ppt/cli/editppt/runtime/web_bundle.py`

**Interfaces:**
- Produces: `sha256_file(path) -> str`, `normalize_member_name(name) -> str`, `inspect_zip(path, limits) -> list[ZipMember]`, `safe_extract(zip_path, destination, limits) -> list[Path]`, `load_bundle_envelope(root, expected_type=None) -> dict`.

- [ ] **Step 1: Write failing tests** for traversal, absolute paths, Windows drive paths, backslashes, duplicate normalized names, symlinks, member-size limits, total-size limits, and valid extraction.
- [ ] **Step 2: Run CI and confirm expected failures** because `web_bundle` does not exist.
- [ ] **Step 3: Implement minimal secure primitives** using `zipfile`, `pathlib`, `hashlib`, and staging directories.
- [ ] **Step 4: Run complete tests** and verify green.

### Task 3: Handoff bundle export

**Files:**
- Create: `tests/test_web_handoff_export.py`
- Create: `skills/image-to-editable-ppt/cli/editppt/runtime/export_web_handoff.py`
- Create: `skills/image-to-editable-ppt/references/web-bundle-protocol.md`

**Interfaces:**
- Consumes: prepared run directory and authoritative run manifests.
- Produces: `export_handoff(run, out, instructions_root=None) -> dict` and `web-handoff.zip`.

- [ ] **Step 1: Write failing fixture test** asserting allowlisted files, source hashes, no absolute paths, deterministic page order, and omission of credentials/unrelated artifacts.
- [ ] **Step 2: Verify red in CI.**
- [ ] **Step 3: Implement export** with temporary output and atomic rename.
- [ ] **Step 4: Verify round-trip inspection and full test suite.**

### Task 4: Reconstruction bundle import

**Files:**
- Create: `tests/test_web_bundle_import.py`
- Create: `skills/image-to-editable-ppt/cli/editppt/runtime/import_web_reconstruction.py`

**Interfaces:**
- Consumes: prepared run plus `reconstruction` bundle.
- Produces: verified page-local `manifest.json`, assets, `imagegen-jobs.json`, and `web_import.json`.

- [ ] **Step 1: Write failing tests** for valid import, mismatched job id, source hash mismatch, missing manifest, missing asset, external asset path, duplicate page, and atomic rollback.
- [ ] **Step 2: Verify red in CI.**
- [ ] **Step 3: Implement staged import** and asset-reference containment checks.
- [ ] **Step 4: Verify green and unchanged run on invalid input.**

### Task 5: `web-artifact` backend

**Files:**
- Modify: `skills/image-to-editable-ppt/cli/editppt/runtime/configure_image_backend.py`
- Modify: `skills/image-to-editable-ppt/cli/editppt/runtime/main.py`
- Create: `tests/test_web_artifact_backend.py`

**Interfaces:**
- Produces backend contract with `backend_id=web-artifact`, `requires_openai_api_key=false`, `asset_delivery=reconstruction-bundle`, and disabled fallback.

- [ ] **Step 1: Add failing backend contract and CLI parser tests.**
- [ ] **Step 2: Verify red.**
- [ ] **Step 3: Add the backend choice and fixed contract.**
- [ ] **Step 4: Verify existing backend tests and all tests pass.**

### Task 6: Web CLI commands

**Files:**
- Modify: `skills/image-to-editable-ppt/cli/editppt/runtime/main.py`
- Create: `skills/image-to-editable-ppt/cli/editppt/runtime/build_web_run.py`
- Create: `tests/test_web_cli.py`
- Create: `tests/test_web_build_pipeline.py`

**Interfaces:**
- Produces commands: `editppt web export`, `editppt web inspect`, `editppt web import`, `editppt web build`.

- [ ] **Step 1: Write failing parser/help tests.**
- [ ] **Step 2: Write failing build-pipeline fixture test** using a minimal imported page.
- [ ] **Step 3: Implement command routing.**
- [ ] **Step 4: Implement build orchestration** by invoking existing page build/contact-sheet/validate/record/finalize scripts and emitting JSON summary.
- [ ] **Step 5: Verify all tests pass.**

### Task 7: Revision request/result bundles

**Files:**
- Create: `tests/test_revision_bundle.py`
- Create: `tests/test_revision_patch.py`
- Create: `skills/image-to-editable-ppt/cli/editppt/runtime/export_web_revision.py`
- Create: `skills/image-to-editable-ppt/cli/editppt/runtime/apply_web_revision.py`
- Modify: `skills/image-to-editable-ppt/cli/editppt/runtime/main.py`

**Interfaces:**
- Produces commands: `editppt revision export` and `editppt revision apply`.

- [ ] **Step 1: Write failing tests** for exporting only failed/unrecorded pages with current evidence.
- [ ] **Step 2: Write failing tests** for valid replacement import, source hash mismatch, unsafe path, and revision-history preservation.
- [ ] **Step 3: Implement revision export.**
- [ ] **Step 4: Implement staged revision apply.**
- [ ] **Step 5: Verify repeated build/revision rounds leave successful pages untouched.**

### Task 8: Cross-platform correctness fixes

**Files:**
- Modify: `skills/image-to-editable-ppt/cli/editppt/runtime/_input_normalization.py`
- Modify: `skills/image-to-editable-ppt/cli/editppt/runtime/build_pptx_from_manifest.py`
- Create: `tests/test_cross_platform_runtime.py`

**Interfaces:**
- Fixes `.ppt` DPI parameter use, ImageMagick discovery through `shutil.which`, and cross-platform CJK preview-font discovery.

- [ ] **Step 1: Write failing regression tests.**
- [ ] **Step 2: Fix `args.dpi` to `dpi`.**
- [ ] **Step 3: Add executable/font discovery helpers.**
- [ ] **Step 4: Verify full suite.**

### Task 9: Web Skill and user documentation

**Files:**
- Create: `skills/image-to-editable-ppt-web/SKILL.md`
- Create: `skills/image-to-editable-ppt-web/prompts/web-batch-worker.md`
- Create: `docs/WEB_BATCH_USAGE_ZH.md`
- Create: `docs/WEB_BATCH_TROUBLESHOOTING_ZH.md`
- Modify: `skills/image-to-editable-ppt/references/cli-helper.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Documents the exact local/web/local workflow, bundle output contract, multi-round revision process, installation, safety limits, and quality claim boundary.

- [ ] **Step 1: Write docs against implemented CLI help.**
- [ ] **Step 2: Run command-help tests and inspect documentation links.**
- [ ] **Step 3: Add changelog entries.**

### Task 10: Final verification and pull request

**Files:**
- No new production files required.

- [ ] **Step 1: Run complete GitHub Actions matrix** and record exact run/check results.
- [ ] **Step 2: Review branch diff** for generated artifacts, credentials, absolute paths, and documentation inconsistencies.
- [ ] **Step 3: Open a draft PR** to `main` with architecture, commands, test evidence, limitations, and manual A/B validation requirements.
- [ ] **Step 4: Mark ready only after all required checks pass.**