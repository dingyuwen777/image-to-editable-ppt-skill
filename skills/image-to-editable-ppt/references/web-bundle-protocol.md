# Web Bundle Protocol

This reference owns the file and integrity contract for batch handoffs between local `editppt` and ChatGPT Web. Page object-source decisions remain in `page-decision-tree.md`; page manifest fields remain in `manifest-schema.md`.

## 1. Common envelope

Every ZIP contains UTF-8 `bundle.json`:

```json
{
  "protocol": "editppt-web-bundle",
  "version": 1,
  "bundle_type": "handoff",
  "job_id": "20260730-010101-deck",
  "created_at": "2026-07-30T01:01:01Z",
  "pages": [
    {
      "page_id": "page_001",
      "page_index": 1,
      "source_sha256": "64 lowercase hexadecimal characters"
    }
  ]
}
```

Allowed `bundle_type` values:

- `handoff`: local prepared pages sent to ChatGPT Web.
- `reconstruction`: initial manifests/assets returned from ChatGPT Web.
- `revision-request`: failed-page evidence returned to ChatGPT Web.
- `revision-result`: replacement manifests/assets returned for a revision round.

`job_id`, `page_id`, and `source_sha256` must match the local prepared run. Local import rejects mismatches before writing page artifacts.

## 2. Path and ZIP safety

All member names are POSIX-relative. The importer rejects:

- absolute paths and drive-letter paths;
- backslashes;
- empty, `.`, or `..` path components;
- duplicate normalized names;
- NUL characters;
- symlinks and encrypted members;
- members or archives exceeding configured uncompressed-size limits;
- excessive compression ratios.

Extraction is performed manually into a staging directory. `extractall()` is not used. The importer validates every page before replacing authoritative run artifacts.

## 3. Handoff layout

```text
bundle.json
deck_manifest.json
notes_manifest.json
instructions/
  web-batch-worker.md
  page-decision-tree.md
  manifest-schema.md
  web-bundle-protocol.md
pages/page_001/
  source.png
  page_request.json
  text_hints.json        # optional when hint generation failed/was skipped
  text_hints.png         # optional overlay
```

Local absolute paths, API credentials, OAuth files, input originals, temporary files, and unrelated run artifacts are never exported.

## 4. Reconstruction result layout

```text
bundle.json
pages/page_001/
  manifest.json
  imagegen-jobs.json
  web_result.json         # optional explanatory metadata
  assets/
    clean-background.png
    icon-sheet.png
    icon-01.png
```

Rules:

1. `manifest.json` is the page's complete replacement manifest, not a prose description.
2. Every `images[].path` must remain below the same page's `assets/` directory.
3. Every generated/separated image must have a matching `asset_provenance` entry that satisfies `manifest-schema.md`.
4. `imagegen-jobs.json` records web image generation/editing intent and selected outputs.
5. Do not include `page.pptx`, `preview.png`, or final deck files. Local Runtime creates and validates them.
6. Do not use `source.png` as a full-slide image behind editable text.

## 5. Revision request layout

A revision request contains only pages that have not passed local validation:

```text
bundle.json
pages/page_001/
  source.png
  current-manifest.json
  current-imagegen-jobs.json
  preview.png
  split_assets_contact.png
  visual_diff.png
  visual_metrics.json
  validation.json
  page_result.json
  text_hints.json
  correction-request.json
  assets/...
```

The worker must compare the source, current preview, contact sheet, visual diff, metrics, and local validation evidence. `visual_metrics.json` is diagnostic evidence only: it cannot waive editability, provenance, semantic completeness, or manifest-contract failures. The worker returns a `revision-result` bundle with complete replacement `manifest.json`, `imagegen-jobs.json`, and required assets for each listed page.

## 6. Revision history

`revision-result` requires integer `round >= 1`. Local apply archives the previous page artifacts under:

```text
RUN/revisions/round-01/before/page_001/
```

Changed pages are reset to `pending`; successful pages are not reset. `editppt web build RUN` performs another deterministic build-render-compare-validate-record-finalize cycle.

## 7. Integrity and failure policy

- Invalid bundles must not modify authoritative run artifacts.
- Import uses a staging directory and rollback copies.
- Missing manifest assets are fatal.
- Source hash mismatch is fatal.
- Pages not present in the prepared run are fatal.
- An empty reconstruction or revision result is fatal.
- Local page/deck validation remains the delivery gate; a bundle cannot declare itself passed.
