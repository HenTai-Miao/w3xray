"""Complete text indexes are built once by the object pipeline."""

from __future__ import annotations

from w3xtool.client_object_data import ClientBaseObject
from w3xtool.description_cache import DescriptionCache
from w3xtool.map_data import MapData
from w3xtool.object_candidates import (
    ObjectCandidate,
    ObjectFieldValue,
    ObjectSourceKind,
)
from w3xtool.object_pipeline import populate_object_pipeline
from w3xtool.object_text_models import ObjectTextState


def test_map_data_default_keeps_legacy_construction_with_an_empty_text_index() -> None:
    # Given / When: an existing caller constructs MapData with only path and name.
    md = MapData("fixture.w3x", "fixture")

    # Then: the appended compatibility field is an immutable empty index.
    assert md.object_texts.records == ()


def test_pipeline_builds_map_and_client_text_once_from_original_candidates() -> None:
    # Given: one map item has an explicit description while another inherits client text.
    map_candidate = ObjectCandidate(
        "物品",
        "I001",
        "ratf",
        True,
        "w3t",
        (
            ObjectFieldValue(
                "utub",
                "提示工具 - 扩展的",
                "地图完整说明",
                "war3map.w3t",
                ObjectSourceKind.BINARY,
            ),
        ),
        (),
    )
    client = ClientBaseObject(
        "rde1",
        "物品",
        (("说明", "客户端说明"),),
        (
            ObjectFieldValue(
                "utub",
                "提示工具 - 扩展的",
                "客户端说明",
                "Units\\ItemStrings.txt",
                ObjectSourceKind.TEXT_STRINGS,
            ),
        ),
    )
    client_base_candidate = ObjectCandidate(
        "物品",
        "I002",
        "rde1",
        True,
        "w3t",
        (),
        (),
    )
    md = MapData("fixture.w3x", "fixture")

    # When: the public pipeline materializes the objects.
    populate_object_pipeline(
        md,
        (map_candidate, client_base_candidate),
        {},
        include_named_bases=False,
        client_objects=(client,),
        description_cache=DescriptionCache.build(()),
        client_text_available=True,
    )

    # Then: the same MapData carries source-aware map and client results.
    map_row = next(
        row
        for row in md.object_texts.for_object("物品", "I001")
        if row.role == "扩展提示" and row.raw_value
    )
    client_row = next(
        row
        for row in md.object_texts.for_object("物品", "I002")
        if row.role == "扩展提示" and row.raw_value
    )
    assert (map_row.raw_value, map_row.state) == (
        "地图完整说明",
        ObjectTextState.MAP_VALUE,
    )
    assert (client_row.raw_value, client_row.state) == (
        "客户端说明",
        ObjectTextState.CLIENT_FILL,
    )


def test_explicit_empty_blocks_fills_without_discarding_same_tier_text() -> None:
    # Given: binary explicitly clears a role while named Strings supplies its full text.
    empty = ObjectCandidate(
        "物品",
        "I001",
        "ratf",
        True,
        "w3t",
        (
            ObjectFieldValue(
                "utub", "提示工具 - 扩展的", "", "war3map.w3t", ObjectSourceKind.BINARY
            ),
        ),
        (),
    )
    text = ObjectCandidate(
        "物品",
        "I001",
        "I001",
        True,
        "txt",
        (
            ObjectFieldValue(
                "Ubertip",
                "提示工具 - 扩展的",
                "地图文本完整说明",
                "Units\\ItemStrings.txt",
                ObjectSourceKind.TEXT_STRINGS,
            ),
        ),
        (),
    )
    md = MapData("fixture.w3x", "fixture")

    # When: both equal-tier map sources enter the complete text index.
    populate_object_pipeline(
        md,
        (empty, text),
        {},
        include_named_bases=False,
        client_objects=(),
        description_cache=DescriptionCache.build(()),
        client_text_available=False,
    )

    # Then: the clear blocks lower fills, but the peer map evidence remains complete.
    rows = tuple(
        row
        for row in md.object_texts.for_object("物品", "I001")
        if row.role == "扩展提示"
    )
    assert {(row.raw_value, row.state) for row in rows} == {
        ("", ObjectTextState.MAP_EXPLICIT_EMPTY),
        ("地图文本完整说明", ObjectTextState.MAP_VALUE),
    }


def test_fixed_placeholder_keeps_author_undefined_state_with_same_tier_text() -> None:
    # Given: one map tier explicitly clears, leaves undefined, and supplies a role.
    fields = tuple(
        ObjectFieldValue(
            "utub",
            "提示工具 - 扩展的",
            value,
            "war3map.w3t",
            ObjectSourceKind.BINARY,
        )
        for value in ("", "-", "地图文本完整说明")
    )
    candidate = ObjectCandidate("物品", "I001", "ratf", True, "w3t", fields, ())
    md = MapData("fixture.w3x", "fixture")

    # When: the public pipeline resolves every same-tier evidence variant.
    populate_object_pipeline(
        md,
        (candidate,),
        {},
        include_named_bases=False,
        client_objects=(),
        description_cache=DescriptionCache.build(()),
        client_text_available=False,
    )

    # Then: each raw value retains its exact semantic state.
    rows = tuple(
        row
        for row in md.object_texts.for_object("物品", "I001")
        if row.role == "扩展提示"
    )
    assert {(row.raw_value, row.state) for row in rows} == {
        ("", ObjectTextState.MAP_EXPLICIT_EMPTY),
        ("-", ObjectTextState.AUTHOR_UNDEFINED),
        ("地图文本完整说明", ObjectTextState.MAP_VALUE),
    }


def test_pipeline_preserves_pre_westring_raw_text_with_readable_translation() -> None:
    # Given: compatibility presentation translated a retained WESTRING token.
    candidate = ObjectCandidate(
        "物品",
        "I001",
        "ratf",
        True,
        "w3t",
        (
            ObjectFieldValue(
                "utip",
                "提示工具 - 基础",
                "技能",
                "war3map.w3t",
                ObjectSourceKind.BINARY,
                value_type="string",
                raw_value="WESTRING_ABILITY",
            ),
        ),
        (),
    )
    md = MapData("fixture.w3x", "fixture")

    # When: the public pipeline builds the complete-text index.
    populate_object_pipeline(
        md,
        (candidate,),
        {},
        include_named_bases=False,
        client_objects=(),
        description_cache=DescriptionCache.build(()),
        client_text_available=False,
    )

    # Then: the source token and readable translation remain independently available.
    row = next(
        row
        for row in md.object_texts.for_object("物品", "I001")
        if row.role == "基础提示" and row.raw_value
    )
    assert (row.raw_value, row.readable_value) == ("WESTRING_ABILITY", "技能")


def test_pipeline_preserves_client_pre_westring_raw_text() -> None:
    # Given: client evidence carries both a translated view and its source token.
    candidate = ObjectCandidate("物品", "I001", "ratf", True, "w3t", (), ())
    client = ClientBaseObject(
        "ratf",
        "物品",
        (("提示", "技能"),),
        (
            ObjectFieldValue(
                "utip",
                "提示工具 - 基础",
                "技能",
                "Units\\ItemStrings.txt",
                ObjectSourceKind.TEXT_STRINGS,
                value_type="string",
                raw_value="WESTRING_ABILITY",
            ),
        ),
    )
    md = MapData("fixture.w3x", "fixture")

    # When: the public pipeline fills missing text from client evidence.
    populate_object_pipeline(
        md,
        (candidate,),
        {},
        include_named_bases=False,
        client_objects=(client,),
        description_cache=DescriptionCache.build(()),
        client_text_available=True,
    )

    # Then: the client source token remains raw while presentation stays readable.
    row = next(
        row
        for row in md.object_texts.for_object("物品", "I001")
        if row.role == "基础提示" and row.raw_value
    )
    assert (row.raw_value, row.readable_value, row.state) == (
        "WESTRING_ABILITY",
        "技能",
        ObjectTextState.CLIENT_FILL,
    )
