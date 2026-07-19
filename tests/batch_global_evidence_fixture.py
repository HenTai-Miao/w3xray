"""Manifest-bound non-empty fixtures for global icon evidence tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from tests.batch_publication_fixture import empty_result, write_empty_publication
from w3xtool.batch_icon_models import IconExportRecord, IconExportState, IconKind
from w3xtool.batch_manifest_models import CONTENT_MANIFEST_NAME, OWNERSHIP_MARKER_NAME
from w3xtool.batch_map_manifest import finalize_map_manifest
from w3xtool.batch_models import MapBatchResult, SourceFingerprint
from w3xtool.batch_reports import format_icon_index_tsv, format_map_summary
from w3xtool.batch_status import (
    PublicationResult,
    derive_batch_axes,
    derive_legacy_map_state,
)
from w3xtool.extraction_ledger import BlockSource, BlockState
from w3xtool.icon_evidence_exports import (
    format_icon_integrity,
    format_unresolved_icon_tsv,
)
from w3xtool.icon_evidence_index import IconEvidenceIndex
from w3xtool.icon_evidence_models import (
    IconDiagnosticFlag,
    IconGapReason,
    IconResolutionLayer,
    ResolvedIconEvidence,
    UnresolvedIconEvidence,
)
from w3xtool.icon_resources import AnonymousIconResource, IconObjectReference


GAP_PATH = r"ReplaceableTextures\CommandButtons\BTNMissing.blp"
NAMED_PATH = r"ReplaceableTextures\CommandButtons\BTNFound.blp"


def publish_nonempty_icon_result(
    index: int,
    fingerprint: SourceFingerprint,
    output_root: str,
    *,
    gap_path: str = GAP_PATH,
    named_path: str = NAMED_PATH,
    named_digest: str = "c" * 64,
    anonymous_digest: str = "d" * 64,
    gap_reason: IconGapReason = IconGapReason.NAMED_RESOURCE_MISSING,
) -> MapBatchResult:
    """Publish one gap, one named payload, and one anonymous payload."""
    relative = f"地图/{index:03d}_{fingerprint.sha256[:8]}"
    destination = Path(output_root, relative)
    destination.mkdir(parents=True, exist_ok=True)
    base = empty_result(fingerprint, relative)
    _ = write_empty_publication(destination, base, f"{index:032x}")
    _remove_metadata(destination)
    evidence, exports = _evidence(
        fingerprint,
        gap_path,
        named_path,
        named_digest,
        anonymous_digest,
        gap_reason,
    )
    result = _result(base, evidence, exports)
    reports = (
        ("地图摘要.txt", format_map_summary(result)),
        ("图标索引.tsv", format_icon_index_tsv(exports)),
        ("图标未解析.tsv", format_unresolved_icon_tsv(evidence)),
        ("图标完整性.txt", format_icon_integrity(evidence, exports)),
    )
    for name, text in reports:
        (destination / name).write_text(text, encoding="utf-8", newline="")
    return finalize_map_manifest(destination, result, f"{index + 100:032x}")


def terminal_result_with_evidence(fingerprint: SourceFingerprint) -> MapBatchResult:
    """Build one failed result that retains non-zero diagnostic counters."""
    base = empty_result(fingerprint, "地图/unused")
    axes = derive_batch_axes(
        PublicationResult.FAILED,
        raw_blocks=0,
        damaged_blocks=0,
        restricted_blocks=0,
        icon_gaps=3,
        current_text_states=(),
        relation_partial_count=0,
        unresolved_endpoint_count=0,
    )
    return replace(
        base,
        output_directory="",
        stage="load/process",
        state=derive_legacy_map_state(axes),
        first_error="fixture failure",
        publication_result=axes.publication,
        archive_integrity=axes.archive,
        knowledge_evidence=axes.knowledge,
        knowledge_gap_reasons=axes.knowledge_reasons,
        valid_icon_reference_count=5,
        resolved_icon_reference_count=1,
        unresolved_icon_count=3,
        unresolved_icon_reference_count=4,
        dependency_fingerprint="",
        manifest_sha256="",
        published_bytes=0,
    )


def _evidence(
    fingerprint: SourceFingerprint,
    gap_path: str,
    named_path: str,
    named_digest: str,
    anonymous_digest: str,
    gap_reason: IconGapReason,
) -> tuple[IconEvidenceIndex, tuple[IconExportRecord, ...]]:
    gap_reference = _reference(fingerprint, gap_path, "A001")
    named_reference = _reference(fingerprint, named_path, "A002")
    anonymous = AnonymousIconResource(
        17,
        b"BLP1anonymous",
        anonymous_digest,
        f"block_000017_{anonymous_digest[:8]}",
        f"{fingerprint.path}#block17",
        BlockSource.ARCHIVE_RECOVERED,
        BlockState.DECODED,
    )
    evidence = IconEvidenceIndex.build(
        resolved=(
            ResolvedIconEvidence(
                named_reference,
                named_path,
                fingerprint.path,
                b"BLP1named",
                named_digest,
                IconResolutionLayer.CURRENT_MAP,
                (),
            ),
        ),
        unresolved=(
            UnresolvedIconEvidence(
                gap_reference,
                gap_reason,
                (IconDiagnosticFlag.HISTORICAL_EVIDENCE_CHECKED,),
                (),
            ),
        ),
        anonymous=(anonymous,),
    )
    exports = (
        _export(
            IconKind.NAMED,
            named_path,
            fingerprint.path,
            None,
            named_digest,
            (named_reference,),
        ),
        _export(
            IconKind.ANONYMOUS, "", anonymous.source_path, 17, anonymous_digest, ()
        ),
    )
    return evidence, exports


def _export(
    kind: IconKind,
    path: str,
    source: str,
    block: int | None,
    digest: str,
    objects: tuple[IconObjectReference, ...],
) -> IconExportRecord:
    return IconExportRecord(
        kind,
        path,
        path,
        source,
        block,
        digest,
        "fixture.blp",
        "fixture.png",
        True,
        True,
        IconExportState.COMPLETE,
        "",
        objects,
        IconResolutionLayer.CURRENT_MAP if kind is IconKind.NAMED else None,
    )


def _reference(
    fingerprint: SourceFingerprint,
    path: str,
    rawcode: str,
) -> IconObjectReference:
    return IconObjectReference(
        "技能",
        rawcode,
        "测试技能",
        "AHbz",
        fingerprint.path,
        fingerprint.sha256,
        "root",
        "aart",
        "图标 - 普通",
        "icon",
        "war3map.w3a",
        "",
        path,
        path,
    )


def _result(
    base: MapBatchResult,
    evidence: IconEvidenceIndex,
    exports: tuple[IconExportRecord, ...],
) -> MapBatchResult:
    axes = derive_batch_axes(
        PublicationResult.PUBLISHED,
        raw_blocks=0,
        damaged_blocks=0,
        restricted_blocks=0,
        icon_gaps=1,
        current_text_states=(),
        relation_partial_count=0,
        unresolved_endpoint_count=0,
    )
    return replace(
        base,
        state=derive_legacy_map_state(axes),
        archive_integrity=axes.archive,
        knowledge_evidence=axes.knowledge,
        knowledge_gap_reasons=axes.knowledge_reasons,
        named_icon_count=1,
        anonymous_icon_count=1,
        original_written_count=len(exports),
        png_written_count=len(exports),
        valid_icon_reference_count=2,
        resolved_icon_reference_count=1,
        unresolved_icon_count=1,
        unresolved_icon_reference_count=1,
    )


def _remove_metadata(root: Path) -> None:
    (root / CONTENT_MANIFEST_NAME).unlink()
    (root / OWNERSHIP_MARKER_NAME).unlink()
