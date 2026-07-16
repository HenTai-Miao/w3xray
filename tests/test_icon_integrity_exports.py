"""Icon evidence count-reconciliation report tests."""

from __future__ import annotations

from w3xtool.batch_icon_export import IconExportRecord, IconExportState, IconKind
from w3xtool.extraction_ledger import BlockSource, BlockState
from w3xtool.icon_evidence_exports import format_icon_integrity
from w3xtool.icon_evidence_index import IconEvidenceIndex
from w3xtool.icon_evidence_models import (
    FilteredIconEvidence,
    IconGapReason,
    IconResolutionLayer,
    ResolvedIconEvidence,
    UnresolvedIconEvidence,
)
from w3xtool.icon_resources import AnonymousIconResource, IconObjectReference


def test_icon_integrity_splits_every_counter_without_calling_gaps_write_failures() -> (
    None
):
    # Given
    unresolved = tuple(
        UnresolvedIconEvidence(
            _reference(category, rawcode),
            IconGapReason.HISTORICAL_CLIENT_MISS,
            (),
            (),
        )
        for category, rawcode in (("技能", "A001"), ("物品", "I001"))
    )
    resolved_reference = _reference("单位", "h001", path=r"Icons\Hit.blp")
    index = IconEvidenceIndex.build(
        resolved=(
            ResolvedIconEvidence(
                resolved_reference,
                r"Icons\Hit.blp",
                "map.w3x",
                b"BLP1hit",
                "b" * 64,
                IconResolutionLayer.CURRENT_MAP,
                (),
            ),
        ),
        unresolved=unresolved,
        filtered=(FilteredIconEvidence(_reference("单位", "h002")),),
        anonymous=(
            AnonymousIconResource(
                7,
                b"BLP1anonymous",
                "c" * 64,
                "block_000007_cccccccc",
                "map.w3x",
                BlockSource.ARCHIVE_RECOVERED,
                BlockState.DECODED,
            ),
        ),
        anonymous_read_failure_count=2,
    )
    exports = (
        _export(original_written=False, png_written=False),
        _export(original_written=True, png_written=False),
    )

    # When
    counts = {
        label: int(value)
        for line in format_icon_integrity(index, exports).splitlines()
        for label, value in (line.split("：", 1),)
    }

    # Then
    assert counts == {
        "有效引用": 3,
        "已解析引用": 1,
        "过滤字段": 1,
        "具名未解析": 1,
        "未解析引用": 2,
        "匿名载荷": 1,
        "匿名读取失败": 2,
        "原始写出失败": 1,
        "PNG失败": 1,
    }


def _reference(
    category: str, rawcode: str, *, path: str = r"Icons\Missing.blp"
) -> IconObjectReference:
    return IconObjectReference(
        category,
        rawcode,
        "引用对象",
        "BASE",
        "map.w3x",
        "a" * 64,
        "map.w3x",
        "aart",
        "图标 - 普通",
        "icon",
        "war3map.w3a",
        "",
        path,
        path,
    )


def _export(*, original_written: bool, png_written: bool) -> IconExportRecord:
    return IconExportRecord(
        IconKind.NAMED,
        r"Icons\Hit.blp",
        r"Icons\Hit.blp",
        "map.w3x",
        None,
        "d" * 64,
        "图标/原始/具名/Icons/Hit.blp",
        "图标/PNG/具名/Icons/Hit.png",
        original_written,
        png_written,
        (
            IconExportState.PNG_FAILED
            if original_written
            else IconExportState.ORIGINAL_FAILED
        ),
        "fixture failure",
        (),
    )
