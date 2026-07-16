"""Per-map completeness-state precedence tests."""

from __future__ import annotations

import pytest

from w3xtool.batch_descriptions import DescriptionRecord, DescriptionState
from w3xtool.batch_icon_export import IconExportRecord, IconExportState, IconKind
from w3xtool.batch_models import MapBatchState
from w3xtool.batch_reports import derive_map_state


def _description_record(state: DescriptionState) -> DescriptionRecord:
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
        raw_description="说明",
        readable_description="说明",
        description_source="war3map.w3a",
        state=state,
    )


def _icon_record(state: IconExportState) -> IconExportRecord:
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
        objects=(),
    )


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
    icons = (_icon_record(icon_state),)
    descriptions = (_description_record(description_state),)

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
