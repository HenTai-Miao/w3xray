"""Lossless unresolved-icon report and split integrity tests."""

from __future__ import annotations

import json
from typing import Final

from tests.real_map_text_acceptance import read_tsv_text
from w3xtool.icon_evidence_exports import (
    format_unresolved_icon_tsv,
    normalized_icon_gap_count,
)
from w3xtool.icon_evidence_index import IconEvidenceIndex
from w3xtool.icon_evidence_models import (
    FilteredIconEvidence,
    IconGapReason,
    IconLookupAttempt,
    IconResolutionLayer,
    UnresolvedIconEvidence,
)
from w3xtool.icon_resources import IconObjectReference

_DIGEST: Final = "a" * 64
_PATH: Final = r"Icons\Missing.blp"
_REFERENCE_KEYS: Final = {
    "category",
    "rawcode",
    "base",
    "name",
    "field",
    "label",
    "type",
    "source",
    "wts",
    "map",
    "scope",
}


def test_unresolved_report_has_one_path_row_with_every_reference() -> None:
    # Given
    index = _index_with_two_object_references()

    # When
    table = read_tsv_text(format_unresolved_icon_tsv(index))

    # Then
    assert len(table.rows) == 1
    row = table.rows[0]
    assert table.value(row, "规范路径") == _PATH
    assert table.value(row, "主原因") == "historical_client_miss"
    references = json.loads(table.value(row, "引用集合"))
    assert {(item["category"], item["rawcode"]) for item in references} == {
        ("技能", "A001"),
        ("物品", "I001"),
    }
    assert all(set(item) == _REFERENCE_KEYS for item in references)


def test_unresolved_report_preserves_raw_paths_attempts_and_field_evidence() -> None:
    # Given: every source field contains evidence that delimiter-based rendering loses.
    raw_path = 'Icons\t"Missing\nName.blp'
    reference = _reference(
        "技能",
        "A001",
        name="暴风\t雪\n原名",
        requested_path=raw_path,
        field_label="图标\t普通\n原标签",
    )
    attempt = IconLookupAttempt(
        IconResolutionLayer.CURRENT_MAP,
        raw_path,
        "map\tarchive.w3x",
        False,
    )
    index = IconEvidenceIndex.build(
        unresolved=(
            UnresolvedIconEvidence(
                reference,
                IconGapReason.NAMED_RESOURCE_MISSING,
                (),
                (attempt,),
            ),
        )
    )

    # When
    table = read_tsv_text(format_unresolved_icon_tsv(index))
    row = table.rows[0]

    # Then: standard TSV decoding restores the complete JSON values.
    assert json.loads(table.value(row, "原始路径集合")) == [raw_path]
    attempts = json.loads(table.value(row, "查询证据"))
    assert attempts[0]["candidate"] == raw_path
    assert attempts[0]["source"] == "map\tarchive.w3x"
    references = json.loads(table.value(row, "引用集合"))
    assert references[0]["name"] == "暴风\t雪\n原名"
    assert references[0]["label"] == "图标\t普通\n原标签"


def test_filtered_icon_fields_never_leak_into_gap_rows() -> None:
    # Given
    index = IconEvidenceIndex.build(
        filtered=(FilteredIconEvidence(_reference("单位", "h001")),)
    )

    # When
    table = read_tsv_text(format_unresolved_icon_tsv(index))

    # Then
    assert table.rows == ()


def test_unresolved_report_keeps_distinct_logical_submaps_separate() -> None:
    # Given: two campaign children have identical bytes and the same missing path.
    index = IconEvidenceIndex.build(
        unresolved=tuple(
            UnresolvedIconEvidence(
                _reference("技能", rawcode, map_path=map_path),
                IconGapReason.NAMED_RESOURCE_MISSING,
                (),
                (),
            )
            for rawcode, map_path in (
                ("A001", "chapter-a.w3x"),
                ("A002", "chapter-b.w3x"),
            )
        )
    )

    # When
    table = read_tsv_text(format_unresolved_icon_tsv(index))

    # Then
    assert {table.value(row, "地图路径") for row in table.rows} == {
        "chapter-a.w3x",
        "chapter-b.w3x",
    }
    assert normalized_icon_gap_count(index) == 2


def _index_with_two_object_references() -> IconEvidenceIndex:
    attempt = IconLookupAttempt(
        IconResolutionLayer.SAME_MAP_HISTORY,
        _PATH,
        "",
        False,
    )
    return IconEvidenceIndex.build(
        unresolved=tuple(
            UnresolvedIconEvidence(
                _reference(category, rawcode),
                IconGapReason.HISTORICAL_CLIENT_MISS,
                (),
                (attempt,),
            )
            for category, rawcode in (("技能", "A001"), ("物品", "I001"))
        )
    )


def _reference(
    category: str,
    rawcode: str,
    *,
    name: str = "引用对象",
    requested_path: str = _PATH,
    normalized_path: str = _PATH,
    field_label: str = "图标 - 普通",
    map_path: str = "map.w3x",
) -> IconObjectReference:
    return IconObjectReference(
        category,
        rawcode,
        name,
        "BASE",
        map_path,
        _DIGEST,
        map_path,
        "aart",
        field_label,
        "icon",
        "war3map.w3a",
        "war3map.wts#STRING 7",
        requested_path,
        normalized_path,
    )
