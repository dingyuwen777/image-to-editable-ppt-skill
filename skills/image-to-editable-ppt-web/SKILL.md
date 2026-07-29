---
name: image-to-editable-ppt-web

description: Process editppt web handoff and revision ZIP bundles in ChatGPT Web. Use when the user uploads a bundle created by `editppt web export` or `editppt revision export` and wants a low-API reconstruction/revision bundle for later local PPTX building. This Skill does not create the final PPTX directly.
---
# Image to Editable PPT — Web Batch

## Purpose

This Skill is the ChatGPT Web half of the low-API workflow:

```text
local prepare/export
→ ChatGPT Web semantic reconstruction and image editing
→ local import/build/render/validate/finalize
```

It accepts only protocol bundles created by the modified local `editppt` Runtime:

- `handoff` → produce `reconstruction`;
- `revision-request` → produce `revision-result`.

It does not replace local deterministic construction. Never claim that a final PPTX passed validation inside this Skill.

## Entry checks

1. Confirm the upload is a ZIP and contains `bundle.json`.
2. Read and verify:
   - `protocol` is `editppt-web-bundle`;
   - `version` is `1`;
   - `bundle_type` is `handoff` or `revision-request`;
   - `job_id`, page ids, and source hashes are present.
3. Extract only into a dedicated task directory. Reject absolute paths, `..`, backslashes, duplicate names, symlinks, or files outside the task directory.
4. Read `instructions/web-batch-worker.md` from the bundle and follow it as the page execution contract.
5. Read the bundled decision tree, manifest schema, and protocol before reconstructing a page.

## Execution

- Process pages in input order.
- Keep each page's working files under its own page directory.
- Use the webpage's multimodal understanding for page decomposition.
- Use the built-in image generation/editing tool for compliant background repair and foreground asset separation.
- Reconstruct readable text and simple geometry in `manifest.json`, not in a rendered screenshot.
- Preserve the source SHA-256 values exactly in the output envelope.
- For long decks, process pages in bounded batches while continuously saving page results. Do not rely on remembering earlier pages; rely on the bundle files and written manifests.

## Quality requirements

The bundled references are authoritative. In particular:

- background → foreground assets → native PPT reconstruction is the mandatory order;
- readable text defaults to native editable text boxes;
- positioned objects require source-pixel coordinates;
- foreground visuals cannot use direct crops, emoji, approximate native shapes, or silent fallback;
- image assets require provenance;
- a full-slide source image plus hidden/editable text is forbidden;
- all required quality checks must be explicitly true only after they were performed.

## Output packaging

Create one ZIP with the layout required by `instructions/web-bundle-protocol.md`.

For initial reconstruction:

```text
bundle.json                       # bundle_type=reconstruction
pages/page_NNN/manifest.json
pages/page_NNN/imagegen-jobs.json
pages/page_NNN/web_result.json
pages/page_NNN/assets/...
```

For a revision:

```text
bundle.json                       # bundle_type=revision-result and same round
pages/page_NNN/manifest.json
pages/page_NNN/imagegen-jobs.json
pages/page_NNN/web_result.json
pages/page_NNN/assets/...
```

Do not package source pages, credentials, local absolute paths, temporary files, page PPTX files, previews, or final PPTX files.

## Failure behavior

A page that cannot satisfy the bundled contracts is not a successful page. Do not fabricate assets, validation results, or quality checks. Report omitted/failed page ids in the final message so the user can decide whether to retry that page.

The local commands after download are:

```bash
editppt web import <run> reconstruction.zip
editppt web build <run>
```

For later rounds:

```bash
editppt revision apply <run> revision-result.zip
editppt web build <run>
```
