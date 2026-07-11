"""Pure campaign map-order and archive-source helpers."""

from __future__ import annotations

from contextlib import nullcontext

from w3xtool.api import _campaign_inner_maps
from w3xtool.campaign_sources import campaign_inner_maps, open_map_source
from w3xtool.map_data import MapData
from w3xtool.w3f import CampaignMapEntry, W3fInfo


def test_campaign_inner_maps_prefers_w3f_order_and_archive_spelling() -> None:
    # Given: W3F order disagrees with the archive's listfile order and path spelling.
    w3f = W3fInfo(maps=[
        CampaignMapEntry("Maps\\B.w3x", "B", "", True),
        CampaignMapEntry("Maps\\A.w3m", "A", "", True),
    ])
    archive_names = ("maps/a.W3M", "MAPS/b.W3X", "Maps\\C.w3x", "notes.txt")

    # When: the campaign sources are ordered.
    names = campaign_inner_maps(w3f, archive_names)

    # Then: declared order wins, archive spelling is retained, and leftovers follow.
    assert names == ("MAPS/b.W3X", "maps/a.W3M", "Maps\\C.w3x")


def test_campaign_inner_maps_deduplicates_case_and_slash_variants() -> None:
    # Given: the same member appears with slash and case variants.
    w3f = W3fInfo(maps=[CampaignMapEntry("maps/a.w3x", "A", "", True)])

    # When: archive names are normalized for membership.
    names = campaign_inner_maps(w3f, ("Maps\\A.W3X", "maps/a.w3x", "Maps/B.w3x"))

    # Then: only the first archive spelling for each logical path remains.
    assert names == ("Maps\\A.W3X", "Maps/B.w3x")


def test_loader_campaign_discovery_accepts_w3f_declared_order() -> None:
    # Given: archive enumeration disagrees with the W3F map-order table.
    class Archive:
        def list_files(self) -> list[str]:
            return ["Maps\\A.w3x", "Maps\\B.w3x"]

        def has_file(self, _name: str) -> bool:
            return False

    w3f = W3fInfo(maps=[
        CampaignMapEntry("Maps\\B.w3x", "B", "", True),
        CampaignMapEntry("Maps\\A.w3x", "A", "", True),
    ])

    # When: the compatibility wrapper discovers campaign children.
    names = _campaign_inner_maps(Archive(), (), w3f)

    # Then: the parsed W3F order wins without changing archive path spelling.
    assert names == ["Maps\\B.w3x", "Maps\\A.w3x"]


def test_loader_probes_w3f_child_missing_from_archive_enumeration() -> None:
    # Given: W3F declares a real child omitted from listfile-based enumeration.
    class Archive:
        def list_files(self) -> list[str]:
            return []

        def has_file(self, name: str) -> bool:
            return name == "Maps\\Hidden.w3x"

    w3f = W3fInfo(maps=[CampaignMapEntry("Maps\\Hidden.w3x", "Hidden", "", True)])

    # When: the loader discovers campaign children.
    names = _campaign_inner_maps(Archive(), (), w3f)

    # Then: the declared path is probed directly and retained in W3F order.
    assert names == ["Maps\\Hidden.w3x"]


def test_loader_attempts_missing_w3f_child_for_diagnostics() -> None:
    # Given: W3F declares a child that is absent from every archive source.
    class Archive:
        def list_files(self) -> list[str]:
            return []

        def has_file(self, _name: str) -> bool:
            return False

    w3f = W3fInfo(maps=[CampaignMapEntry("Maps\\Missing.w3x", "Missing", "", True)])

    # When: campaign candidates are assembled for the loader's diagnostic loop.
    names = _campaign_inner_maps(Archive(), (), w3f)

    # Then: the declared member is attempted instead of disappearing before diagnostics.
    assert names == ["Maps\\Missing.w3x"]


def test_open_map_source_prefers_attached_archive_source() -> None:
    # Given: map metadata with a reopenable archive source.
    class Source:
        path = "attached.w3x"

        def open(self):
            return nullcontext("attached")

        def close(self) -> None:
            return None

    md = MapData("missing-on-disk.w3x", "Attached", archive_source=Source())

    # When: a consumer asks for its archive context.
    with open_map_source(md) as opened:
        # Then: the attached source wins over the logical path.
        assert opened == "attached"


def test_open_map_source_falls_back_to_path_source() -> None:
    # Given: ordinary map metadata without an attached source.
    fixture = "tests/fixtures/maps/war3net-map-script-builder.w3x"
    md = MapData(fixture, "Example")

    # When: a consumer asks for its archive context.
    with open_map_source(md) as archive:
        has_script = archive.has_file("war3map.j")

    # Then: it opens via a path-backed source.
    assert has_script
