"""Strict parser for source-bound static compatibility bundles."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

from .bounded_file import BoundedFileError, read_bounded_regular_file, sha256_regular_file
from .extraction_ledger import BlockSource
from .safe_output import safe_relative_path
from .supplemental_evidence import (
    SupplementalEvidence,
    SupplementalEvidenceError,
    SupplementalFile,
    SupplementalKey,
    normalize_internal_name,
)


CompatBundleError = SupplementalEvidenceError
COMPAT_MANIFEST_NAME: Final = "w3xray-compat-bundle.tsv"
MAX_COMPAT_MANIFEST_SIZE: Final = 2 * 1024 * 1024
MAX_COMPAT_NAMES: Final = 100_000
MAX_COMPAT_FILES: Final = 10_000
MAX_COMPAT_KEYS: Final = 262_144
MAX_COMPAT_FILE_SIZE: Final = 256 * 1024 * 1024
MAX_COMPAT_TOTAL_SIZE: Final = 512 * 1024 * 1024
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")
_KEY_RE: Final = re.compile(r"[0-9A-Fa-f]{8}")


@dataclass(frozen=True, slots=True)
class _Rows:
    names: tuple[str, ...]
    files: tuple[tuple[str, str], ...]
    keys: tuple[SupplementalKey, ...]


def load_compat_bundle(
    root: str | Path,
    source_path: str | Path,
) -> SupplementalEvidence:
    """Parse, identity-bind, and hash-check a compatibility directory."""
    bundle_root = Path(root)
    if bundle_root.is_symlink():
        raise CompatBundleError("bundle root is a symlink")
    if not bundle_root.is_dir():
        raise CompatBundleError("bundle root is not a directory")
    lines = _read_manifest(bundle_root)
    expected_source_sha256 = _parse_source_identity(lines)
    try:
        actual_source_sha256, _identity = sha256_regular_file(Path(source_path))
    except BoundedFileError as exc:
        raise CompatBundleError(f"cannot hash source: {exc.reason}") from exc
    if actual_source_sha256 != expected_source_sha256:
        raise CompatBundleError("source SHA-256 mismatch")
    rows = _parse_rows(lines[2:])
    files = _load_files(bundle_root, rows.files)
    return SupplementalEvidence(
        expected_source_sha256,
        rows.names,
        files,
        rows.keys,
    )


def _read_manifest(root: Path) -> list[str]:
    try:
        payload, _identity = read_bounded_regular_file(
            root / COMPAT_MANIFEST_NAME,
            MAX_COMPAT_MANIFEST_SIZE,
        )
    except BoundedFileError as exc:
        raise CompatBundleError(
            f"missing or oversized {COMPAT_MANIFEST_NAME}: {exc.reason}",
        ) from exc
    try:
        return payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise CompatBundleError("manifest is not valid UTF-8") from exc


def _parse_source_identity(lines: list[str]) -> str:
    if len(lines) < 2 or lines[0] != "W3XRAY-COMPAT-BUNDLE\t1":
        raise CompatBundleError("unsupported manifest header")
    parts = lines[1].split("\t")
    if len(parts) != 2 or parts[0] != "source_sha256":
        raise CompatBundleError("missing source SHA-256")
    return _parse_sha256(parts[1], "source SHA-256")


def _parse_rows(lines: list[str]) -> _Rows:
    names: list[str] = []
    files: list[tuple[str, str]] = []
    keys: list[SupplementalKey] = []
    paths: set[str] = set()
    blocks: set[int] = set()
    for line in lines:
        parts = line.split("\t")
        if not parts:
            raise CompatBundleError("empty manifest row")
        match parts[0]:
            case "name":
                if len(parts) != 2 or len(names) >= MAX_COMPAT_NAMES:
                    raise CompatBundleError("invalid or excessive name row")
                name = _parse_internal_path(parts[1])
                _claim_path(name, paths)
                names.append(name)
            case "file":
                if len(parts) != 3 or len(files) >= MAX_COMPAT_FILES:
                    raise CompatBundleError("invalid or excessive file row")
                name = _parse_internal_path(parts[1])
                _claim_path(name, paths)
                files.append((name, _parse_sha256(parts[2], "file SHA-256")))
            case "mpq_key":
                if len(parts) != 5 or len(keys) >= MAX_COMPAT_KEYS:
                    raise CompatBundleError("invalid or excessive mpq_key row")
                key = _parse_key(parts)
                if key.block_index in blocks:
                    raise CompatBundleError(
                        f"duplicate MPQ key block: {key.block_index}",
                    )
                blocks.add(key.block_index)
                keys.append(key)
            case _:
                raise CompatBundleError("unknown manifest row")
    return _Rows(tuple(names), tuple(files), tuple(keys))


def _parse_key(parts: list[str]) -> SupplementalKey:
    if not parts[1].isdecimal():
        raise CompatBundleError("invalid MPQ block index")
    block_index = int(parts[1])
    if block_index > 0xFFFF_FFFF or _KEY_RE.fullmatch(parts[2]) is None:
        raise CompatBundleError("invalid MPQ key")
    internal_path = None if parts[4] == "-" else _parse_internal_path(parts[4])
    return SupplementalKey(
        block_index,
        int(parts[2], 16),
        _parse_sha256(parts[3], "plaintext SHA-256"),
        internal_path,
    )


def _load_files(
    root: Path,
    declarations: tuple[tuple[str, str], ...],
) -> tuple[SupplementalFile, ...]:
    if not declarations:
        return ()
    payload_root = root / "files"
    if payload_root.is_symlink():
        raise CompatBundleError("payload root files/ is a symlink")
    if not payload_root.is_dir():
        raise CompatBundleError("payload root files/ is missing")
    resolved_root = payload_root.resolve()
    files: list[SupplementalFile] = []
    total_size = 0
    for name, expected_sha256 in declarations:
        path = _resolve_payload_file(resolved_root, PurePosixPath(name).parts)
        try:
            actual_sha256, identity = sha256_regular_file(path, MAX_COMPAT_FILE_SIZE)
        except BoundedFileError as exc:
            raise CompatBundleError(
                f"plaintext file unsafe: {name} ({exc.reason})",
            ) from exc
        total_size += identity.size
        if total_size > MAX_COMPAT_TOTAL_SIZE:
            raise CompatBundleError("plaintext total size limit exceeded")
        if actual_sha256 != expected_sha256:
            raise CompatBundleError(f"file SHA-256 mismatch: {name}")
        files.append(
            SupplementalFile(
                name,
                path,
                expected_sha256,
                identity.size,
                identity,
                MAX_COMPAT_FILE_SIZE,
                BlockSource.COMPAT_PLAINTEXT,
            ),
        )
    return tuple(files)


def _resolve_payload_file(root: Path, parts: tuple[str, ...]) -> Path:
    candidate = root
    for part in parts:
        candidate /= part
        if candidate.is_symlink():
            raise CompatBundleError("plaintext path contains a symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise CompatBundleError("plaintext file is missing") from exc
    if not resolved.is_relative_to(root):
        raise CompatBundleError("plaintext file escapes payload root")
    return resolved


def _parse_internal_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    if any(part in {"", ".", ".."} for part in normalized.split("/")):
        raise CompatBundleError(f"unsafe internal path: {value}")
    relative = safe_relative_path(normalized)
    if relative is None:
        raise CompatBundleError(f"unsafe internal path: {value}")
    return str(relative)


def _parse_sha256(value: str, label: str) -> str:
    normalized = value.lower()
    if _SHA256_RE.fullmatch(normalized) is None:
        raise CompatBundleError(f"invalid {label}")
    return normalized


def _claim_path(name: str, claimed: set[str]) -> None:
    key = normalize_internal_name(name)
    if key in claimed:
        raise CompatBundleError(f"duplicate internal path: {name}")
    claimed.add(key)
