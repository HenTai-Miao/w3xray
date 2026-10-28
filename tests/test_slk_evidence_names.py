"""Explicit empty names cannot turn inherited labels into map-defined names."""

from __future__ import annotations

import csv
from pathlib import Path
import struct

import pytest

from gametool.base_names import BASE_NAMES
from gametool.knowledge_object_exports import write_box_ids, write_object_ids
from gametool.fields import label_for
from gametool.item_relation_fields import object_field_relations
from gametool.map_data import MapData
from gametool.object_candidates import (
    ObjectCandidate,
    ObjectFieldValue,
    ObjectSourceKind,
    collect_object_candidates,
)
from gametool.object_pipeline import load_object_pipeline, populate_object_pipeline


class _Archive:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.path = "empty-name.w3x"
        self._data = b""

    def has_file(self, name: str) -> bool:
        return name in self.files

    def read_file(self, name: str) -> bytes:
        return self.files[name]

    def list_files(self) -> list[str]:
        return list(self.files)

    def close(self) -> None:
        pass


def _slk(*, explicit_name: bool) -> bytes:
    field = "Name" if explicit_name else "race"
    value = "" if explicit_name else "human"
    return (
        'ID;P\nC;X1;Y1;K"unitID"\nC;X2;Y1;K"' + field + '"\n'
        'C;X3;Y1;K"Propernames"\nC;X1;Y2;K"hfoo"\nC;X2;Y2;K"' + value + '"\n'
        'C;X3;Y2;K"Unselected propername"\nE\n'
    ).encode()


def _binary_empty_name(
    field: str = "unam", old_id: str = "hfoo", new_id: str = "H001"
) -> bytes:
    mod = field.encode("latin-1") + struct.pack("<i", 3) + b"\0" + struct.pack("<I", 0)
    obj = (old_id + new_id).encode("latin-1") + struct.pack("<i", 1) + mod
    return struct.pack("<ii", 2, 0) + struct.pack("<i", 1) + obj


@pytest.mark.parametrize("source", ["slk", "binary", "text"])
def test_explicit_empty_name_survives_materialization_and_real_exports(
    source: str, tmp_path: Path
) -> None:
    files = {
        "slk": {"UnitData.slk": _slk(explicit_name=True)},
        "binary": {"war3map.w3u": _binary_empty_name()},
        "text": {
            "Units\\HumanUnitStrings.txt": b"[hfoo]\nName=\nPropernames=Unselected propername\n"
        },
    }[source]
    code = "H001" if source == "binary" else "hfoo"
    md = MapData("empty-name.w3x", "empty-name")
    load_object_pipeline(md, _Archive(files), {}, base_objects={})
    obj = md.obj_index[code]
    assert obj.name == code
    assert obj.field_values["display:name"] == ""
    assert any(
        row.value == "" and row.source != "base names" for row in obj.field_evidence
    )
    output = tmp_path / "pack"
    assert write_object_ids(md, str(output)) == 1
    assert write_box_ids(md, str(output)) == 1
    with (output / "单位.tsv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream, delimiter="\t"))
    assert rows[0][4] == "名称" and rows[1][4] == code
    assert f"名字：{code}\n" in (output / "单位ID.txt").read_text(encoding="utf-8")


def test_absent_name_keeps_existing_base_fallback_and_declared_propername() -> None:
    payload = _slk(explicit_name=False)
    archive = _Archive({"UnitData.slk": payload})
    md = MapData("absent-name.w3x", "absent-name")
    load_object_pipeline(md, archive, {}, base_objects={})
    assert md.obj_index["hfoo"].name == "Unselected propername"
    assert "display:name" not in md.obj_index["hfoo"].field_values
    archive.files["UnitData.slk"] = payload.replace(
        b'C;X3;Y2;K"Unselected propername"\n', b""
    )
    load_object_pipeline(md, archive, {}, base_objects={})
    assert md.obj_index["hfoo"].name == BASE_NAMES["hfoo"]


@pytest.mark.parametrize(
    ("category", "extension", "field", "old_id", "code", "old_value"),
    [
        ("物品", "w3t", "iabi", "ratf", "I001", "A000"),
        ("单位", "w3u", "usei", "hfoo", "H001", "I000"),
    ],
)
def test_binary_explicit_empty_lists_suppress_inherited_fields_and_relations(
    category: str, extension: str, field: str, old_id: str, code: str, old_value: str
) -> None:
    inherited = ObjectCandidate(
        category,
        code,
        old_id,
        False,
        "base",
        (
            ObjectFieldValue(
                field, label_for(field), old_value, "inherited", ObjectSourceKind.BASE
            ),
        ),
        (),
    )
    md = MapData("empty-list.w3x", "empty-list")
    populate_object_pipeline(md, (inherited,), {}, include_named_bases=False)
    assert len(tuple(object_field_relations(md))) == 1
    archive = _Archive(
        {f"war3map.{extension}": _binary_empty_name(field, old_id, code)}
    )
    binary = collect_object_candidates(archive, {})
    populate_object_pipeline(md, (inherited, *binary), {}, include_named_bases=False)
    obj = md.obj_identity_index[(category, code)]
    assert obj.field_values[field] == ""
    assert not tuple(object_field_relations(md))
    assert any(
        row.key == field and row.value == old_value for row in obj.field_evidence
    )
    assert any(row.key == field and row.value == "" for row in obj.field_evidence)
