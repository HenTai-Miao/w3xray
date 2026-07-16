"""Manifest-valid fixtures for structured icon report validation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Final

from tests.batch_publication_fixture import empty_result, write_empty_publication
from tests.real_map_text_acceptance import read_tsv_text
from w3xtool.batch_icon_export import IconExportRecord, IconExportState, IconKind
from w3xtool.batch_manifest_models import (
    CONTENT_MANIFEST_NAME,
    OWNERSHIP_MARKER_NAME,
    PublicationValidation,
)
from w3xtool.batch_manifest_validation import verify_map_publication
from w3xtool.batch_map_manifest import finalize_map_manifest
from w3xtool.batch_models import MapBatchResult, SourceFingerprint
from w3xtool.batch_reports import format_icon_index_tsv
from w3xtool.batch_tsv import format_tsv_rows
from w3xtool.icon_evidence_exports import (
    format_icon_integrity,
    format_unresolved_icon_tsv,
    normalized_icon_gap_count,
)
from w3xtool.icon_evidence_index import IconEvidenceIndex
from w3xtool.icon_evidence_models import (
    IconGapReason,
    IconResolutionLayer,
    ResolvedIconEvidence,
    UnresolvedIconEvidence,
)
from w3xtool.icon_resources import IconObjectReference

_DIGEST: Final = "a" * 64
_PATH: Final = r"Icons\Missing.blp"


def validate_icon_publication(
    root: Path,
    *,
    reference_json: str | None = None,
    duplicate_gap_row: bool = False,
    resolved_conflict: bool = False,
    resolved_other_map: bool = False,
) -> PublicationValidation:
    """Publish chosen icon reports and run the real publication validator."""
    fingerprint = SourceFingerprint("/maps/map.w3x", 3, 4, _DIGEST)
    base = empty_result(fingerprint, "地图/001_map_aaaaaaaa")
    _ = write_empty_publication(root, base, "1" * 32)
    _remove_metadata(root)
    index = _icon_index(resolved_conflict, resolved_other_map)
    exports = (_failed_export(index.resolved[0].reference),) if index.resolved else ()
    gap_text = format_unresolved_icon_tsv(index)
    if reference_json is not None:
        gap_text = _replace_reference_json(gap_text, reference_json)
    if duplicate_gap_row:
        table = read_tsv_text(gap_text)
        gap_text = format_tsv_rows((table.header, *table.rows, *table.rows))
    (root / "图标未解析.tsv").write_text(gap_text, encoding="utf-8", newline="")
    (root / "图标索引.tsv").write_text(
        format_icon_index_tsv(exports), encoding="utf-8", newline=""
    )
    (root / "图标完整性.txt").write_text(
        format_icon_integrity(index, exports), encoding="utf-8"
    )
    finalized = finalize_map_manifest(
        root,
        _icon_result(base, index, exports),
        "2" * 32,
    )
    return verify_map_publication(root, finalized)


def validate_missing_gap_publication(root: Path) -> PublicationValidation:
    """Publish a manifest that omits the required unresolved report."""
    base = empty_result(
        SourceFingerprint("/maps/map.w3x", 3, 4, _DIGEST),
        "地图/001_map_aaaaaaaa",
    )
    _ = write_empty_publication(root, base, "1" * 32)
    _remove_metadata(root)
    (root / "图标未解析.tsv").unlink()
    result = finalize_map_manifest(root, base, "2" * 32)
    return verify_map_publication(root, result)


def _icon_index(
    resolved_conflict: bool,
    resolved_other_map: bool,
) -> IconEvidenceIndex:
    reference = _reference()
    resolved_reference = (
        _reference(map_path="other-child.w3x", digest="c" * 64)
        if resolved_other_map
        else reference
    )
    resolved = (
        (
            ResolvedIconEvidence(
                resolved_reference,
                _PATH,
                "map.w3x",
                b"BLP1resolved",
                "b" * 64,
                IconResolutionLayer.CURRENT_MAP,
                (),
            ),
        )
        if resolved_conflict or resolved_other_map
        else ()
    )
    return IconEvidenceIndex.build(
        resolved=resolved,
        unresolved=(
            UnresolvedIconEvidence(
                reference,
                IconGapReason.NAMED_RESOURCE_MISSING,
                (),
                (),
            ),
        ),
    )


def _icon_result(
    base: MapBatchResult,
    index: IconEvidenceIndex,
    exports: tuple[IconExportRecord, ...],
) -> MapBatchResult:
    gaps = normalized_icon_gap_count(index)
    original_failures = sum(not item.original_written for item in exports)
    png_failures = sum(
        item.original_written and not item.png_written for item in exports
    )
    return replace(
        base,
        named_icon_count=len(exports),
        icon_failure_count=gaps + original_failures + png_failures,
        valid_icon_reference_count=len(index.resolved) + len(index.unresolved),
        resolved_icon_reference_count=len(index.resolved),
        unresolved_icon_count=gaps,
        unresolved_icon_reference_count=len(index.unresolved),
        original_write_failure_count=original_failures,
        png_failure_count=png_failures,
    )


def _failed_export(reference: IconObjectReference) -> IconExportRecord:
    return IconExportRecord(
        IconKind.NAMED,
        _PATH,
        _PATH,
        "map.w3x",
        None,
        "b" * 64,
        "",
        "",
        False,
        False,
        IconExportState.ORIGINAL_FAILED,
        "fixture write failure",
        (reference,),
        IconResolutionLayer.CURRENT_MAP,
    )


def _reference(
    *,
    map_path: str = "map.w3x",
    digest: str = _DIGEST,
) -> IconObjectReference:
    return IconObjectReference(
        "技能",
        "A001",
        "暴风雪",
        "AHbz",
        map_path,
        digest,
        map_path,
        "aart",
        "图标 - 普通",
        "icon",
        "war3map.w3a",
        "",
        _PATH,
        _PATH,
    )


def _replace_reference_json(report: str, reference_json: str) -> str:
    table = read_tsv_text(report)
    row = list(table.rows[0])
    row[table.header.index("引用集合")] = reference_json
    return format_tsv_rows((table.header, tuple(row)))


def _remove_metadata(root: Path) -> None:
    (root / CONTENT_MANIFEST_NAME).unlink()
    (root / OWNERSHIP_MARKER_NAME).unlink()
