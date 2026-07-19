"""Portable exact-byte fixtures for owned trusted-description caches."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path

from tests.description_cache_migration_fixture import (
    LEGACY_RELATIVE,
    SOURCE_DIGEST,
    candidate,
    legacy_client_fill,
    write_legacy_inputs,
)
from w3xtool.batch_tsv import format_tsv_rows
from w3xtool.description_cache import (
    format_description_cache_tsv,
    load_description_cache_text,
)
from w3xtool.description_cache_migration_exports import (
    format_migration_payloads,
)
from w3xtool.description_cache_migration_models import (
    LegacySourceReport,
    LegacyStateResult,
    ProvenDescriptionCandidate,
)
from w3xtool.description_cache_migration_rows import (
    parse_legacy_cache,
    parse_legacy_report,
    prove_candidate,
)
from w3xtool.description_cache_models import DescriptionCache
from w3xtool.description_cache_owned_schema import (
    TRUSTED_DESCRIPTION_CACHE_FILES,
    TRUSTED_DESCRIPTION_CACHE_MANIFEST,
    TRUSTED_DESCRIPTION_CACHE_MARKER,
    TRUSTED_DESCRIPTION_CACHE_SCHEMA,
    TrustedCacheArtifact,
    TrustedCacheManifest,
    format_trusted_cache_manifest,
    format_trusted_cache_marker,
    parse_trusted_cache_manifest,
    trusted_content_sha256,
)
from w3xtool.description_cache_schema import DESCRIPTION_CACHE_SOURCE_HEADER
from w3xtool.trusted_description_cache import load_trusted_description_cache
from w3xtool.trusted_description_cache_tables import parse_source_manifest


def published_cache(root: Path, *, raw: str = "原版说明") -> Path:
    """Materialize one exact owned cache and return its destination root."""
    legacy_output, legacy_cache = write_legacy_inputs(
        root,
        cache_rows=(candidate(raw=raw),),
        report_rows=(
            legacy_client_fill(
                raw_description=raw,
                readable_description=raw,
            ),
        ),
    )
    report = legacy_output / LEGACY_RELATIVE / "对象描述.tsv"
    report_payload = report.read_bytes()
    state = LegacyStateResult(
        "/maps/source.w3x",
        SOURCE_DIGEST,
        LEGACY_RELATIVE,
        "published",
    )
    candidates = parse_legacy_cache(legacy_cache.read_bytes(), str(legacy_cache))
    reports = (
        LegacySourceReport(
            state,
            report,
            hashlib.sha256(report_payload).hexdigest(),
            parse_legacy_report(report_payload, str(report)),
        ),
    )
    proven = prove_candidate(candidates[0], reports)
    if not isinstance(proven, ProvenDescriptionCandidate):
        raise AssertionError(f"fixture candidate was rejected: {proven}")

    output = root / "trusted"
    output.mkdir()
    payloads = format_migration_payloads((proven,), ())
    for name, text in payloads.items():
        (output / name).write_text(text, encoding="utf-8", newline="")
    artifacts = tuple(
        sorted(
            (
                TrustedCacheArtifact(
                    name,
                    len(text.encode("utf-8")),
                    hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
                for name, text in payloads.items()
            ),
            key=lambda item: item.name.casefold(),
        )
    )
    manifest = TrustedCacheManifest(
        TRUSTED_DESCRIPTION_CACHE_SCHEMA,
        str(legacy_output),
        artifacts,
        trusted_content_sha256(artifacts),
    )
    manifest_text = format_trusted_cache_manifest(manifest)
    (output / TRUSTED_DESCRIPTION_CACHE_MANIFEST).write_text(
        manifest_text,
        encoding="utf-8",
        newline="",
    )
    manifest_digest = hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()
    (output / TRUSTED_DESCRIPTION_CACHE_MARKER).write_text(
        format_trusted_cache_marker(manifest_digest),
        encoding="ascii",
        newline="",
    )
    assert len(load_trusted_description_cache(output).cache.entries) == 1
    return output


def rewrite_source_record(
    root: Path,
    *,
    report_path: str | None = None,
    report_sha256: str | None = None,
    report_row_number: int | None = None,
) -> None:
    """Rewrite one fixture source record before restoring all hash bindings."""
    source = root / "来源清单.tsv"
    records = parse_source_manifest(source.read_bytes())
    if len(records) != 1:
        raise AssertionError("fixture must contain exactly one source record")
    record = records[0]
    row = (
        record.category,
        record.base_id,
        record.role,
        record.level_text,
        record.source_map_sha256,
        record.report_path if report_path is None else report_path,
        record.report_sha256 if report_sha256 is None else report_sha256,
        str(
            record.report_row_number if report_row_number is None else report_row_number
        ),
        record.report_row_sha256,
        record.source_label,
    )
    source.write_text(
        format_tsv_rows((DESCRIPTION_CACHE_SOURCE_HEADER, row)),
        encoding="utf-8",
        newline="",
    )


def resign_source_evidence(root: Path) -> None:
    """Rebind a changed source table into cache rows and owned metadata."""
    source_digest = hashlib.sha256((root / "来源清单.tsv").read_bytes()).hexdigest()
    cache_path = root / "可信描述缓存.tsv"
    cache = load_description_cache_text(
        cache_path.read_text(encoding="utf-8"), str(cache_path)
    )
    if cache.diagnostics:
        raise AssertionError("fixture cache must parse before re-signing")
    rebound = DescriptionCache.build(
        replace(entry, source_manifest_sha256=source_digest) for entry in cache.entries
    )
    cache_path.write_text(
        format_description_cache_tsv(rebound),
        encoding="utf-8",
        newline="",
    )
    resign_owned_cache(root)


def resign_owned_cache(root: Path) -> None:
    """Recompute the outer manifest and marker for a malicious fixture."""
    manifest_path = root / TRUSTED_DESCRIPTION_CACHE_MANIFEST
    previous = parse_trusted_cache_manifest(manifest_path.read_text(encoding="utf-8"))
    artifacts = tuple(
        sorted(
            (
                TrustedCacheArtifact(
                    name,
                    len(payload),
                    hashlib.sha256(payload).hexdigest(),
                )
                for name in TRUSTED_DESCRIPTION_CACHE_FILES
                for payload in ((root / name).read_bytes(),)
            ),
            key=lambda item: item.name.casefold(),
        )
    )
    manifest = TrustedCacheManifest(
        previous.schema_version,
        previous.source_root,
        artifacts,
        trusted_content_sha256(artifacts),
    )
    manifest_text = format_trusted_cache_manifest(manifest)
    manifest_path.write_text(manifest_text, encoding="utf-8", newline="")
    digest = hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()
    (root / TRUSTED_DESCRIPTION_CACHE_MARKER).write_text(
        format_trusted_cache_marker(digest),
        encoding="ascii",
        newline="",
    )
