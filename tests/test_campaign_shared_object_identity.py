"""Campaign children resolve shared script objects by category and rawcode."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from w3xtool import map_loader
from w3xtool.load_context import MapLoadContext
from w3xtool.map_archive_reader import MapArchiveReader
from w3xtool.map_components import _add_script_refs
from w3xtool.map_data import GameObject, MapData


def test_script_refs_select_shared_object_when_rawcodes_collide() -> None:
    # Given: campaign-shared unit and item objects use the same rawcode.
    unit = GameObject("单位", "w3u", "X001", "hfoo", "共享单位", True)
    item = GameObject("物品", "w3t", "X001", "ratf", "共享物品", True)
    shared = {(obj.category, obj.obj_id): obj for obj in (unit, item)}
    child = MapData("child.w3x", "child")
    script = "\n".join(
        (
            "call CreateUnit(Player(0), 'X001', 0.0, 0.0, 0.0)",
            "call CreateItem('X001', 0.0, 0.0)",
        ),
    )

    # When: child script references are completed from the shared object table.
    _add_script_refs(child, script, shared)

    # Then: each exact category keeps its own shared metadata.
    assert child.obj_identity_index[("单位", "X001")].name == "共享单位"
    assert child.obj_identity_index[("物品", "X001")].name == "共享物品"


def test_campaign_loader_passes_identity_index_to_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the real campaign loader is observed only at its recursive boundary.
    fixture = Path(__file__).parent / "fixtures" / "reference" / "stormlib-campaign.w3n"
    original = map_loader._load_map_impl
    captured: list[Mapping[tuple[str, str], GameObject] | None] = []

    def capture_shared_index(
        archive: MapArchiveReader,
        path: str,
        depth: int,
        shared_index: Mapping[tuple[str, str], GameObject] | None,
        load_context: MapLoadContext,
    ) -> MapData:
        if depth > 0:
            captured.append(shared_index)
        return original(archive, path, depth, shared_index, load_context)

    monkeypatch.setattr(map_loader, "_load_map_impl", capture_shared_index)

    # When: the campaign and its embedded map are loaded normally.
    loaded = map_loader.load_map(str(fixture))

    # Then: the child receives the parent's exact category-safe index object.
    try:
        assert captured == [loaded.obj_identity_index]
    finally:
        loaded.close()
