"""Shared semantic proof for descriptor-read trusted-cache bytes."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .description_cache import (
    format_description_cache_tsv,
    load_description_cache_text,
)
from .description_cache_owned_schema import (
    TrustedCacheSchemaError,
    parse_trusted_cache_manifest,
    parse_trusted_cache_marker,
)
from .trusted_description_cache_models import (
    TrustedDescriptionCacheError,
    TrustedDescriptionCachePayloads,
    VerifiedDescriptionCache,
)
from .trusted_description_cache_sources import (
    TrustedSourceError,
    validate_rejection_table,
    validate_source_manifest,
)
from .trusted_description_cache_tables import TrustedTableError


def validate_trusted_description_cache_payloads(
    payloads: TrustedDescriptionCachePayloads,
) -> VerifiedDescriptionCache:
    """Run one marker, manifest, payload, source, and TSV proof."""
    try:
        marker_digest = parse_trusted_cache_marker(payloads.marker.decode("ascii"))
    except (UnicodeError, TrustedCacheSchemaError) as exc:
        raise TrustedDescriptionCacheError(f"invalid owned metadata: {exc}") from exc
    manifest_digest = hashlib.sha256(payloads.manifest).hexdigest()
    if marker_digest != manifest_digest:
        raise TrustedDescriptionCacheError("manifest hash mismatch")
    try:
        manifest = parse_trusted_cache_manifest(payloads.manifest.decode("utf-8"))
    except (UnicodeError, TrustedCacheSchemaError) as exc:
        raise TrustedDescriptionCacheError(f"invalid owned metadata: {exc}") from exc
    source_root = _canonical_source_root(Path(manifest.source_root))
    owned_payloads = {
        "可信描述缓存.tsv": payloads.cache,
        "来源清单.tsv": payloads.source_manifest,
        "可信缓存迁移拒绝.tsv": payloads.rejections,
    }
    for artifact in manifest.artifacts:
        payload = owned_payloads[artifact.name]
        if (
            len(payload) != artifact.size
            or hashlib.sha256(payload).hexdigest() != artifact.sha256
        ):
            raise TrustedDescriptionCacheError(
                f"payload hash mismatch: {artifact.name}"
            )
    try:
        cache_text = payloads.cache.decode("utf-8")
    except UnicodeError as exc:
        raise TrustedDescriptionCacheError("cache payload is not UTF-8") from exc
    cache = load_description_cache_text(
        cache_text,
        str(payloads.root / "可信描述缓存.tsv"),
    )
    if cache.diagnostics or format_description_cache_tsv(cache) != cache_text:
        raise TrustedDescriptionCacheError(
            "cache payload schema or round-trip mismatch"
        )
    source_digest = hashlib.sha256(payloads.source_manifest).hexdigest()
    if any(entry.source_manifest_sha256 != source_digest for entry in cache.entries):
        raise TrustedDescriptionCacheError("cache source-manifest binding mismatch")
    try:
        validate_source_manifest(payloads.source_manifest, cache, source_root)
        validate_rejection_table(payloads.rejections)
    except (TrustedSourceError, TrustedTableError) as exc:
        raise TrustedDescriptionCacheError(str(exc)) from exc
    return VerifiedDescriptionCache(cache, manifest_digest, manifest.content_sha256)


def _canonical_source_root(path: Path) -> Path:
    absolute = path.expanduser().absolute()
    if absolute.is_symlink() or not absolute.is_dir():
        raise TrustedDescriptionCacheError(
            "source root is not a regular directory or is a symlink"
        )
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise TrustedDescriptionCacheError(f"source root is unreadable: {exc}") from exc
    if resolved != absolute:
        raise TrustedDescriptionCacheError("source root traverses a symlink")
    return resolved


__all__ = ("validate_trusted_description_cache_payloads",)
