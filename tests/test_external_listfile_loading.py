"""Load-time validation and immutable external-listfile behavior."""

from __future__ import annotations

from pathlib import Path

from w3xtool.api import MapData, load_map
from w3xtool.external_listfile import ExternalListfileReport
from w3xtool.gui_loader import LoadedMap, load_path_payload
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


def test_load_map_confirms_external_names_before_listing(monkeypatch) -> None:
    # Given: one real hidden name, one missing name, one unsafe name, and a duplicate.
    archive = _Archive({"hidden/config.json"})
    context = MapLoadContext(
        external_names=("hidden/config.json", "ghost.blp", "../escape", "HIDDEN/CONFIG.JSON"),
    )
    monkeypatch.setattr("w3xtool.api.MPQArchive", lambda _path: archive)

    # When: the map is loaded through the normal API.
    md = load_map("fixture.w3x", load_context=context)

    # Then: only the confirmed safe name enters the map listing.
    assert md.external_listfile == ExternalListfileReport(
        confirmed=("hidden/config.json",),
        missing=("ghost.blp",),
        unsafe=("../escape",),
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
    )

    # Then: WTG parsing receives both the names and loaded trigger schema.
    assert captured[0] is not None
    assert captured[0].external_names == ("hidden/config.json",)
    assert captured[0].trigger_schema is not None
    assert captured[0].trigger_schema.has_trigger_strings


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

