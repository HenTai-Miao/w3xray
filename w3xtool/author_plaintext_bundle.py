"""Verified author plaintext overlays for otherwise unreadable map containers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
import mmap
from pathlib import Path
import re
from typing import Final, override

from .bounded_file import (
    BoundedFileError,
    FileIdentity,
    read_bounded_regular_file,
    sha256_regular_file,
)
from .mpq import MPQArchive
from .safe_output import safe_relative_path

MANIFEST_NAME: Final = "w3xray-author-bundle.tsv"
MAX_BUNDLE_FILE_SIZE: Final = 40 * 1024 * 1024
MAX_BUNDLE_TOTAL_SIZE: Final = 512 * 1024 * 1024
MAX_BUNDLE_FILES: Final = 10_000
MAX_MANIFEST_SIZE: Final = 2 * 1024 * 1024
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class AuthorBundleError(OSError):
    reason: str

    @override
    def __str__(self) -> str:
        return f"author plaintext bundle rejected: {self.reason}"


@dataclass(frozen=True, slots=True)
class AuthorBundleFile:
    name: str
    path: Path
    sha256: str
    size: int
    identity: FileIdentity


@dataclass(frozen=True, slots=True)
class AuthorPlaintextBundle:
    source_sha256: str
    files: tuple[AuthorBundleFile, ...]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.files)

    def has_file(self, name: str) -> bool:
        key = _normalize_name(name)
        return any(_normalize_name(item.name) == key for item in self.files)

    def read_file(self, name: str) -> bytes:
        key = _normalize_name(name)
        for item in self.files:
            if _normalize_name(item.name) != key:
                continue
            try:
                payload, _identity = read_bounded_regular_file(
                    item.path,
                    MAX_BUNDLE_FILE_SIZE,
                    expected=item.identity,
                )
            except BoundedFileError as exc:
                raise AuthorBundleError(
                    f"plaintext changed after validation: {item.name} ({exc.reason})",
                ) from exc
            if len(payload) != item.size or hashlib.sha256(payload).hexdigest() != item.sha256:
                raise AuthorBundleError(f"plaintext changed after validation: {item.name}")
            return payload
        raise FileNotFoundError(name)


class PlaintextOverlayArchive:
    """Expose verified plaintext before an optional underlying MPQ archive."""

    def __init__(
        self,
        source_path: str,
        bundle: AuthorPlaintextBundle,
        base: MPQArchive | None,
    ) -> None:
        self.path: str = source_path
        self._bundle: AuthorPlaintextBundle = bundle
        self._base: MPQArchive | None = base
        self._data: bytes | mmap.mmap = b"" if base is None else base._data

    @property
    def author_bundle_files(self) -> tuple[str, ...]:
        return self._bundle.names

    def has_file(self, name: str) -> bool:
        return self._bundle.has_file(name) or (
            self._base is not None and self._base.has_file(name)
        )

    def read_file(self, name: str) -> bytes:
        if self._bundle.has_file(name):
            return self._bundle.read_file(name)
        if self._base is None:
            raise FileNotFoundError(name)
        return self._base.read_file(name)

    def list_files(self) -> list[str]:
        names = list(self._base.list_files()) if self._base is not None else []
        seen = {_normalize_name(name) for name in names}
        for name in self._bundle.names:
            if _normalize_name(name) not in seen:
                names.append(name)
                seen.add(_normalize_name(name))
        return names

    def close(self) -> None:
        if self._base is not None:
            self._base.close()
        self._data = b""


def load_author_plaintext_bundle(
    root: str | Path,
    source_path: str | Path,
) -> AuthorPlaintextBundle:
    """Parse, bind, and hash-check an author plaintext bundle."""
    bundle_root = Path(root)
    manifest_path = bundle_root / MANIFEST_NAME
    try:
        manifest, _identity = read_bounded_regular_file(manifest_path, MAX_MANIFEST_SIZE)
    except BoundedFileError as exc:
        raise AuthorBundleError(f"missing or oversized {MANIFEST_NAME}: {exc.reason}") from exc
    try:
        lines = manifest.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise AuthorBundleError(f"manifest unreadable: {exc}") from exc
    if not lines:
        raise AuthorBundleError(f"missing or oversized {MANIFEST_NAME}")
    if len(lines) < 2 or lines[0] != "W3XRAY-AUTHOR-BUNDLE\t1":
        raise AuthorBundleError("unsupported manifest header")
    source_parts = lines[1].split("\t")
    if len(source_parts) != 2 or source_parts[0] != "source_sha256":
        raise AuthorBundleError("missing source SHA256")
    expected_source_hash = _parse_sha256(source_parts[1], "source SHA256")
    actual_source_hash = _sha256_file(Path(source_path))
    if actual_source_hash != expected_source_hash:
        raise AuthorBundleError("source SHA256 mismatch")
    files = _parse_file_rows(bundle_root, lines[2:])
    return AuthorPlaintextBundle(expected_source_hash, files)


def _parse_file_rows(root: Path, lines: list[str]) -> tuple[AuthorBundleFile, ...]:
    if len(lines) > MAX_BUNDLE_FILES:
        raise AuthorBundleError("too many plaintext files")
    payload_root: Path | None = None
    files: list[AuthorBundleFile] = []
    seen: set[str] = set()
    total_size = 0
    for line in lines:
        parts = line.split("\t")
        if len(parts) != 3 or parts[0] != "file":
            raise AuthorBundleError("invalid file manifest row")
        relative = safe_relative_path(parts[1])
        if relative is None:
            raise AuthorBundleError(f"unsafe internal path: {parts[1]}")
        key = _normalize_name(str(relative))
        if key in seen:
            raise AuthorBundleError(f"duplicate internal path: {parts[1]}")
        expected_hash = _parse_sha256(parts[2], f"file SHA256: {parts[1]}")
        if payload_root is None:
            payload_root = _resolve_payload_root(root)
        path = _resolve_payload_file(payload_root, relative.parts)
        if path is None:
            raise AuthorBundleError(f"plaintext file missing or escapes root: {parts[1]}")
        try:
            actual_hash, identity = sha256_regular_file(path, MAX_BUNDLE_FILE_SIZE)
        except BoundedFileError as exc:
            raise AuthorBundleError(f"plaintext file unsafe: {parts[1]} ({exc.reason})") from exc
        size = identity.size
        total_size += size
        if size > MAX_BUNDLE_FILE_SIZE or total_size > MAX_BUNDLE_TOTAL_SIZE:
            raise AuthorBundleError(f"plaintext size limit exceeded: {parts[1]}")
        if actual_hash != expected_hash:
            raise AuthorBundleError(f"file SHA256 mismatch: {parts[1]}")
        files.append(AuthorBundleFile(str(relative), path, expected_hash, size, identity))
        seen.add(key)
    return tuple(files)


def _resolve_payload_root(root: Path) -> Path:
    payload_root = root / "files"
    if payload_root.is_symlink():
        raise AuthorBundleError("payload root files/ is a symlink")
    if not payload_root.is_dir():
        raise AuthorBundleError("payload root files/ is missing")
    return payload_root.resolve()


def _parse_sha256(value: str, label: str) -> str:
    normalized = value.lower()
    if _SHA256_RE.fullmatch(normalized) is None:
        raise AuthorBundleError(f"invalid {label}")
    return normalized


def _sha256_file(path: Path) -> str:
    try:
        digest, _identity = sha256_regular_file(path)
    except BoundedFileError as exc:
        raise AuthorBundleError(f"cannot hash {path.name}: {exc.reason}") from exc
    return digest


def _resolve_payload_file(root: Path, parts: tuple[str, ...]) -> Path | None:
    candidate = root
    for part in parts:
        candidate /= part
        if candidate.is_symlink():
            return None
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None
    if not resolved.is_relative_to(root):
        return None
    return resolved


def _normalize_name(name: str) -> str:
    return name.replace("\\", "/").lstrip("/").lower()
