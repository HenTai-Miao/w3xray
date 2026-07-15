"""Compatibility characterization for the public map models."""

from __future__ import annotations

from pathlib import Path
from typing import Never

import pytest

from w3xtool.api import GameObject, MapData


def test_legacy_models_keep_decimal_category_counts_and_default_fields() -> None:
    # Given: the legacy public model constructors.
    obj = GameObject("unit", "w3u", "H001", "hfoo", "Paladin", True)
    md = MapData("x.w3x", "Example", objects={"unit": [obj], "item": []})
    defaults = MapData("empty.w3x", "Empty")

    # When: callers inspect the long-standing derived values and defaults.
    counts = md.category_counts()

    # Then: their existing public contract is unchanged.
    assert obj.decimal == 1_211_117_617
    assert counts == {"unit": 1, "item": 0}
    assert defaults.objects == {}
    assert defaults.scripts == {}
    assert defaults.all_files == []
    assert defaults.external_listfile is None
    assert defaults.sub_maps == []
    assert defaults.obj_index == {}
    assert defaults.doodads == []
    assert defaults.units == []
    assert defaults.regions == []
    assert defaults.cameras == []
    assert defaults.sounds == []
    assert defaults.game_configs == []
    assert defaults.trigger_summary is None
    assert defaults.preview_icons is None
    assert defaults.import_summary is None
    assert defaults.w3i is None
    assert defaults.w3f is None
    assert defaults.references == {}
    assert defaults.referenced_by == {}
    assert defaults.orphans == []
    assert defaults.ref_low_coverage is False
    assert defaults.script_features == []
    assert defaults.author_bundle_files == ()
    assert defaults.extraction_ledger is None
    assert defaults.item_relations.records == ()


def test_api_reexports_map_models() -> None:
    # Given: the split public model module.
    from w3xtool.api import GameObject as ApiObject
    from w3xtool.api import MapData as ApiMap
    from w3xtool.map_data import GameObject as SplitObject
    from w3xtool.map_data import MapData as SplitMap

    # When/Then: existing facade imports retain object identity.
    assert ApiObject is SplitObject
    assert ApiMap is SplitMap


def test_load_map_initializes_a_path_archive_source() -> None:
    # Given: a valid on-disk MPQ fixture passed through the compatibility facade.
    from w3xtool.api import load_map
    from w3xtool.archive_source import PathArchiveSource

    fixture = "tests/fixtures/maps/war3net-map-script-builder.w3x"

    # When: the facade loads the map into its public model.
    md = load_map(fixture)

    # Then: later extraction can reopen the original path through a source.
    try:
        assert md.archive_source == PathArchiveSource(fixture)
        assert md.extraction_ledger is not None
        assert md.extraction_ledger.entries
    finally:
        md.close()


def test_campaign_child_archive_source_reopens_after_load_returns() -> None:
    # Given: a campaign whose child is extracted through a temporary path.
    from w3xtool.api import load_map

    fixture = Path("tests/fixtures/reference/stormlib-campaign.w3n")
    campaign = load_map(str(fixture))

    # When: the child source is reopened after campaign loading has returned.
    try:
        child = campaign.sub_maps[0]
        assert child.archive_source is not None
        with child.archive_source.open() as archive:
            script = archive.read_file("war3map.j")

        # Then: the logical child remains backed by readable archive bytes.
        assert child.path == "Maps\\Chapter1.w3x"
        assert script.startswith(
            b"//==========================================================================="
        )
    finally:
        campaign.close()


def test_archive_sources_open_real_mpq_bytes_repeatedly_then_reject_after_close() -> (
    None
):
    # Given: immutable bytes from a pinned valid MPQ fixture.
    from w3xtool.archive_source import (
        ArchiveSourceClosedError,
        BytesArchiveSource,
        PathArchiveSource,
    )

    fixture = Path("tests/fixtures/maps/war3net-map-script-builder.w3x")
    expected = b"//=============================================================="
    path_source = PathArchiveSource(str(fixture))
    bytes_source = BytesArchiveSource("Maps\\Chapter01.w3x", fixture.read_bytes())

    # When: callers open both source forms and reuse the byte-backed source.
    with path_source.open() as archive:
        assert archive.read_file("war3map.j").startswith(expected)
    with bytes_source.open() as archive:
        first_read = archive.read_file("war3map.j")
    with bytes_source.open() as archive:
        second_read = archive.read_file("war3map.j")
    bytes_source.close()

    # Then: each open is independently readable and close is terminal.
    assert first_read == second_read
    assert bytes_source.is_closed
    with pytest.raises(ArchiveSourceClosedError):
        bytes_source.open()


def test_bytes_archive_source_removes_temp_file_when_mpq_open_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: invalid bytes and a tracked temporary-file allocation.
    import w3xtool.archive_source as archive_source
    from w3xtool.archive_source import BytesArchiveSource

    created_paths: list[Path] = []
    original_mkstemp = archive_source.tempfile.mkstemp

    def tracked_mkstemp(
        suffix: str | None = None,
        prefix: str | None = None,
        dir: str | None = None,
        text: bool = False,
    ) -> tuple[int, str]:
        _ = dir
        descriptor, path = original_mkstemp(
            suffix=suffix,
            prefix=prefix,
            dir=str(tmp_path),
            text=text,
        )
        created_paths.append(Path(path))
        return descriptor, path

    monkeypatch.setattr(archive_source.tempfile, "mkstemp", tracked_mkstemp)
    source = BytesArchiveSource("broken.w3x", b"not an MPQ archive")

    # When: MPQArchive rejects the temporary payload.
    with pytest.raises(ValueError):
        with source.open():
            pass

    # Then: the normal MPQ error survives and the source cleans the file.
    assert len(created_paths) == 1
    assert not created_paths[0].exists()


def test_bytes_archive_source_removes_temp_file_after_successful_context_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: valid MPQ bytes and a tracked temporary-file allocation.
    import w3xtool.archive_source as archive_source
    from w3xtool.archive_source import BytesArchiveSource

    created_paths: list[Path] = []
    original_mkstemp = archive_source.tempfile.mkstemp

    def tracked_mkstemp(
        suffix: str | None = None,
        prefix: str | None = None,
        dir: str | None = None,
        text: bool = False,
    ) -> tuple[int, str]:
        _ = dir
        descriptor, path = original_mkstemp(
            suffix=suffix,
            prefix=prefix,
            dir=str(tmp_path),
            text=text,
        )
        created_paths.append(Path(path))
        return descriptor, path

    monkeypatch.setattr(archive_source.tempfile, "mkstemp", tracked_mkstemp)
    fixture = Path("tests/fixtures/maps/war3net-map-script-builder.w3x")
    source = BytesArchiveSource("valid.w3x", fixture.read_bytes())

    # When: a successful archive context exits.
    with source.open() as archive:
        assert archive.read_file("war3map.j")

    # Then: the source-owned temporary file is gone.
    assert len(created_paths) == 1
    assert not created_paths[0].exists()


def test_map_data_close_closes_source_and_sub_maps_idempotently() -> None:
    # Given: a map hierarchy with independently closable archive sources.
    from w3xtool.map_data import MapData as SplitMap

    class CloseRecorder:
        path = "recorder.w3x"

        def __init__(self) -> None:
            self.close_calls = 0

        def open(self) -> Never:
            raise AssertionError("test does not reopen recorder")

        def close(self) -> None:
            self.close_calls += 1

    parent_source = CloseRecorder()
    child_source = CloseRecorder()
    child = SplitMap("child.w3x", "Child", archive_source=child_source)
    parent = SplitMap(
        "parent.w3n", "Parent", archive_source=parent_source, sub_maps=[child]
    )

    # When: closing is requested twice.
    parent.close()
    parent.close()

    # Then: each resource is released at most once.
    assert parent_source.close_calls == 1
    assert child_source.close_calls == 1
