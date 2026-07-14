"""Source-aware object description audit tests."""

from __future__ import annotations

import pytest

from w3xtool.batch_descriptions import DescriptionState, audit_object_descriptions
from w3xtool.map_data import GameObject


def _game_object(
    *,
    category: str = "技能",
    obj_id: str = "A000",
    base_id: str = "AHbz",
    field_values: dict[str, str] | None = None,
    field_sources: dict[str, str] | None = None,
) -> GameObject:
    return GameObject(
        category=category,
        ext="w3a",
        obj_id=obj_id,
        base_id=base_id,
        name=f"对象 {obj_id}",
        is_custom=obj_id != base_id,
        field_values=field_values or {},
        field_sources=field_sources or {},
    )


def test_audit_preserves_raw_levels_and_cleans_markup() -> None:
    # Given
    item = _game_object(
        field_values={
            "atp1:1": "一级",
            "aub1:1": "|cffffcc00伤害|r|n100",
            "aub1:2": "",
        },
        field_sources={
            "atp1:1": "war3map.w3a",
            "aub1:1": "war3map.w3a",
            "aub1:2": "war3map.w3a",
        },
    )

    # When
    records = audit_object_descriptions((item,))

    # Then
    assert [
        (
            record.level,
            record.raw_description,
            record.readable_description,
            record.state,
        )
        for record in records
    ] == [
        (1, "|cffffcc00伤害|r|n100", "伤害\n100", DescriptionState.MAP_VALUE),
        (2, "", "", DescriptionState.MAP_EXPLICIT_EMPTY),
    ]


def test_audit_marks_inherited_client_text_without_fabricating_missing_text() -> None:
    # Given
    inherited = _game_object(
        field_values={"display:description": "客户端说明"},
        field_sources={"display:description": "base:A000"},
    )
    missing = _game_object(obj_id="A001", field_values={}, field_sources={})

    # When
    records = audit_object_descriptions((inherited, missing))

    # Then
    assert records[0].state is DescriptionState.CLIENT_FILL
    assert records[0].description_source == "base:A000"
    assert records[1].state is DescriptionState.SOURCE_MISSING
    assert records[1].raw_description == records[1].readable_description == ""


def test_map_explicit_empty_description_wins_over_client_fallback() -> None:
    # Given
    item = _game_object(
        field_values={"aub1": "", "display:description": "客户端说明"},
        field_sources={"aub1": "war3map.w3a", "display:description": "base:AHbz"},
    )

    # When
    (record,) = audit_object_descriptions((item,))

    # Then
    assert record.raw_description == ""
    assert record.description_source == "war3map.w3a"
    assert record.state is DescriptionState.MAP_EXPLICIT_EMPTY


@pytest.mark.parametrize(
    ("category", "tip_key", "description_key"),
    (
        ("单位", "utip", "utub"),
        ("物品", "utip", "utub"),
        ("技能", "atp1", "aub1"),
        ("科技", "gtp1", "gub1"),
        ("增益", "ftip", "fube"),
    ),
)
def test_audit_uses_category_specific_tip_and_description_fields(
    category: str,
    tip_key: str,
    description_key: str,
) -> None:
    # Given
    item = _game_object(
        category=category,
        field_values={tip_key: "短提示", description_key: "完整说明"},
        field_sources={tip_key: "war3map.bin", description_key: "war3map.bin"},
    )

    # When
    (record,) = audit_object_descriptions((item,))

    # Then
    assert (record.raw_tip, record.raw_description) == ("短提示", "完整说明")
    assert (record.tip_source, record.description_source) == (
        "war3map.bin",
        "war3map.bin",
    )


def test_item_description_falls_back_to_ides() -> None:
    # Given
    item = _game_object(
        category="物品",
        field_values={"ides": "编辑器描述"},
        field_sources={"ides": "war3map.w3t"},
    )

    # When
    (record,) = audit_object_descriptions((item,))

    # Then
    assert record.raw_description == "编辑器描述"
    assert record.state is DescriptionState.MAP_VALUE


def test_records_have_deterministic_category_object_and_level_order() -> None:
    # Given
    later = _game_object(
        obj_id="A002", field_values={"aub1": "later"}, field_sources={"aub1": "map"}
    )
    earlier = _game_object(
        obj_id="A001",
        field_values={"aub1:2": "two", "aub1:1": "one"},
        field_sources={"aub1:2": "map", "aub1:1": "map"},
    )

    # When
    records = audit_object_descriptions((later, earlier))

    # Then
    assert [(record.object_id, record.level) for record in records] == [
        ("A001", 1),
        ("A001", 2),
        ("A002", None),
    ]
