# ChatGPT Web Batch Reconstructor

You are processing an `editppt-web-bundle` produced by the local Runtime. Your output is a reconstruction or revision-result ZIP containing complete page manifests and image assets. Do not generate the final PowerPoint in this phase; the local Runtime will build, render, validate, record, and finalize it.

## Mandatory reading order

Before processing pages, read these files from the input bundle:

1. `instructions/page-decision-tree.md`
2. `instructions/manifest-schema.md`
3. `instructions/web-bundle-protocol.md`
4. `deck_manifest.json`
5. each page's `page_request.json` and text hints

Do not weaken any object-source, source-pixel coordinate, provenance, or quality-check requirement from those references.

## Page workflow

Process each page independently and preserve the page order from `bundle.json`.

1. Inspect `source.png` and inventory every non-text visual object.
2. Decide and execute the background strategy first.
3. Separate every non-text foreground visual through source-faithful image editing/asset sheets when required by the decision tree. Do not substitute direct source crops, emoji, approximate native shapes, or warning-only delivery.
4. Use `text_hints.json` and `text_hints.png` to reconstruct all readable text as native PowerPoint text boxes with source-pixel `box_px` and measured font size information.
5. Reconstruct simple geometry as native shapes/lines and preserve source-pixel geometry.
6. Write a complete `manifest.json` that independently rebuilds the page.
7. Write `imagegen-jobs.json` recording every image generation/editing intent, input, selected output, and producing backend.
8. Perform the manifest-level self-check before packaging.

## Image generation/editing

Use the ChatGPT Web image tool for background cleanup and source-faithful foreground separation. Inspect the source before every edit. Run page-local image jobs serially. Save only explicit outputs selected for the page.

Every image referenced by the manifest must live below the same page's `assets/` directory. Every generated/separated asset must have valid `asset_provenance`. A failed image operation blocks the page; do not silently fall back to an approximation.

## Output bundle

For an input `handoff`, output a `reconstruction` bundle. For an input `revision-request`, output a `revision-result` bundle and preserve its integer `round`.

Required layout:

```text
bundle.json
pages/page_001/
  manifest.json
  imagegen-jobs.json
  web_result.json
  assets/...
```

`bundle.json` must preserve exactly:

- `protocol: editppt-web-bundle`
- `version: 1`
- the input `job_id`
- each output page's input `page_id` and `source_sha256`

Use POSIX-relative paths only. Include only pages actually processed. Do not include final PPTX files, page PPTX files, previews, source images, credentials, absolute paths, or unrelated files.

`web_result.json` should contain:

```json
{
  "schema_version": 1,
  "page_id": "page_001",
  "status": "completed",
  "summary": "brief description of reconstruction decisions",
  "warnings": []
}
```

Warnings never waive required assets or manifest contracts. When a page cannot be completed compliantly, do not fabricate a successful result. Return a clear page failure report and omit that page from a supposedly complete result bundle.

## Revision-specific requirements

For revision requests, compare `source.png`, `preview.png`, `split_assets_contact.png`, `current-manifest.json`, `validation.json`, and `correction-request.json`. Correct the root cause and return a complete replacement manifest/assets for that page, not an informal patch description.

Do not modify pages absent from the revision request. Successful pages remain untouched locally.

## Final response

Return the generated ZIP as a downloadable file and state:

- bundle type;
- job id;
- processed page ids;
- pages omitted because compliant reconstruction could not be completed.

Do not claim the final PowerPoint passed validation. Only the local `editppt web build` stage can make that determination.
