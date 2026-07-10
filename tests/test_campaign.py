"""Portable integration coverage for real campaign MPQ extraction."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from w3xtool import archive_export
from w3xtool.api import MapData, export_all_files, load_map
from w3xtool.extraction_completeness import build_extraction_completeness_report
from w3xtool.knowledge_assets import export_resource_bodies
from w3xtool.knowledge_terrain_exports import build_terrain_export_data
from w3xtool.knowledge_unknown_exports import write_unknown_files
from w3xtool.map_identity import build_map_identity

_CAMPAIGN = Path(__file__).parent / "fixtures" / "reference" / "stormlib-campaign.w3n"
_CAMPAIGN_SHA256 = "617ccc0239e9c919edd4f6cce20b56e15e490ba466b661a9edba60623b68e317"


@pytest.fixture(scope="module")
def campaign() -> MapData:
    return load_map(str(_CAMPAIGN))


def test_reference_campaign_fixture_hash_is_pinned() -> None:
    # Given/When: the independently generated real campaign fixture is read.
    digest = hashlib.sha256(_CAMPAIGN.read_bytes()).hexdigest()

    # Then: accidental fixture replacement cannot change the acceptance baseline.
    assert digest == _CAMPAIGN_SHA256


def test_campaign_loads_shared_objects_and_nested_real_map(campaign: MapData) -> None:
    # Given: the StormLib campaign contains a shared w3a and one nested map.
    # When: the normal high-level loader parses all campaign layers.
    shared = [obj for values in campaign.objects.values() for obj in values if obj.ext == "w3a"]

    # Then: both the top-level shared layer and nested map are available.
    assert [obj.obj_id for obj in shared] == ["Amls"]
    assert len(campaign.sub_maps) == 1
    assert campaign.sub_maps[0].name == "Maps\\Chapter1.w3x"
    assert campaign.sub_maps[0].obj_index["AHwe"].name == "召唤水元素"


def test_campaign_nested_map_keeps_real_slk_fields_and_references(campaign: MapData) -> None:
    # Given: the nested map contains a real wc3libs AbilityData SLK table.
    ability = campaign.sub_maps[0].obj_index["AHwe"]

    # When: SLK fields and object references are merged into the submap.
    targets = {
        code
        for _label, resolved in campaign.sub_maps[0].references["AHwe"]
        for code, _name in resolved
    }

    # Then: the legacy SLK payload is not reduced to a name-only object.
    assert len(ability.fields) > 10
    assert "hwat" in targets


def test_campaign_recursive_export_includes_shared_and_nested_files(
    tmp_path: Path,
) -> None:
    # Given: a real campaign fixture and an empty output directory.
    output = tmp_path / "campaign"

    # When: all campaign layers are exported recursively.
    export_all_files(str(_CAMPAIGN), str(output))

    # Then: shared data, nested archive, script, resource and SLK are all materialized.
    assert (output / "war3campaign.w3a").is_file()
    assert (output / "Maps" / "Chapter1.w3x").is_file()
    assert (output / "Maps" / "Chapter1" / "war3map.j").is_file()
    assert (output / "Maps" / "Chapter1" / "war3mapMap.blp").is_file()
    assert (output / "Maps" / "Chapter1" / "Units" / "AbilityData.slk").is_file()


def test_campaign_child_identity_and_terrain_reopen_owned_archive(campaign: MapData) -> None:
    # Given: a loaded child whose logical path does not exist on the host filesystem.
    child = campaign.sub_maps[0]

    # When: archive-backed reports run after the parent load has returned.
    identity = build_map_identity(child)
    terrain = build_terrain_export_data(child)

    # Then: both reports use the child's owned archive bytes.
    assert identity.readable and identity.sha1
    assert terrain.terrain is not None
    assert terrain.structure.pathing is not None


def test_campaign_child_resource_bodies_reopen_owned_archive(
    campaign: MapData,
    tmp_path: Path,
) -> None:
    # Given: the child archive contains a real minimap image and SLK body.
    child = campaign.sub_maps[0]

    # When: resource bodies are exported from the already-loaded child.
    report = export_resource_bodies(child, str(tmp_path))

    # Then: the logical child path does not prevent body extraction.
    assert report.exported_count > 0
    assert (tmp_path / "素材文件" / "war3mapmap.blp").is_file()
    assert (tmp_path / "素材文件" / "units" / "abilitydata.slk").is_file()


def test_campaign_child_completeness_and_unknown_exports_reopen_owned_archive(
    campaign: MapData,
    tmp_path: Path,
) -> None:
    # Given: the child is backed by BytesArchiveSource rather than a host path.
    child = campaign.sub_maps[0]

    # When: block-level reports reopen the child archive.
    completeness = build_extraction_completeness_report(child)
    count = write_unknown_files(child, str(tmp_path))

    # Then: block coverage and the unknown-file manifest are produced.
    assert completeness.source_readable
    assert completeness.block_count is not None
    assert count >= 1
    assert (tmp_path / "Unknown_manifest.tsv").is_file()


def test_campaign_child_loading_does_not_reenter_path_loader() -> None:
    # Given: the outer campaign is opened through the public path loader.
    from w3xtool import map_loader

    load_from_path = map_loader.load_map

    # When: recursive path loading is rejected while the campaign is parsed.
    with patch.object(map_loader, "load_map", side_effect=AssertionError("path reentry")):
        loaded = load_from_path(str(_CAMPAIGN))

    # Then: child bytes are parsed directly through their retained source.
    try:
        assert [child.path for child in loaded.sub_maps] == ["Maps\\Chapter1.w3x"]
    finally:
        loaded.close()


def test_campaign_child_exports_directly_from_owned_source(
    campaign: MapData,
    tmp_path: Path,
) -> None:
    # Given: the active child has only a logical path and retained archive bytes.
    child = campaign.sub_maps[0]
    output = tmp_path / "child"

    # When: the loaded-map export entry point extracts that active child.
    result = archive_export.export_loaded_map_files(child, str(output))

    # Then: the child archive contents are materialized without its parent path.
    assert result == str(output)
    assert (output / "war3map.j").is_file()
    assert (output / "Units" / "AbilityData.slk").is_file()
