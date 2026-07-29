#!/usr/bin/env python3
"""Cross-platform executable and CJK font discovery for editppt previews."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def find_imagemagick() -> str | None:
    """Return a usable ImageMagick executable from PATH or common install paths."""

    for command in ("magick", "convert"):
        found = shutil.which(command)
        if found:
            return found
    candidates = (
        "/opt/homebrew/bin/magick",
        "/opt/homebrew/bin/convert",
        "/usr/local/bin/magick",
        "/usr/local/bin/convert",
        "/usr/bin/magick",
        "/usr/bin/convert",
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    return None


def preview_font_candidates(preferred: str | None) -> list[str]:
    """Return ordered CJK-capable preview font candidates for all target OSes."""

    windows = os.environ.get("WINDIR", r"C:\Windows")
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        preferred,
        # Windows system and per-user fonts.
        str(Path(windows) / "Fonts/msyh.ttc"),
        str(Path(windows) / "Fonts/msyhbd.ttc"),
        str(Path(windows) / "Fonts/simhei.ttf"),
        str(Path(windows) / "Fonts/Deng.ttf"),
        str(Path(local_app_data) / "Microsoft/Windows/Fonts/SourceHanSansCN-Regular.otf")
        if local_app_data
        else None,
        # Linux distributions / container images.
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/source-han-sans/SourceHanSansCN-Regular.otf",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        # macOS.
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = str(Path(candidate))
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def choose_preview_font(preferred: str | None = None) -> str | None:
    for candidate in preview_font_candidates(preferred):
        if Path(candidate).is_file():
            return candidate
    return None
