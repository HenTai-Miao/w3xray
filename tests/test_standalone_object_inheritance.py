"""Standalone binary base chains reach complete object exports and queries."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import struct

import pytest

from gametool.knowledge_object_exports import format_object_fields, write_object_ids
from gametool.map_data import MapData
from gametool.map_loader import load_map
from gametool.pack_query_cli import execute_pack_query, load_item_tooltips
from gametool.pack_query_options import PackQueryCliOptions
from gametool.reference_catalog import load_reference_catalog
from tests.skin_layers_fixture import mpq, object_file, slk


def _custom_table(*objects: bytes) -> bytes:
    """Assemble independently authored version-2 custom records in encoded order."""
    return struct.pack("<iii", 2, 0, len(objects)) + b"".join(
        record[12:] for record in objects
    )


def _pack(md: MapData, path: Path) -> None:
    path.mkdir()
    write_object_ids(md, str(path / "对象ID"))
    (path / "对象字段.tsv").write_text(
        format_object_fields(md), encoding="utf-8", newline=""
    )


@pytest.mark.parametrize("suffix", (".w3x", ".w3m"))
@pytest.mark.parametrize("parent_first", (False, True))
def test_custom_chain_reaches_standalone_pack_and_reference(
    tmp_path: Path, suffix: str, parent_first: bool
) -> None:
    ancestor = object_file(
        "w3t",
        (
            ("unam", "ancestor original", 0, 0),
            ("ides", "ancestor description", 0, 0),
            ("utip", "ancestor tip", 0, 0),
            ("igol", 99, 0, 0),
            ("iabi", "A001", 0, 0),
        ),
        code="I001",
    )
    middle = object_file("w3t", (("utip", "", 0, 0),), code="I002", base="I001")
    child = object_file(
        "w3t", (("ides", "", 0, 0), ("igol", 7, 0, 0)), code="I003", base="I002"
    )
    records = (ancestor, middle, child) if parent_first else (child, middle, ancestor)
    path = tmp_path / f"standalone{suffix}"
    path.write_bytes(
        mpq(
            {
                "war3map.w3t": _custom_table(*records),
                "war3mapSkin.w3t": object_file(
                    "w3t",
                    (("unam", "ancestor skin", 0, 0), ("igol", 17, 0, 0)),
                    code="I001",
                ),
                "war3map.w3u": object_file(
                    "w3u",
                    (("unam", "same-code unit", 0, 0), ("usei", "ratf", 0, 0)),
                    code="I001",
                    base="hfoo",
                ),
                "war3map.w3a": object_file(
                    "w3a", (("anam", "linked skill", 0, 0),), code="A001", base="ANcl"
                ),
            }
        )
    )
    source_bytes = path.read_bytes()
    md = load_map(str(path))
    try:
        item = md.obj_identity_index[("物品", "I003")]
        assert item.base_id == "I002" and item.is_custom
        assert item.name == "ancestor skin"
        assert item.field_values["igol"] == "7"
        assert item.field_values["ides"] == item.field_values["utip"] == ""
        assert item.field_values["iabi"] == "A001"
        assert item.field_sources["display:name"] == "war3mapSkin.w3t"
        assert "same-code unit" not in {row.value for row in item.field_evidence}
        assert "usei" not in item.field_values
        assert any(
            row.key == "igol" and row.value == "99" and row.state == "overridden"
            for row in item.field_evidence
        )
        assert any(
            row.key == "igol" and row.value == "17" and row.state == "overridden"
            for row in item.field_evidence
        )
        inherited_skill = next(row for row in item.field_evidence if row.key == "iabi")
        provenance = json.loads(inherited_skill.encoded_evidence)
        assert provenance["gamexray_inheritance"] == [
            {"category": "物品", "object_id": "I001"},
            {"category": "物品", "object_id": "I002"},
        ]
        assert b"A001\0" in base64.b64decode(provenance["raw_bytes_base64"])
        current_names = [
            row.raw_value
            for row in md.object_texts.for_object("物品", "I003")
            if row.semantic_field == "name" and row.is_current
        ]
        assert current_names == ["ancestor skin"]
        assert not any(
            note.component == "object-inheritance" for note in md.diagnostics
        )
        pack = tmp_path / "pack"
        _pack(md, pack)
        assert load_item_tooltips(pack)["I003"] == ""
        price = execute_pack_query(PackQueryCliOptions(str(pack), "price", "I003"))
        assert price.exit_code == 0
        assert "7" in price.render() and "冲突" not in price.render()
        detail = execute_pack_query(PackQueryCliOptions(str(pack), "item", "I003"))
        assert detail.exit_code == 0
        assert all(
            value in detail.render()
            for value in (
                "ancestor skin",
                "ancestor original",
                "99",
                "overridden",
                "A001",
            )
        )
    finally:
        md.close()
    catalog = load_reference_catalog(map_path=path)
    record = next(
        row
        for row in catalog.records
        if row.id == "I003" and row.category == "物品" and row.scope == str(path)
    )
    assert record.label == "ancestor skin"
    assert any(value.value == "7" and value.key == "igol" for value in record.values)
    assert any(value.value == "A001" and value.key == "iabi" for value in record.values)
    assert path.read_bytes() == source_bytes


def test_standalone_binary_inherits_category_qualified_local_slk_base(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tables.w3x"
    path.write_bytes(
        mpq(
            {
                "Units\\ItemData.slk": slk(
                    ("itemID", "Name", "goldcost"), (("s000", "local item base", "41"),)
                ),
                "Units\\UnitData.slk": slk(
                    ("unitID", "Name", "goldcost"), (("s000", "other category", "999"),)
                ),
                "war3map.w3t": object_file(
                    "w3t", (("unam", "own name", 0, 0),), code="I001", base="s000"
                ),
            }
        )
    )
    md = load_map(str(path))
    try:
        item = md.obj_identity_index[("物品", "I001")]
        assert item.name == "own name" and item.field_values["goldcost"] == "41"
        assert item.field_sources["goldcost"] == "Units\\ItemData.slk"
        assert "999" not in {row.value for row in item.field_evidence}
        assert not any(
            note.component == "object-inheritance" for note in md.diagnostics
        )
        pack = tmp_path / "pack"
        _pack(md, pack)
        result = execute_pack_query(PackQueryCliOptions(str(pack), "price", "I001"))
        assert result.exit_code == 0 and "41" in result.render()
        assert "冲突" not in result.render()
    finally:
        md.close()


def test_standalone_custom_object_inherits_modified_original_record(
    tmp_path: Path,
) -> None:
    original = object_file(
        "w3t", (("unam", "modified original", 0, 0), ("igol", 23, 0, 0)), code="ratf"
    )
    child = object_file("w3t", (), code="I001", base="ratf")
    raw = (
        struct.pack("<ii", 2, 1)
        + b"ratf\0\0\0\0"
        + original[20:]
        + struct.pack("<i", 1)
        + child[12:]
    )
    path = tmp_path / "original.w3x"
    path.write_bytes(mpq({"war3map.w3t": raw}))
    md = load_map(str(path))
    try:
        item = md.obj_identity_index[("物品", "I001")]
        assert item.name == "modified original"
        assert item.field_values["igol"] == "23"
        assert item.field_sources["igol"] == "war3map.w3t"
        assert not any(note.component == "object-binary" for note in md.diagnostics)
    finally:
        md.close()


def test_standalone_missing_cyclic_and_cross_category_bases_retain_diagnostics(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unavailable.w3x"
    path.write_bytes(
        mpq(
            {
                "war3map.w3t": _custom_table(
                    object_file(
                        "w3t",
                        (("unam", "cycle first", 0, 0),),
                        code="C001",
                        base="C002",
                    ),
                    object_file(
                        "w3t",
                        (("ides", "cycle second", 0, 0),),
                        code="C002",
                        base="C001",
                    ),
                    object_file(
                        "w3t",
                        (("unam", "known own name", 0, 0),),
                        code="M001",
                        base="MISS",
                    ),
                    object_file("w3t", (), code="M002", base="M001"),
                    object_file(
                        "w3t",
                        (("ides", "own item text", 0, 0),),
                        code="X001",
                        base="U001",
                    ),
                ),
                "war3map.w3u": object_file(
                    "w3u", (("unam", "unrelated unit", 0, 0),), code="U001", base="hfoo"
                ),
            }
        )
    )
    md = load_map(str(path))
    try:
        assert "ides" not in md.obj_identity_index[("物品", "C001")].field_values
        assert md.obj_identity_index[("物品", "C002")].name == "C002"
        descendant = md.obj_identity_index[("物品", "M002")]
        assert (
            descendant.name == "known own name"
            and "igol" not in descendant.field_values
        )
        other = md.obj_identity_index[("物品", "X001")]
        assert other.name == "X001" and other.field_values["ides"] == "own item text"
        assert "unrelated unit" not in {row.value for row in other.field_evidence}
        messages = [
            note.message
            for note in md.diagnostics
            if note.component == "object-inheritance"
        ]
        assert any("C001" in message and "循环" in message for message in messages)
        assert any("C002" in message and "循环" in message for message in messages)
        assert any("M002" in message and "MISS" in message for message in messages)
        assert any("X001" in message and "U001" in message for message in messages)
        assert not any(note.component == "object-binary" for note in md.diagnostics)
    finally:
        md.close()


def test_standalone_ambiguous_base_does_not_choose_local_or_builtin_fields(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ambiguous.w3m"
    path.write_bytes(
        mpq(
            {
                "war3map.w3t": _custom_table(
                    object_file(
                        "w3t", (("unam", "own name", 0, 0),), code="X001", base="I001"
                    ),
                    object_file("w3t", (), code="X001", base="ratf"),
                    object_file("w3t", (("igol", 29, 0, 0),), code="I001", base="ratf"),
                )
            }
        )
    )
    md = load_map(str(path))
    try:
        item = md.obj_identity_index[("物品", "X001")]
        assert item.name == "own name" and item.base_id == ""
        assert "igol" not in item.field_values
        assert not any(row.source.startswith("base:") for row in item.field_evidence)
        assert any(
            note.component == "object-inheritance" and "声明冲突" in note.message
            for note in md.diagnostics
        )
    finally:
        md.close()


def test_standalone_unavailable_four_byte_base_keeps_every_identity_byte(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invalid.w3x"
    path.write_bytes(
        mpq(
            {
                "war3map.w3t": object_file(
                    "w3t",
                    (("unam", "retained own name", 0, 0), ("igol", 13, 0, 0)),
                    code="I001",
                    base="BAD\0",
                )
            }
        )
    )
    md = load_map(str(path))
    try:
        item = md.obj_identity_index[("物品", "I001")]
        assert item.name == "retained own name" and item.field_values["igol"] == "13"
        assert item.base_id == "BAD\0"
        assert not any(row.source.startswith("base:") for row in item.field_evidence)
        assert any(
            note.component == "object-inheritance"
            and "未在同类别" in note.message
            and "BAD" in note.message
            and "war3map.w3t" in note.message
            for note in md.diagnostics
        )
    finally:
        md.close()


def test_standalone_truncated_base_declaration_retains_complete_records(
    tmp_path: Path,
) -> None:
    valid = object_file(
        "w3t", (("unam", "complete object", 0, 0), ("igol", 13, 0, 0)), code="I001"
    )
    raw = struct.pack("<iii", 2, 0, 2) + valid[12:] + b"BAD"
    path = tmp_path / "truncated.w3x"
    path.write_bytes(mpq({"war3map.w3t": raw}))
    md = load_map(str(path))
    try:
        item = md.obj_identity_index[("物品", "I001")]
        assert item.name == "complete object" and item.field_values["igol"] == "13"
        assert not any(
            code.startswith("BAD") for _category, code in md.obj_identity_index
        )
        assert any(
            note.component == "object-binary"
            and note.source == "war3map.w3t"
            and note.message
            for note in md.diagnostics
        )
    finally:
        md.close()


@pytest.mark.parametrize("value", (7, 37, ""))
def test_child_override_marks_same_member_parent_evidence_before_export(
    tmp_path: Path, value: str | int
) -> None:
    path = tmp_path / "override-state.w3x"
    path.write_bytes(
        mpq(
            {
                "war3map.w3t": _custom_table(
                    object_file("w3t", (), code="I003", base="I002"),
                    object_file(
                        "w3t", (("igol", value, 0, 0),), code="I002", base="I001"
                    ),
                    object_file("w3t", (("igol", 37, 0, 0),), code="I001", base="ratf"),
                )
            }
        )
    )
    md = load_map(str(path))
    try:
        for code in ("I002", "I003"):
            obj = md.obj_identity_index[("物品", code)]
            assert obj.field_values["igol"] == str(value)
            rows = [row for row in obj.field_evidence if row.key == "igol"]
            by_declared_object = {
                json.loads(row.encoded_evidence)["new_id"]: row for row in rows
            }
            parent = by_declared_object["I001"]
            current = by_declared_object["I002"]
            assert parent.value == "37" and parent.state == "overridden"
            assert current.value == str(value) and current.state == "confirmed"
            assert parent.source == current.source == "war3map.w3t"
            assert base64.b64decode(
                json.loads(parent.encoded_evidence)["raw_bytes_base64"]
            )
        pack = tmp_path / "pack"
        _pack(md, pack)
        detail = execute_pack_query(PackQueryCliOptions(str(pack), "item", "I002"))
        assert detail.exit_code == 0 and "overridden" in detail.render()
    finally:
        md.close()


def test_binary_child_override_demotes_inherited_slk_field_alias(
    tmp_path: Path,
) -> None:
    path = tmp_path / "alias-override.w3x"
    path.write_bytes(
        mpq(
            {
                "Units\\ItemData.slk": slk(
                    ("itemID", "Name", "goldcost"), (("s000", "local item base", "41"),)
                ),
                "war3map.w3t": object_file(
                    "w3t", (("igol", 7, 0, 0),), code="I001", base="s000"
                ),
            }
        )
    )
    md = load_map(str(path))
    try:
        item = md.obj_identity_index[("物品", "I001")]
        assert item.field_values["igol"] == "7" and "goldcost" not in item.field_values
        assert any(
            row.key == "goldcost"
            and row.value == "41"
            and row.state == "overridden"
            and row.source == "Units\\ItemData.slk"
            for row in item.field_evidence
        )
    finally:
        md.close()


def test_child_same_tier_values_are_retained_beside_overridden_parent(
    tmp_path: Path,
) -> None:
    path = tmp_path / "same-tier.w3x"
    path.write_bytes(
        mpq(
            {
                "war3map.w3t": _custom_table(
                    object_file(
                        "w3t",
                        (("igol", 7, 0, 0), ("igol", 9, 0, 0)),
                        code="I002",
                        base="I001",
                    ),
                    object_file("w3t", (("igol", 37, 0, 0),), code="I001"),
                )
            }
        )
    )
    md = load_map(str(path))
    try:
        item = md.obj_identity_index[("物品", "I002")]
        assert {
            (row.value, row.state) for row in item.field_evidence if row.key == "igol"
        } == {("7", "confirmed"), ("9", "confirmed"), ("37", "overridden")}
        pack = tmp_path / "pack"
        _pack(md, pack)
        detail = execute_pack_query(PackQueryCliOptions(str(pack), "item", "I002"))
        assert detail.exit_code == 0
        assert all(value in detail.render() for value in ("7", "9", "37", "overridden"))
    finally:
        md.close()
