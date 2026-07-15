"""Deterministic per-map and global batch report tests."""

from __future__ import annotations

import csv
import io

import pytest

import w3xtool.batch_tsv as batch_tsv
from w3xtool.batch_descriptions import DescriptionRecord, DescriptionState
from w3xtool.batch_icon_export import (
    IconExportRecord,
    IconExportState,
    IconKind,
)
from w3xtool.batch_models import (
    MapBatchState,
)
from w3xtool.batch_reports import (
    derive_map_state,
    format_description_tsv,
    format_icon_index_tsv,
)
from w3xtool.icon_resources import IconObjectReference


def _description_record(
    *,
    raw_description: str = "|cffff0000说明|r|n第二行",
    readable_description: str = "说明\n第二行",
    state: DescriptionState = DescriptionState.MAP_VALUE,
) -> DescriptionRecord:
    return DescriptionRecord(
        category="技能",
        object_id="A001",
        base_id="AHbz",
        object_name="暴风雪",
        is_custom=True,
        level=1,
        raw_tip="提示",
        readable_tip="提示",
        tip_source="war3map.w3a",
        raw_description=raw_description,
        readable_description=readable_description,
        description_source="war3map.w3a",
        state=state,
    )


def _icon_record(
    *,
    state: IconExportState = IconExportState.COMPLETE,
) -> IconExportRecord:
    return IconExportRecord(
        kind=IconKind.NAMED,
        requested_path=r"Icons\BTN.blp",
        resolved_path=r"Icons\BTN.blp",
        source_path="War3Patch.mpq",
        block_index=None,
        sha256="b" * 64,
        original_relative_path="图标/原始/具名/Icons/BTN.blp",
        png_relative_path="图标/PNG/具名/Icons/BTN.png",
        original_written=True,
        png_written=state is IconExportState.COMPLETE,
        state=state,
        error="" if state is IconExportState.COMPLETE else "decode failed",
        objects=(IconObjectReference("技能", "A001", "暴风雪"),),
    )


def test_description_tsv_keeps_raw_and_readable_columns_separate() -> None:
    # Given
    record = _description_record()

    # When
    report = format_description_tsv((record,))

    # Then
    assert "原始说明\t可读说明\t说明来源\t完整性状态" in report
    row = next(csv.DictReader(io.StringIO(report), delimiter="\t"))
    assert row["原始说明"] == "|cffff0000说明|r|n第二行"
    assert row["可读说明"] == "说明\n第二行"


def test_description_tsv_preserves_a_leading_quote_without_merging_columns() -> None:
    # Given
    text = '"烧伤附近的敌人。'
    record = _description_record(
        raw_description=text,
        readable_description=text,
    )

    # When
    report = format_description_tsv((record,))
    row = next(csv.DictReader(report.splitlines(), delimiter="\t"))

    # Then
    assert row["原始说明"] == text
    assert row["可读说明"] == text
    assert row["完整性状态"] == DescriptionState.MAP_VALUE.value


def test_description_tsv_round_trips_tabs_and_physical_newlines() -> None:
    # Given: legacy description output receives lossless raw evidence.
    text = '"开头\t字段\r\n第二行\n第三行'
    record = _description_record(
        raw_description=text,
        readable_description="开头\t字段\n第二行\n第三行",
    )

    # When: the report is parsed by the standard TSV reader.
    row = next(
        csv.DictReader(io.StringIO(format_description_tsv((record,))), delimiter="\t")
    )

    # Then: quoted TSV restores both versions exactly.
    assert row["原始说明"] == text
    assert row["可读说明"] == "开头\t字段\n第二行\n第三行"


@pytest.mark.parametrize(
    "payload",
    (
        '=HYPERLINK("https://example.invalid")',
        " \t@SUM(1,2)",
        "\u200e+1+1",
        "\n-cmd|calc",
    ),
)
def test_batch_tsv_neutralizes_formulas_with_reversible_lossless_encoding(
    payload: str,
) -> None:
    # Given: a map-controlled cell starts a spreadsheet formula after ignorable text.

    # When: the shared batch serializer emits the spreadsheet-facing TSV cell.
    report = batch_tsv.format_tsv_rows(((payload,),))
    encoded = next(csv.reader(io.StringIO(report), delimiter="\t"))[0]

    # Then: spreadsheet software sees text while trusted readers recover exact bytes.
    assert encoded != payload
    assert not encoded.lstrip().startswith(("=", "+", "-", "@"))
    assert batch_tsv.decode_tsv_cell(encoded) == payload


def test_icon_index_includes_true_source_and_all_object_references() -> None:
    # Given
    record = _icon_record()

    # When
    report = format_icon_index_tsv((record,))

    # Then
    assert "真实来源" in report
    assert "War3Patch.mpq" in report
    assert "技能:A001:暴风雪" in report


@pytest.mark.parametrize(
    (
        "structural_error",
        "restricted",
        "ledger_incomplete",
        "text_incomplete",
        "relation_incomplete",
        "icon_state",
        "description_state",
        "expected",
    ),
    (
        (
            True,
            0,
            False,
            False,
            False,
            IconExportState.COMPLETE,
            DescriptionState.MAP_VALUE,
            MapBatchState.FAILED,
        ),
        (
            False,
            1,
            False,
            False,
            False,
            IconExportState.COMPLETE,
            DescriptionState.MAP_VALUE,
            MapBatchState.RESTRICTED,
        ),
        (
            False,
            0,
            True,
            False,
            False,
            IconExportState.COMPLETE,
            DescriptionState.MAP_VALUE,
            MapBatchState.PARTIAL,
        ),
        (
            False,
            0,
            False,
            False,
            False,
            IconExportState.PNG_FAILED,
            DescriptionState.MAP_VALUE,
            MapBatchState.PARTIAL,
        ),
        (
            False,
            0,
            False,
            False,
            False,
            IconExportState.COMPLETE,
            DescriptionState.SOURCE_MISSING,
            MapBatchState.PARTIAL,
        ),
        (
            False,
            0,
            False,
            False,
            False,
            IconExportState.COMPLETE,
            DescriptionState.MAP_EXPLICIT_EMPTY,
            MapBatchState.COMPLETE,
        ),
        (
            False,
            0,
            False,
            True,
            False,
            IconExportState.COMPLETE,
            DescriptionState.MAP_VALUE,
            MapBatchState.PARTIAL,
        ),
        (
            False,
            0,
            False,
            False,
            True,
            IconExportState.COMPLETE,
            DescriptionState.MAP_VALUE,
            MapBatchState.PARTIAL,
        ),
    ),
)
def test_map_state_follows_completeness_precedence(
    structural_error: bool,
    restricted: int,
    ledger_incomplete: bool,
    text_incomplete: bool,
    relation_incomplete: bool,
    icon_state: IconExportState,
    description_state: DescriptionState,
    expected: MapBatchState,
) -> None:
    # Given
    icons = (_icon_record(state=icon_state),)
    descriptions = (_description_record(state=description_state),)

    # When
    state = derive_map_state(
        structural_error=structural_error,
        restricted_block_count=restricted,
        ledger_incomplete=ledger_incomplete,
        text_incomplete=text_incomplete,
        relation_incomplete=relation_incomplete,
        icons=icons,
        descriptions=descriptions,
    )

    # Then
    assert state is expected
