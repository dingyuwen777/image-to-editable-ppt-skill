#!/usr/bin/env python3
"""Render page previews with portable font and SVG conversion discovery."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import build_pptx_from_manifest as builder
from platform_support import choose_preview_font, find_imagemagick


class PreviewRenderError(RuntimeError):
    pass


def _convert_svg(source: Path, destination: Path) -> None:
    executable = find_imagemagick()
    if not executable:
        raise PreviewRenderError(
            f"Cannot render SVG preview without ImageMagick on PATH: {source}. "
            "Install ImageMagick so `magick` or `convert` is available."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [executable, str(source), str(destination)]
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0 or not destination.is_file():
        raise PreviewRenderError(
            f"ImageMagick failed to convert {source}: "
            + (result.stdout + result.stderr).strip()
        )


def _preview_manifest(manifest: dict, manifest_path: Path, temporary: Path) -> dict:
    copied = json.loads(json.dumps(manifest))
    base = manifest_path.parent
    for index, image in enumerate(copied.get("images", []), start=1):
        raw_path = image.get("path")
        if not raw_path:
            continue
        source = Path(raw_path)
        if not source.is_absolute():
            source = base / source
        if source.suffix.lower() != ".svg":
            continue
        converted = temporary / f"image-{index:03d}.png"
        _convert_svg(source.resolve(), converted)
        image["path"] = str(converted)
    return copied


def render_cross_platform_preview(
    manifest_path: str | Path,
    out_path: str | Path,
) -> Path:
    manifest_path = Path(manifest_path).resolve()
    out_path = Path(out_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    original_font_chooser = builder.choose_preview_font
    builder.choose_preview_font = choose_preview_font
    try:
        with tempfile.TemporaryDirectory(prefix="editppt-preview-") as tmp:
            preview_manifest = _preview_manifest(manifest, manifest_path, Path(tmp))
            builder.render_preview(preview_manifest, manifest_path, out_path)
    finally:
        builder.choose_preview_font = original_font_chooser
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a page preview with portable font/SVG support.")
    parser.add_argument("manifest")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = render_cross_platform_preview(args.manifest, args.out)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
