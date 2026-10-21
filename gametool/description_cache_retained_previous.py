"""Captured-byte-only semantic validation for retained previous caches."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

from .description_cache import format_description_cache_tsv, load_description_cache_text
from .description_cache_models import DescriptionCache
from .description_cache_owned_schema import (
    TRUSTED_DESCRIPTION_CACHE_MANIFEST,
    TRUSTED_DESCRIPTION_CACHE_MARKER,
    TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY,
    TrustedCacheSchemaError,
    parse_trusted_cache_manifest,
    parse_trusted_cache_marker,
)
from .description_cache_retained_integrity_models import (
    RetainedArtifactValidation,
    RetainedTreeProof,
)
from .trusted_description_cache_models import (
    TrustedDescriptionCacheError,
    TrustedDescriptionCachePayloads,
)
from .trusted_description_cache_tables import (
    DescriptionCacheSourceRecord,
    TrustedTableError,
    parse_source_level,
    parse_source_manifest,
    validate_rejection_table,
)


_OWNED_NAMES: Final = frozenset(TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY)


def classify_retained_previous(
    path: Path,
    proof: RetainedTreeProof,
) -> tuple[RetainedArtifactValidation, str | None]:
    """Classify one complete previous tree without opening any pathname."""
    paths = tuple(entry.relative_path for entry in proof.entries)
    if (
        proof.file_count != len(_OWNED_NAMES)
        or proof.entry_count != len(_OWNED_NAMES)
        or frozenset(paths) != _OWNED_NAMES
        or any("/" in value for value in paths)
    ):
        return RetainedArtifactValidation.INVALID_PREVIOUS, _inventory_problem(paths)
    payloads = dict(proof.payloads)
    try:
        validate_retained_payloads(
            TrustedDescriptionCachePayloads(
                path,
                payloads[TRUSTED_DESCRIPTION_CACHE_MARKER],
                payloads[TRUSTED_DESCRIPTION_CACHE_MANIFEST],
                payloads["可信描述缓存.tsv"],
                payloads["来源清单.tsv"],
                payloads["可信缓存迁移拒绝.tsv"],
            )
        )
    except KeyError, TrustedDescriptionCacheError:
        return RetainedArtifactValidation.INVALID_PREVIOUS, None
    return RetainedArtifactValidation.VALID_CACHE, None


def validate_retained_payloads(payloads: TrustedDescriptionCachePayloads) -> None:
    """Verify all internal five-leaf bindings using only captured bytes."""
    try:
        marker_digest = parse_trusted_cache_marker(payloads.marker.decode("ascii"))
        manifest = parse_trusted_cache_manifest(payloads.manifest.decode("utf-8"))
    except (UnicodeError, TrustedCacheSchemaError) as exc:
        raise TrustedDescriptionCacheError(f"invalid owned metadata: {exc}") from exc
    manifest_digest = hashlib.sha256(payloads.manifest).hexdigest()
    if marker_digest != manifest_digest:
        raise TrustedDescriptionCacheError("manifest hash mismatch")
    source_root = Path(manifest.source_root)
    if not source_root.is_absolute() or ".." in source_root.parts:
        raise TrustedDescriptionCacheError("manifest source root is not absolute")
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
    cache = _parse_cache(payloads)
    source_digest = hashlib.sha256(payloads.source_manifest).hexdigest()
    if any(entry.source_manifest_sha256 != source_digest for entry in cache.entries):
        raise TrustedDescriptionCacheError("cache source-manifest binding mismatch")
    try:
        records = parse_source_manifest(payloads.source_manifest)
        validate_rejection_table(payloads.rejections)
        _validate_internal_source_bindings(cache, records)
    except TrustedTableError as exc:
        raise TrustedDescriptionCacheError(str(exc)) from exc


def _parse_cache(payloads: TrustedDescriptionCachePayloads) -> DescriptionCache:
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
    return cache


def _validate_internal_source_bindings(
    cache: DescriptionCache,
    records: tuple[DescriptionCacheSourceRecord, ...],
) -> None:
    identities = {
        (
            row.category,
            row.base_id,
            row.role,
            row.level_text,
            row.source_map_sha256,
            row.report_path,
            row.report_row_number,
        )
        for row in records
    }
    if len(identities) != len(records):
        raise TrustedTableError("duplicate source manifest identity")
    bound_keys: set[tuple[str, str, str, int | None, str, str]] = set()
    for record in records:
        level = parse_source_level(record.level_text)
        entries = cache.lookup(record.category, record.base_id, record.role, level)
        if len(entries) != 1:
            raise TrustedTableError("source manifest row is not bound to cache")
        entry = entries[0]
        expected_path = f"{record.report_path}#base:{record.base_id}"
        if (
            entry.source_map_sha256 != record.source_map_sha256
            or entry.source_path != expected_path
        ):
            raise TrustedTableError("source manifest row binding mismatch")
        bound_keys.add(
            (
                entry.category,
                entry.base_id,
                entry.role,
                entry.level,
                entry.source_map_sha256,
                entry.source_path,
            )
        )
    cache_keys = {
        (
            entry.category,
            entry.base_id,
            entry.role,
            entry.level,
            entry.source_map_sha256,
            entry.source_path,
        )
        for entry in cache.entries
    }
    if bound_keys != cache_keys:
        raise TrustedTableError("cache entry has no exact source record")


def _inventory_problem(paths: tuple[str, ...]) -> str | None:
    missing = tuple(
        sorted(_OWNED_NAMES - frozenset(paths), key=lambda value: value.encode("utf-8"))
    )
    if missing:
        return missing[0]
    extras = tuple(
        sorted(
            (value for value in paths if value not in _OWNED_NAMES),
            key=lambda value: value.encode("utf-8"),
        )
    )
    return None if not extras else extras[0]


__all__ = ("classify_retained_previous", "validate_retained_payloads")
