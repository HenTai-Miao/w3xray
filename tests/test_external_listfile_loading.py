"""Load-time validation and immutable external-listfile behavior."""

from __future__ import annotations

from pathlib import Path

from w3xtool.api import MapData, _campaign_inner_maps, load_map
from w3xtool.external_listfile import (
    ExternalListfileReport,
    read_external_listfile,
    validate_external_names,
)
from w3xtool.gui_loader import LoadedMap, load_path_payload
from w3xtool.client_object_data import ClientBaseObject
from w3xtool.knowledge_pack import write_knowledge_pack
from w3xtool.load_context import MapLoadContext


class _Archive:
    path = "fixture.w3x"
    _data = b""

    def __init__(self, existing: set[str]) -> None:
        self._existing = existing

    def has_file(self, name: str) -> bool:
        return name in self._existing

    def read_file(self, name: str) -> bytes:
        if name not in self._existing:
            raise KeyError(name)
        return b"fixture"

    def list_files(self) -> list[str]:
        return []

    def close(self) -> None:
        return


def test_read_external_listfile_preserves_unc_name_for_unsafe_report(tmp_path: Path) -> None:
    # Given: a real listfile containing a forward-slash UNC path.
    listfile = tmp_path / "listfile.txt"
    listfile.write_text("//server/share/file.blp\n", encoding="utf-8")

    # When: names cross the real file parser and archive validation boundary.
    report = validate_external_names(_Archive(set()), read_external_listfile(str(listfile)))

    # Then: the path is reported as unsafe instead of disappearing as a comment.
    assert report.unsafe == ("//server/share/file.blp",)


def test_load_map_confirms_external_names_before_listing(monkeypatch) -> None:
    # Given: one real hidden name, one missing name, one unsafe name, and a duplicate.
    archive = _Archive({"hidden/config.json"})
    context = MapLoadContext(
        external_names=(
            "hidden/config.json",
            "ghost.blp",
            "../escape",
            r"\\server\share\escape",
            "HIDDEN/CONFIG.JSON",
        ),
    )
    monkeypatch.setattr("w3xtool.api.MPQArchive", lambda _path: archive)

    # When: the map is loaded through the normal API.
    md = load_map("fixture.w3x", load_context=context)

    # Then: only the confirmed safe name enters the map listing.
    assert md.external_listfile == ExternalListfileReport(
        confirmed=("hidden/config.json",),
        missing=("ghost.blp",),
        unsafe=("../escape", r"\\server\share\escape"),
        duplicates=("HIDDEN/CONFIG.JSON",),
    )
    assert "hidden/config.json" in md.all_files
    assert "ghost.blp" not in md.all_files


def test_gui_loader_builds_schema_and_external_context_from_selected_sources() -> None:
    # Given: selected external names and a real TriggerData fixture directory.
    captured: list[MapLoadContext | None] = []

    def load(path: str, *, load_context: MapLoadContext | None = None) -> MapData:
        captured.append(load_context)
        return MapData(path=path, name="context")

    def prepare(
        active: MapData,
        campaign_path: str | None,
        views: list[tuple[str, MapData]] | None,
        *,
        load_options: dict[str, bool] | None,
    ) -> LoadedMap:
        return LoadedMap(active, [], [], None, views, campaign_path)

    trigger_dir = Path(__file__).with_name("fixtures") / "trigger"

    # When: the GUI loader opens the map with both selected sources.
    load_path_payload(
        "fixture.w3x",
        load=load,
        prepare=prepare,
        external_names=("hidden/config.json",),
        game_data_path=str(trigger_dir),
        author_bundle_path="author-bundle",
    )

    # Then: WTG parsing receives both the names and loaded trigger schema.
    assert captured[0] is not None
    assert captured[0].external_names == ("hidden/config.json",)
    assert captured[0].trigger_schema is not None
    assert captured[0].trigger_schema.has_trigger_strings
    assert captured[0].author_bundle_path == "author-bundle"


def test_gui_loader_preserves_context_with_only_client_base_objects(monkeypatch) -> None:
    # Given: selected game data yielded object tables but no TriggerData or listfile data.
    context = MapLoadContext(
        client_base_objects=(ClientBaseObject("hX01", "单位", (("名称", "Client Base"),)),),
    )
    captured: list[MapLoadContext | None] = []
    monkeypatch.setattr("w3xtool.gui_loader.build_map_load_context", lambda **_kwargs: context)

    def load(path: str, *, load_context: MapLoadContext | None = None) -> MapData:
        captured.append(load_context)
        return MapData(path=path, name="client context")

    def prepare(
        active: MapData,
        campaign_path: str | None,
        views: list[tuple[str, MapData]] | None,
        *,
        load_options: dict[str, bool] | None,
    ) -> LoadedMap:
        return LoadedMap(active, [], [], None, views, campaign_path)

    # When: the normal GUI path loader hands off the built context.
    load_path_payload("fixture.w3x", load=load, prepare=prepare, game_data_path="client-data")

    # Then: object-only enrichment reaches the map loader unchanged.
    assert captured == [context]


def test_repeated_pack_exports_do_not_mutate_map_file_listing(tmp_path) -> None:
    # Given: a loaded map and legacy external_names passed at export time.
    md = MapData(path="missing.w3x", name="immutable")
    md.all_files = ["war3map.j"]
    before = tuple(md.all_files)

    # When: the same pack is exported repeatedly.
    write_knowledge_pack(md, str(tmp_path / "first"), external_names=("ghost.blp",))
    write_knowledge_pack(md, str(tmp_path / "second"), external_names=("ghost.blp",))

    # Then: export is a read-only operation over MapData.
    assert tuple(md.all_files) == before


def test_campaign_discovery_merges_validated_and_archive_names() -> None:
    # Given: validated names contain only static files while the archive knows an arbitrary chapter name.
    archive = _Archive(set())
    archive.list_files = lambda: ["Story/Finale.w3x"]

    # When: campaign map candidates are discovered.
    names = _campaign_inner_maps(archive, ("war3campaign.w3f",))

    # Then: the archive's own nonstandard chapter name is not hidden by a non-empty validated list.
    assert names == ["Story/Finale.w3x"]
