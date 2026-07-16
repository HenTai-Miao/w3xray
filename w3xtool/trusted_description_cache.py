"""Validate owned, hash-bound trusted description-cache generations."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Final

from .bounded_file import read_bounded_regular_file
from .description_cache import (
    format_description_cache_tsv,
    load_description_cache_text,
)
from .description_cache_models import DescriptionCache
from .description_cache_owned_schema import (
    TRUSTED_DESCRIPTION_CACHE_FILES,
    TRUSTED_DESCRIPTION_CACHE_MANIFEST,
    TRUSTED_DESCRIPTION_CACHE_MARKER,
    TRUSTED_DESCRIPTION_CACHE_SCHEMA,
    TrustedCacheSchemaError,
    parse_trusted_cache_manifest,
    parse_trusted_cache_marker,
)
from .trusted_description_cache_sources import (
    TrustedSourceError,
    validate_rejection_table,
    validate_source_manifest,
)
from .trusted_description_cache_tables import TrustedTableError


_MAX_METADATA_BYTES: Final = 4 * 1024 * 1024
_MAX_PAYLOAD_BYTES: Final = 512 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class VerifiedDescriptionCache:
    """A fully rehashed cache and its two generation identities."""

    cache: DescriptionCache
    manifest_sha256: str
    content_sha256: str


class TrustedDescriptionCacheError(OSError):
    """An owned trusted-description cache failed complete validation."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    def __str__(self) -> str:
        return self.detail


def load_trusted_description_cache(root: Path) -> VerifiedDescriptionCache:
    """Return a cache only after validating every payload and source proof."""
    directory = _canonical_directory(root, "trusted cache root")
    _require_exact_inventory(directory)
    marker_bytes = _read_stable(
        directory / TRUSTED_DESCRIPTION_CACHE_MARKER,
        _MAX_METADATA_BYTES,
    )
    manifest_bytes = _read_stable(
        directory / TRUSTED_DESCRIPTION_CACHE_MANIFEST,
        _MAX_METADATA_BYTES,
    )
    try:
        marker_digest = parse_trusted_cache_marker(marker_bytes.decode("ascii"))
    except (UnicodeError, TrustedCacheSchemaError) as exc:
        raise TrustedDescriptionCacheError(f"invalid owned metadata: {exc}") from exc
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    if marker_digest != manifest_digest:
        raise TrustedDescriptionCacheError("manifest hash mismatch")
    try:
        manifest = parse_trusted_cache_manifest(manifest_bytes.decode("utf-8"))
    except (UnicodeError, TrustedCacheSchemaError) as exc:
        raise TrustedDescriptionCacheError(f"invalid owned metadata: {exc}") from exc
    source_root = _canonical_directory(Path(manifest.source_root), "source root")
    payloads: dict[str, bytes] = {}
    for artifact in manifest.artifacts:
        payload = _read_stable(directory / artifact.name, _MAX_PAYLOAD_BYTES)
        if (
            len(payload) != artifact.size
            or hashlib.sha256(payload).hexdigest() != artifact.sha256
        ):
            raise TrustedDescriptionCacheError(
                f"payload hash mismatch: {artifact.name}"
            )
        payloads[artifact.name] = payload
    cache_payload = payloads["可信描述缓存.tsv"]
    try:
        cache_text = cache_payload.decode("utf-8")
    except UnicodeError as exc:
        raise TrustedDescriptionCacheError("cache payload is not UTF-8") from exc
    cache = load_description_cache_text(cache_text, str(directory / "可信描述缓存.tsv"))
    if cache.diagnostics or format_description_cache_tsv(cache) != cache_text:
        raise TrustedDescriptionCacheError(
            "cache payload schema or round-trip mismatch"
        )
    source_payload = payloads["来源清单.tsv"]
    source_digest = hashlib.sha256(source_payload).hexdigest()
    if any(entry.source_manifest_sha256 != source_digest for entry in cache.entries):
        raise TrustedDescriptionCacheError("cache source-manifest binding mismatch")
    try:
        validate_source_manifest(source_payload, cache, source_root)
        validate_rejection_table(payloads["可信缓存迁移拒绝.tsv"])
    except (TrustedSourceError, TrustedTableError) as exc:
        raise TrustedDescriptionCacheError(str(exc)) from exc
    return VerifiedDescriptionCache(cache, manifest_digest, manifest.content_sha256)


def _canonical_directory(path: Path, label: str) -> Path:
    absolute = path.expanduser().absolute()
    if absolute.is_symlink() or not absolute.is_dir():
        raise TrustedDescriptionCacheError(
            f"{label} is not a regular directory or is a symlink"
        )
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise TrustedDescriptionCacheError(f"{label} is unreadable: {exc}") from exc
    if resolved != absolute:
        raise TrustedDescriptionCacheError(f"{label} traverses a symlink")
    return resolved


def _require_exact_inventory(root: Path) -> None:
    expected = {
        *TRUSTED_DESCRIPTION_CACHE_FILES,
        TRUSTED_DESCRIPTION_CACHE_MANIFEST,
        TRUSTED_DESCRIPTION_CACHE_MARKER,
    }
    try:
        entries = tuple(root.iterdir())
    except OSError as exc:
        raise TrustedDescriptionCacheError(f"cannot list trusted cache: {exc}") from exc
    if {entry.name for entry in entries} != expected or any(
        entry.is_symlink() or not entry.is_file() for entry in entries
    ):
        raise TrustedDescriptionCacheError("owned cache is partial or has unsafe files")


def _read_stable(path: Path, maximum: int) -> bytes:
    try:
        first, identity = read_bounded_regular_file(path, maximum)
        second, _again = read_bounded_regular_file(path, maximum, expected=identity)
    except OSError as exc:
        raise TrustedDescriptionCacheError(
            f"cannot read owned regular file {path}: {exc}"
        ) from exc
    if first != second:
        raise TrustedDescriptionCacheError(f"owned file changed while reading: {path}")
    return first


__all__ = (
    "TRUSTED_DESCRIPTION_CACHE_FILES",
    "TRUSTED_DESCRIPTION_CACHE_MANIFEST",
    "TRUSTED_DESCRIPTION_CACHE_MARKER",
    "TRUSTED_DESCRIPTION_CACHE_SCHEMA",
    "TrustedDescriptionCacheError",
    "VerifiedDescriptionCache",
    "load_trusted_description_cache",
)
