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
