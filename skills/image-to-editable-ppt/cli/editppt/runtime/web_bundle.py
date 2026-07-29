#!/usr/bin/env python3
"""Security and integrity primitives for editppt web handoff bundles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping


PROTOCOL = "editppt-web-bundle"
PROTOCOL_VERSION = 1
BUNDLE_TYPES = {"handoff", "reconstruction", "revision-request", "revision-result"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DRIVE_RE = re.compile(r"^[A-Za-z]:")


class BundleValidationError(ValueError):
    """Raised when an untrusted bundle violates the web bundle contract."""


@dataclass(frozen=True)
class BundleLimits:
    max_members: int = 5000
    max_member_size: int = 256 * 1024 * 1024
    max_total_size: int = 2 * 1024 * 1024 * 1024
    max_compression_ratio: float = 250.0


@dataclass(frozen=True)
class ZipMember:
    name: str
    size: int
    compressed_size: int
    is_dir: bool


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_member_name(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise BundleValidationError("bundle member name must be a non-empty string")
    if "\x00" in name:
        raise BundleValidationError("bundle member name contains NUL")
    if "\\" in name:
        raise BundleValidationError(f"bundle member must use POSIX separators: {name!r}")
    if name.startswith("/") or DRIVE_RE.match(name):
        raise BundleValidationError(f"absolute bundle member path is forbidden: {name!r}")

    stripped = name[:-1] if name.endswith("/") else name
    if not stripped:
        raise BundleValidationError("bundle root directory entry is forbidden")
    raw_parts = stripped.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise BundleValidationError(f"unsafe bundle member path: {name!r}")

    path = PurePosixPath(*raw_parts)
    normalized = path.as_posix()
    if normalized.startswith("../") or normalized == ".." or path.is_absolute():
        raise BundleValidationError(f"unsafe bundle member path: {name!r}")
    return normalized


def _unix_mode(info: zipfile.ZipInfo) -> int:
    return (info.external_attr >> 16) & 0xFFFF if info.create_system == 3 else 0


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = _unix_mode(info)
    return bool(mode and stat.S_ISLNK(mode))


def inspect_zip(path: str | Path, limits: BundleLimits | None = None) -> list[ZipMember]:
    limits = limits or BundleLimits()
    archive_path = Path(path)
    try:
        archive = zipfile.ZipFile(archive_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise BundleValidationError(f"invalid ZIP bundle: {archive_path}") from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > limits.max_members:
            raise BundleValidationError(
                f"bundle member count exceeds limit: {len(infos)} > {limits.max_members}"
            )

        seen: set[str] = set()
        total_size = 0
        members: list[ZipMember] = []
        for info in infos:
            normalized = normalize_member_name(info.filename)
            if normalized in seen:
                raise BundleValidationError(f"duplicate normalized bundle member: {normalized}")
            seen.add(normalized)

            if info.flag_bits & 0x1:
                raise BundleValidationError(f"encrypted ZIP members are forbidden: {normalized}")
            if _is_symlink(info):
                raise BundleValidationError(f"symlink ZIP members are forbidden: {normalized}")
            if info.file_size < 0 or info.compress_size < 0:
                raise BundleValidationError(f"invalid ZIP member size: {normalized}")
            if info.file_size > limits.max_member_size:
                raise BundleValidationError(
                    f"bundle member size exceeds limit: {normalized} ({info.file_size} > {limits.max_member_size})"
                )

            total_size += info.file_size
            if total_size > limits.max_total_size:
                raise BundleValidationError(
                    f"bundle total size exceeds limit: {total_size} > {limits.max_total_size}"
                )
            if (
                not info.is_dir()
                and info.file_size > 0
                and info.compress_size == 0
            ):
                raise BundleValidationError(f"invalid zero compressed size: {normalized}")
            if (
                not info.is_dir()
                and info.compress_size > 0
                and info.file_size / info.compress_size > limits.max_compression_ratio
            ):
                raise BundleValidationError(f"bundle compression ratio exceeds limit: {normalized}")

            members.append(
                ZipMember(
                    name=normalized,
                    size=info.file_size,
                    compressed_size=info.compress_size,
                    is_dir=info.is_dir(),
                )
            )
        return members


def _ensure_no_symlink_ancestors(destination: Path, target: Path) -> None:
    destination = destination.resolve()
    current = target
    while current != destination:
        if current.exists() and current.is_symlink():
            raise BundleValidationError(f"extraction target contains symlink: {current}")
        current = current.parent
    if destination.exists() and destination.is_symlink():
        raise BundleValidationError(f"extraction destination is a symlink: {destination}")


def safe_extract(
    zip_path: str | Path,
    destination: str | Path,
    limits: BundleLimits | None = None,
) -> list[Path]:
    limits = limits or BundleLimits()
    inspect_zip(zip_path, limits)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    extracted: list[Path] = []

    with zipfile.ZipFile(zip_path, "r") as archive:
        for info in archive.infolist():
            normalized = normalize_member_name(info.filename)
            target = (root / Path(*PurePosixPath(normalized).parts)).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise BundleValidationError(f"bundle member escapes extraction root: {normalized}") from exc
            _ensure_no_symlink_ancestors(root, target.parent)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.is_symlink():
                raise BundleValidationError(f"refusing to overwrite symlink: {target}")
            written = 0
            with archive.open(info, "r") as source, target.open("wb") as output:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > limits.max_member_size:
                        raise BundleValidationError(f"extracted member exceeded limit: {normalized}")
                    output.write(chunk)
            if written != info.file_size:
                raise BundleValidationError(
                    f"extracted member size mismatch: {normalized} ({written} != {info.file_size})"
                )
            extracted.append(target)
    return extracted


def _validate_page_entry(page: object, index: int) -> tuple[str, str]:
    if not isinstance(page, dict):
        raise BundleValidationError(f"bundle pages[{index}] must be an object")
    page_id = page.get("page_id")
    source_hash = page.get("source_sha256")
    if not isinstance(page_id, str) or not page_id.strip():
        raise BundleValidationError(f"bundle pages[{index}].page_id is required")
    if not isinstance(source_hash, str) or not SHA256_RE.fullmatch(source_hash):
        raise BundleValidationError(f"bundle pages[{index}].source_sha256 must be lowercase SHA-256")
    return page_id, source_hash


def validate_bundle_envelope(envelope: object, expected_type: str | None = None) -> dict:
    if not isinstance(envelope, dict):
        raise BundleValidationError("bundle.json must contain a JSON object")
    if envelope.get("protocol") != PROTOCOL:
        raise BundleValidationError(f"unsupported bundle protocol: {envelope.get('protocol')!r}")
    if envelope.get("version") != PROTOCOL_VERSION:
        raise BundleValidationError(f"unsupported bundle version: {envelope.get('version')!r}")

    bundle_type = envelope.get("bundle_type")
    if bundle_type not in BUNDLE_TYPES:
        raise BundleValidationError(f"unsupported bundle type: {bundle_type!r}")
    if expected_type is not None and bundle_type != expected_type:
        raise BundleValidationError(
            f"unexpected bundle type: expected {expected_type!r}, received {bundle_type!r}"
        )

    job_id = envelope.get("job_id")
    if not isinstance(job_id, str) or not job_id.strip():
        raise BundleValidationError("bundle job_id is required")
    created_at = envelope.get("created_at")
    if not isinstance(created_at, str) or not created_at.strip():
        raise BundleValidationError("bundle created_at is required")

    pages = envelope.get("pages")
    if not isinstance(pages, list):
        raise BundleValidationError("bundle pages must be an array")
    seen_pages: set[str] = set()
    for index, page in enumerate(pages):
        page_id, _ = _validate_page_entry(page, index)
        if page_id in seen_pages:
            raise BundleValidationError(f"duplicate page id in bundle: {page_id}")
        seen_pages.add(page_id)
    return envelope


def load_bundle_envelope(root: str | Path, expected_type: str | None = None) -> dict:
    path = Path(root) / "bundle.json"
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BundleValidationError("bundle.json is missing") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleValidationError("bundle.json is not valid UTF-8 JSON") from exc
    return validate_bundle_envelope(envelope, expected_type=expected_type)


def json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_zip_atomic(
    out_path: str | Path,
    members: Mapping[str, bytes | str | Path],
) -> Path:
    """Write an allowlisted bundle atomically with deterministic ZIP metadata."""

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_members: dict[str, bytes | str | Path] = {}
    for name, source in members.items():
        normalized = normalize_member_name(name)
        if normalized in normalized_members:
            raise BundleValidationError(f"duplicate output bundle member: {normalized}")
        normalized_members[normalized] = source

    fd, temporary_name = tempfile.mkstemp(prefix=f".{out_path.name}.", suffix=".tmp", dir=out_path.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name in sorted(normalized_members):
                source = normalized_members[name]
                if isinstance(source, Path):
                    payload = source.read_bytes()
                elif isinstance(source, str):
                    payload = source.encode("utf-8")
                else:
                    payload = bytes(source)
                info = zipfile.ZipInfo(name)
                info.date_time = (1980, 1, 1, 0, 0, 0)
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, payload)
        inspect_zip(temporary)
        os.replace(temporary, out_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return out_path


def staged_extract(zip_path: str | Path, parent: str | Path, limits: BundleLimits | None = None):
    """Context manager-like helper returning a TemporaryDirectory and extracted root.

    The caller owns cleanup through the returned TemporaryDirectory instance.
    """

    temporary = tempfile.TemporaryDirectory(prefix="editppt-web-", dir=Path(parent))
    root = Path(temporary.name)
    safe_extract(zip_path, root, limits=limits)
    return temporary, root


def copy_regular_file(source: str | Path, destination: str | Path) -> Path:
    source = Path(source)
    destination = Path(destination)
    if not source.is_file() or source.is_symlink():
        raise BundleValidationError(f"expected regular source file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return destination
