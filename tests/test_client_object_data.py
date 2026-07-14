"""Selected Warcraft client data enriches map object inheritance."""

from __future__ import annotations

import struct

import pytest

from w3xtool.client_object_data import snapshot_client_base_objects
from w3xtool.load_context import build_map_load_context
from w3xtool.map_data import MapData
from w3xtool.map_loader import _load_map_impl
from w3xtool.object_pipeline import load_object_pipeline
from w3xtool.object_text_models import ObjectTextState


class FakeClientSource:
    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = {_normalize(name): payload for name, payload in files.items()}
        self.closed = False

    def has_file(self, name: str) -> bool:
        return not self.closed and _normalize(name) in self._files

    def read_file(self, name: str) -> bytes:
        if self.closed:
            raise OSError("client source is closed")
        return self._files[_normalize(name)]

    def close(self) -> None:
        self.closed = True


class FakeMapArchive:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.path = "fixture.w3x"
        self._data = b""
        self._files = {
            _normalize(name): (name, payload) for name, payload in files.items()
        }

    def has_file(self, name: str) -> bool:
        return _normalize(name) in self._files

    def read_file(self, name: str) -> bytes:
        return self._files[_normalize(name)][1]

    def list_files(self) -> list[str]:
        return [name for name, _payload in self._files.values()]

    def close(self) -> None:
        return None


def test_pipeline_inherits_client_base_name_health_and_icon() -> None:
    # Given: client tables describe a base unit omitted from the bundled snapshot.
    source = _client_source()
    archive = FakeMapArchive({"war3map.w3u": _custom_unit("hX01", "H001")})
    md = MapData(path=archive.path, name="fixture")

    # When: the selected client data participates in object construction.
    load_object_pipeline(md, archive, {}, base_objects={}, game_data_source=source)

    # Then: the custom map unit inherits all client display and data fields.
    inherited = md.obj_index["H001"]
    assert inherited.name == "Client Base"
    assert dict(inherited.fields)["生命"] == "777"
    assert inherited.icon == "ReplaceableTextures\\CommandButtons\\BTNClient.blp"
    assert not source.closed


def test_load_context_snapshots_client_bases_before_closing_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the shared source must not survive beyond context construction.
    source = _client_source()
    monkeypatch.setattr(
        "w3xtool.game_data_source.open_game_data_source", lambda _path: source
    )

    # When: context construction reads client data and closes its source.
    context = build_map_load_context(game_data_path="client-data")

    # Then: immutable client objects remain usable by the later map load.
    assert source.closed
    assert tuple(item.obj_id for item in context.client_base_objects) == ("hX01",)
    assert context.client_text_available is True
    archive = FakeMapArchive({"war3map.w3u": _custom_unit("hX01", "H001")})
    md = _load_map_impl(archive, archive.path, 0, None, context)
    assert md.obj_index["H001"].name == "Client Base"
    assert md.obj_index["H001"].icon.endswith("BTNClient.blp")
    name_row = next(
        row
        for row in md.object_texts.for_object("单位", "H001")
        if row.role == "名称" and row.raw_value
    )
    assert (name_row.raw_value, name_row.state) == (
        "Client Base",
        ObjectTextState.CLIENT_FILL,
    )


def test_client_snapshot_retains_all_text_evidence_after_source_close() -> None:
    # Given: both Func and Strings tables contain distinct values for one base object.
    source = FakeClientSource(
        {
            "Units\\HumanUnitFunc.txt": b"[hX01]\nName=Internal\nUbertip=First\n",
            "Units\\HumanUnitStrings.txt": b"[hX01]\nName=Localized\nUbertip=Second\n",
        },
    )

    # When: client evidence is snapshotted and the native source is closed.
    snapshot = snapshot_client_base_objects(source)
    source.close()

    # Then: availability and both source-bearing variants survive independently.
    assert snapshot.text_available is True
    assert len(snapshot.objects) == 1
    evidence = snapshot.objects[0].evidence_fields
    assert {field.value for field in evidence if field.key.casefold() == "ubertip"} == {
        "First",
        "Second",
    }
    assert {
        field.source for field in evidence if field.key.casefold() == "ubertip"
    } == {
        "Units\\HumanUnitFunc.txt",
        "Units\\HumanUnitStrings.txt",
    }


def test_absent_client_source_has_no_text_availability() -> None:
    # Given / When: no Warcraft client source is selected.
    snapshot = snapshot_client_base_objects(None)

    # Then: the absence is explicit rather than an empty-but-available snapshot.
    assert snapshot.objects == ()
    assert snapshot.text_available is False


def _client_source() -> FakeClientSource:
    return FakeClientSource(
        {
            "Units\\HumanUnitStrings.txt": b"[hX01]\nName=Client Base\n",
            "Units\\UnitData.slk": _slk(
                ("unitID", "HP", "Art"),
                ("hX01", "777", "ReplaceableTextures\\CommandButtons\\BTNClient.blp"),
            ),
        }
    )


def _custom_unit(base_id: str, object_id: str) -> bytes:
    custom = (
        base_id.encode("latin-1") + object_id.encode("latin-1") + struct.pack("<i", 0)
    )
    return struct.pack("<ii", 2, 0) + struct.pack("<i", 1) + custom


def _slk(columns: tuple[str, ...], row: tuple[str, ...]) -> bytes:
    lines = ["ID;P", f"B;X{len(columns)};Y2"]
    lines.extend(f'C;X{x};Y1;K"{column}"' for x, column in enumerate(columns, 1))
    lines.extend(f'C;X{x};Y2;K"{value}"' for x, value in enumerate(row, 1))
    lines.append("E")
    return "\n".join(lines).encode("latin-1")


def _normalize(name: str) -> str:
    return name.replace("/", "\\").casefold()
