"""Portable integration coverage for real campaign MPQ extraction."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from w3xtool.api import MapData, export_all_files, load_map

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
