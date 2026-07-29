#!/usr/bin/env python3
"""Generate source-versus-preview visual diff artifacts for web revision rounds."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageEnhance, ImageOps


class VisualDiffError(RuntimeError):
    pass


def make_visual_diff(
    page_dir: str | Path,
    *,
    source_name: str = "source.png",
    preview_name: str = "preview.png",
    diff_name: str = "visual_diff.png",
    metrics_name: str = "visual_metrics.json",
    changed_threshold: int = 16,
) -> dict:
    page_dir = Path(page_dir).resolve()
    source_path = page_dir / source_name
    preview_path = page_dir / preview_name
    if not source_path.is_file():
        raise VisualDiffError(f"missing source image: {source_path}")
    if not preview_path.is_file():
        raise VisualDiffError(f"missing preview image: {preview_path}")

    source = Image.open(source_path).convert("RGB")
    preview_original = Image.open(preview_path).convert("RGB")
    preview = preview_original.resize(source.size, Image.Resampling.LANCZOS)
    difference = ImageChops.difference(source, preview)
    array = np.asarray(difference, dtype=np.float32)
    channel_max = array.max(axis=2)
    mean_absolute_error = float(array.mean() / 255.0)
    root_mean_square_error = float(np.sqrt(np.mean(np.square(array))) / 255.0)
    changed_ratio = float(np.mean(channel_max >= changed_threshold))
    max_channel_error = int(channel_max.max()) if channel_max.size else 0

    luminance = ImageOps.grayscale(difference)
    enhanced = ImageEnhance.Contrast(luminance).enhance(2.5)
    heat = ImageOps.colorize(enhanced, black=(0, 0, 0), white=(255, 255, 255))
    overlay = Image.blend(source, heat, 0.55)
    diff_path = page_dir / diff_name
    overlay.save(diff_path)

    metrics = {
        "schema_version": 1,
        "source": source_name,
        "preview": preview_name,
        "source_size_px": {"width": source.width, "height": source.height},
        "preview_original_size_px": {
            "width": preview_original.width,
            "height": preview_original.height,
        },
        "preview_resized_for_comparison": preview_original.size != source.size,
        "changed_threshold": changed_threshold,
        "mean_absolute_error": round(mean_absolute_error, 8),
        "root_mean_square_error": round(root_mean_square_error, 8),
        "changed_pixel_ratio": round(changed_ratio, 8),
        "max_channel_error": max_channel_error,
        "interpretation": (
            "Diagnostic only. Visual metrics cannot waive manifest, editability, provenance, or semantic completeness checks."
        ),
    }
    metrics_path = page_dir / metrics_name
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "diff": str(diff_path),
        "metrics": str(metrics_path),
        **metrics,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create visual_diff.png and visual_metrics.json for one page.")
    parser.add_argument("page_dir")
    parser.add_argument("--source", default="source.png")
    parser.add_argument("--preview", default="preview.png")
    parser.add_argument("--diff", default="visual_diff.png")
    parser.add_argument("--metrics", default="visual_metrics.json")
    parser.add_argument("--changed-threshold", type=int, default=16)
    args = parser.parse_args()
    result = make_visual_diff(
        args.page_dir,
        source_name=args.source,
        preview_name=args.preview,
        diff_name=args.diff,
        metrics_name=args.metrics,
        changed_threshold=args.changed_threshold,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
