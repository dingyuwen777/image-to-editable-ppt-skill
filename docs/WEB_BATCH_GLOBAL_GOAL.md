# Web Batch Reconstruction Global Goal

## Objective

Extend `image-to-editable-ppt` with a low-API-cost web batch workflow that preserves the original deterministic runtime and quality contracts while moving multimodal page reasoning and image generation/editing to ChatGPT Web.

The normal user flow must require only batch handoffs, not page-by-page alternation:

1. Local `editppt` prepares and exports a web handoff bundle.
2. ChatGPT Web processes the bundle and returns a reconstruction bundle.
3. Local `editppt` imports, builds, renders, validates, records, and finalizes the deck.
4. Only pages that fail validation are exported for another web revision round.

## Non-negotiable constraints

- Existing CLI commands and the original Codex/Page Worker workflow remain compatible.
- Web batch mode must not require `OPENAI_API_KEY` or Codex OAuth.
- Web-generated assets are imported through an explicit `web-artifact` backend with provenance and integrity records.
- Bundle imports reject path traversal, absolute paths, symlinks, duplicate members, mismatched job/page hashes, missing assets, and schema-invalid data.
- Final PPTX assembly continues to use page `manifest.json` files as authoritative inputs.
- A page with failed structural or quality validation must not be silently accepted or included as a successful page.
- Full-slide source-image overlays with hidden/editable text are not an acceptable implementation.
- The workflow supports repeated rebuild-render-compare-revise rounds through failure/revision bundles.
- Windows, macOS, and Linux paths and Chinese filenames must be supported.

## Deliverables

- `editppt web export`
- `editppt web inspect`
- `editppt web import`
- `editppt web build`
- `editppt revision export`
- `editppt revision apply`
- `web-artifact` image backend
- Bundle schemas, integrity checks, and safe extraction
- Regression and security tests
- GitHub Actions verification
- Chinese usage and troubleshooting documentation

## Definition of done

The feature is complete only when:

1. All pre-existing tests pass.
2. All new web batch and revision tests pass on GitHub Actions.
3. A fixture run can be exported, reconstructed by fixture bundle, imported, built, validated, recorded, and finalized without model API credentials.
4. Tampered or unsafe bundles fail before modifying authoritative run artifacts.
5. Failed pages can be exported and patched in a later revision round without reprocessing successful pages.
6. The documented commands match the implemented CLI help and behavior.
7. A draft pull request contains implementation details, test evidence, limitations, and the user guide.

## Quality claim boundary

The project may claim deterministic workflow compatibility and regression-tested quality gates. It must not claim universal pixel-perfect reproduction. Equivalence to the original Skill must be demonstrated on a fixed A/B corpus using structural editability, text coverage, page validation, asset completeness, and visual review metrics.