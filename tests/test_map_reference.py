"""Direct-map reference uses actual MPQ loading and retains all scoped evidence."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import struct

import pytest

from gametool import map_reference_sources as source_module
from gametool.base_objects import BASE_OBJECTS
from gametool.map_data import GameObject, GameObjectFieldEvidence, MapData
from gametool.map_reference_sources import MapReferenceCancelled
from gametool.map_reference_tables import map_object_tables
from gametool.mpq_crypto import CRYPT_TABLE, hash_name_bytes
from gametool.object_candidate_models import FieldEvidenceState
from gametool.pack_query_objects import OBJECT_TABLES
from gametool.reference_catalog import load_reference_catalog, search_reference_catalog
from gametool.reference_cli import (
    reference_result_to_dict,
    run_reference_cli,
    write_reference_export,
)
from gametool.w3obj import EXT_CATEGORY


def _encrypt(data: bytes, seed: int) -> bytes:
    output = []
    other = 0xEEEEEEEE
    for (word,) in struct.iter_unpack("<I", data):
        other = (other + CRYPT_TABLE[0x400 + (seed & 0xFF)]) & 0xFFFFFFFF
        output.append(word ^ ((seed + other) & 0xFFFFFFFF))
        seed = (((~seed & 0xFFFFFFFF) << 21) + 0x11111111 | (seed >> 11)) & 0xFFFFFFFF
        other = (word + other + (other << 5) + 3) & 0xFFFFFFFF
    return struct.pack(f"<{len(output)}I", *output)


def _archive(files: dict[str, bytes]) -> bytes:
    files = {**files, "(listfile)": "\r\n".join(files).encode("utf-8")}
    count = 1 << (len(files) * 2).bit_length()
    hashes = [b"\xff" * 16] * count
    blocks = []
    payloads = []
    offset = 32 + count * 16 + len(files) * 16
    for index, (name, payload) in enumerate(files.items()):
        encoded = name.encode("utf-8")
        slot = hash_name_bytes(encoded, 0) & (count - 1)
        while hashes[slot] != b"\xff" * 16:
            slot = (slot + 1) & (count - 1)
        hashes[slot] = struct.pack(
            "<IIHHI",
            hash_name_bytes(encoded, 1),
            hash_name_bytes(encoded, 2),
            0,
            0,
            index,
        )
        blocks.append(
            struct.pack("<IIII", offset, len(payload), len(payload), 0x81000000)
        )
        payloads.append(payload)
        offset += len(payload)
    return b"".join(
        (
            struct.pack(
                "<4sIIHHIIII",
                b"MPQ\x1a",
                32,
                offset,
                0,
                3,
                32,
                32 + count * 16,
                count,
                len(files),
            ),
            _encrypt(b"".join(hashes), hash_name_bytes(b"(hash table)", 3)),
            _encrypt(b"".join(blocks), hash_name_bytes(b"(block table)", 3)),
            *payloads,
        )
    )


def _objects(ext: str, code: str, name: str, *, base: str | None = None) -> bytes:
    if base is None:
        base = next(
            (
                key
                for key, (category, _fields) in BASE_OBJECTS.items()
                if category == EXT_CATEGORY[ext]
            ),
            "B000",
        )
    field = {
        "w3u": "unam",
        "w3t": "unam",
        "w3a": "anam",
        "w3h": "fnam",
        "w3q": "gnam",
        "w3b": "bnam",
        "w3d": "dnam",
    }[ext]
    mod = field.encode() + struct.pack("<i", 3)
    if ext in {"w3a", "w3q", "w3d"}:
        mod += struct.pack("<ii", 1, 0)
    mod += name.encode("utf-8") + b"\0" + b"\0" * 4
    return (
        struct.pack("<iii", 2, 0, 1)
        + base.encode()
        + code.encode()
        + struct.pack("<i", 1)
        + mod
    )


def _map(path: Path, files: dict[str, bytes]) -> Path:
    path.write_bytes(_archive(files))
    return path


def _map_records(catalog):
    return [
        row
        for row in catalog.records
        if row.kind == "objects" and row.scope != "builtin"
    ]


def test_real_map_covers_all_categories_and_full_field_cells(tmp_path: Path) -> None:
    name = "=完整\t名称\r\n第二行\ufeff'原文"
    files = {
        f"war3map.{ext}": _objects(ext, "X001", name if ext == "w3t" else ext)
        for ext in ("w3u", "w3t", "w3a", "w3h", "w3q", "w3b", "w3d")
    }
    path = _map(tmp_path / "all.w3x", files)
    before = path.read_bytes(), path.stat()
    catalog = load_reference_catalog(map_path=path)
    rows = _map_records(catalog)
    assert not catalog.complete  # Three categories have no shipped base-field catalog.
    assert all("已声明基础ID" in note for note in catalog.diagnostics)
    assert len(rows) == 7
    assert {row.category for row in rows} == set(OBJECT_TABLES) - {"英雄"}
    assert all(row.id == "X001" for row in rows)
    assert dict(catalog.map_scopes[0].category_counts)["英雄"] == 0
    item = next(row for row in rows if row.category == "物品")
    assert name in {value.value for value in item.values}
    assert name in {dict(value.extras).get("原始值") for value in item.values}
    result = search_reference_catalog(catalog, '="X001" && 第二行', kind="objects")
    assert result.records == (item,)
    member = next(
        source for source in catalog.sources if source.member_path == "war3map.w3t"
    )
    assert member.sha256 == hashlib.sha256(files["war3map.w3t"]).hexdigest()
    assert (
        member.path == str(path)
        and member.container_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    )
    assert any(value.source == member.id for value in item.values)
    root_source = next(source for source in catalog.sources if source.id == str(path))
    assert (
        len(root_source.source_descriptor_stamp)
        == len(root_source.source_path_stamp)
        == 6
    )
    assert root_source.source_descriptor_stamp[:3] == root_source.source_path_stamp[:3]
    assert all(
        source.source_file_state == "verified-after-load"
        for source in catalog.sources
        if source.path == str(path)
    )
    assert (path.read_bytes(), path.stat().st_mtime_ns) == (
        before[0],
        before[1].st_mtime_ns,
    )


def test_campaign_keeps_shared_once_children_and_bad_scope(tmp_path: Path) -> None:
    child = _archive(
        {
            "war3map.j": b"function main takes nothing returns nothing\ncall CreateItem('X001',0,0)\nendfunction"
        }
    )
    override = _archive({"war3map.w3t": _objects("w3t", "X001", "chapter override")})
    path = _map(
        tmp_path / "story.w3n",
        {
            "war3campaign.w3t": _objects("w3t", "X001", "shared"),
            "Maps\\First.w3x": child,
            "Maps\\Second.w3x": override,
            "Maps\\Broken.w3x": b"not an MPQ",
        },
    )
    catalog = load_reference_catalog(map_path=path)
    rows = _map_records(catalog)
    assert not catalog.complete
    assert [(row.scope, row.label) for row in rows] == [
        (str(path), "shared"),
        (f"{path}!Maps\\Second.w3x", "chapter override"),
    ]
    scopes = {scope.member_path: scope for scope in catalog.map_scopes}
    assert set(scopes) == {
        "",
        "Maps\\First.w3x",
        "Maps\\Second.w3x",
        "Maps\\Broken.w3x",
    }
    assert scopes["Maps\\First.w3x"].shared_references == (("物品", "X001"),)
    assert not scopes["Maps\\Broken.w3x"].complete
    assert any("Broken.w3x" in note for note in catalog.diagnostics)
    for row in rows:
        assert all("gamexray-bytes-" not in source for source in row.sources)
    limited = search_reference_catalog(
        catalog, "X001", kind="objects", source=str(path), limit=1
    )
    assert limited.omitted == 1 and len(limited.records) == 1
    assert limited.diagnostics == search_reference_catalog(catalog).diagnostics


def test_real_campaign_has_no_thousand_chapter_ceiling(tmp_path: Path) -> None:
    empty = _archive({})
    path = _map(tmp_path / "many.w3n", {f"Chapter{i}.w3x": empty for i in range(1001)})
    catalog = load_reference_catalog(map_path=path)
    assert catalog.complete, catalog.diagnostics
    assert len(catalog.map_scopes) == 1002
    assert all(
        sum(count for _category, count in scope.category_counts) == 0
        for scope in catalog.map_scopes
    )
    assert len({scope.scope for scope in catalog.map_scopes}) == 1002


def test_partial_binary_keeps_good_objects_and_full_diagnostics(tmp_path: Path) -> None:
    valid = _objects("w3t", "X001", "retained")
    broken = struct.pack("<iii", 2, 0, 2) + valid[12:] + b"BAD"
    path = _map(tmp_path / "broken.w3m", {"war3map.w3t": broken})
    catalog = load_reference_catalog(map_path=path)
    assert not catalog.complete
    assert [row.id for row in _map_records(catalog)] == ["X001"]
    assert any(
        "object-binary" in note and "war3map.w3t" in note
        for note in catalog.diagnostics
    )
    assert search_reference_catalog(catalog, limit=1).diagnostics


def test_map_source_mutation_is_not_complete_and_resources_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _map(
        tmp_path / "changed.w3x", {"war3map.w3t": _objects("w3t", "X001", "initial")}
    )
    original = source_module.load_map
    loaded: list[MapData] = []

    def changing(name: str, **kwargs):
        md = original(name, **kwargs)
        loaded.append(md)
        before = path.stat()
        payload = path.read_bytes().replace(b"initial", b"changed")
        path.write_bytes(payload)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        return md

    monkeypatch.setattr(source_module, "load_map", changing)
    catalog = load_reference_catalog(map_path=path)
    assert not catalog.complete and loaded[0]._closed
    assert _map_records(catalog)[0].label == "initial"
    assert any("交付前变化" in note for note in catalog.diagnostics)
    assert all(not scope.complete for scope in catalog.map_scopes)
    assert all(
        source.source_file_state == "changed-before-delivery"
        for source in catalog.sources
        if source.path == str(path)
    )


def test_cancelled_scan_closes_loaded_maps_and_does_not_deliver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _map(tmp_path / "cancel.w3x", {})
    loaded = []
    original = source_module.load_map

    def tracked(name: str, **kwargs):
        md = original(name, **kwargs)
        loaded.append(md)
        return md

    monkeypatch.setattr(source_module, "load_map", tracked)
    with pytest.raises(MapReferenceCancelled):
        load_reference_catalog(map_path=path, cancelled=lambda: bool(loaded))
    assert loaded[0]._closed


def test_export_allows_sibling_report_and_rejects_original_and_hardlink(
    tmp_path: Path,
) -> None:
    path = _map(
        tmp_path / "source.w3x", {"war3map.w3t": _objects("w3t", "X001", "source")}
    )
    before = path.read_bytes()
    result = search_reference_catalog(
        load_reference_catalog(map_path=path), source=str(path), kind="objects"
    )
    report = tmp_path / "report.json"
    write_reference_export(report, result)
    first = report.read_bytes()
    write_reference_export(report, result)
    assert report.read_bytes() == first
    assert json.loads(first)["map_path"] == str(path)
    alias = tmp_path / "alias.json"
    os.link(path, alias)
    for target in (path, alias):
        with pytest.raises(ValueError, match="输入源"):
            write_reference_export(target, result)
    assert path.read_bytes() == before == alias.read_bytes()


def test_cli_map_query_and_exclusive_inputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _map(
        tmp_path / "cli.w3x", {"war3map.w3t": _objects("w3t", "X001", "cli item")}
    )
    assert (
        run_reference_cli(
            [
                "X001",
                "--map",
                str(path),
                "--kind",
                "objects",
                "--source",
                str(path),
                "--json",
            ]
        )
        == 0
    )
    data = json.loads(capsys.readouterr().out)
    assert data["map_path"] == str(path) and data["matched"] == 1
    assert data["source_counts"] == [[str(path), 1]]
    assert run_reference_cli(["--map", str(path), "--pack", str(tmp_path)]) == 2
    assert "not allowed" in capsys.readouterr().err
    with pytest.raises(ValueError, match="不能同时"):
        load_reference_catalog(tmp_path, map_path=path)


def test_all_eight_declared_categories_and_conflicting_raw_fields_are_preserved() -> (
    None
):
    objects = {
        category: [GameObject(category, "w3u", "X001", "B000", category, True)]
        for category in OBJECT_TABLES
    }
    hero = objects["英雄"][0]
    conflict = GameObjectFieldEvidence(
        "unam",
        "名称",
        "other\nname",
        "war3map.w3u",
        40,
        state=FieldEvidenceState.CONFLICT,
        diagnostic="完整冲突证据",
        raw_value="TRIGSTR_1",
    )
    hero.field_evidence = (
        conflict,
        replace(conflict, value="another", raw_value="TRIGSTR_2"),
    )
    hero.field_blockers = hero.field_evidence
    tables = map_object_tables(
        MapData("unopened.w3x", "synthetic model", objects=objects)
    )
    assert all(
        len(tables[f"对象ID/{category}.tsv"].rows) == 2 for category in OBJECT_TABLES
    )
    fields = tables["对象字段.tsv"]
    assert "TRIGSTR_1" in {cell for row in fields.rows for cell in row}
    assert "TRIGSTR_2" in {cell for row in fields.rows for cell in row}
    assert "完整冲突证据" in {cell for row in fields.rows for cell in row}


def test_script_placeholders_do_not_claim_base_or_custom_state(tmp_path: Path) -> None:
    path = _map(
        tmp_path / "script.w3x",
        {
            "war3map.j": b"function main takes nothing returns nothing\ncall CreateItem('X001',0,0)\nendfunction"
        },
    )
    catalog = load_reference_catalog(map_path=path)
    record = _map_records(catalog)[0]
    assert record.state == "script-reference"
    assert dict(record.details)["基础ID"] == dict(record.details)["自定义标记"] == ""
    assert not any(value.source.startswith("builtin:") for value in record.values)
    assert reference_result_to_dict(search_reference_catalog(catalog))[
        "input_files"
    ] == (str(path),)


def _slk(name: str) -> bytes:
    return (
        f'ID;P\nC;X1;Y1;K"unitID"\nC;X2;Y1;K"Name"\n'
        f'C;X1;Y2;K"hfoo"\nC;X2;Y2;K"{name}"\nE\n'
    ).encode()


def test_real_slk_conflicts_keep_both_member_values_and_unknown_identity(
    tmp_path: Path,
) -> None:
    path = _map(
        tmp_path / "conflicts.w3x",
        {"Units\\UnitData.slk": _slk("alpha"), "Units\\UnitUI.slk": _slk("beta")},
    )
    catalog = load_reference_catalog(map_path=path)
    record = _map_records(catalog)[0]
    assert not catalog.complete and record.label == "hfoo"
    assert dict(record.details)["基础ID"] == dict(record.details)["自定义标记"] == ""
    assert {value.value for value in record.values if value.state == "conflict"} == {
        "alpha",
        "beta",
    }
    assert {value.source for value in record.values if value.state == "conflict"} == {
        f"{path}!Units\\UnitData.slk",
        f"{path}!Units\\UnitUI.slk",
    }
    assert any("semantic_field_conflict" in note for note in catalog.diagnostics)
    assert all(
        value.state in {"base-reference", "overridden-base"}
        for value in record.values
        if value.source.startswith("builtin:")
    )
    base_names = [
        value
        for value in record.values
        if value.source.startswith("builtin:") and value.label == "名称"
    ]
    assert base_names and all(value.state == "overridden-base" for value in base_names)


def test_text_has_unknown_identity_but_binary_original_table_is_confirmed(
    tmp_path: Path,
) -> None:
    text = b"[hfoo]\nName=text supplied name\n"
    path = _map(tmp_path / "text.w3x", {"Units\\HumanUnitStrings.txt": text})
    text_catalog = load_reference_catalog(map_path=path)
    text_record = _map_records(text_catalog)[0]
    assert text_catalog.complete, text_catalog.diagnostics
    assert (
        dict(text_record.details)["基础ID"]
        == dict(text_record.details)["自定义标记"]
        == ""
    )
    custom = _objects("w3u", "hfoo", "original name", base="hfoo")
    original = struct.pack("<ii", 2, 1) + custom[12:] + struct.pack("<i", 0)
    mixed = _map(
        tmp_path / "mixed.w3x",
        {"Units\\HumanUnitStrings.txt": text, "war3map.w3u": original},
    )
    mixed_catalog = load_reference_catalog(map_path=mixed)
    record = _map_records(mixed_catalog)[0]
    assert mixed_catalog.complete, mixed_catalog.diagnostics
    assert record.label == "text supplied name"
    assert dict(record.details)["基础ID"] == "hfoo"
    assert dict(record.details)["自定义标记"] == "否"
    assert {"original name", "text supplied name"} <= {
        value.value for value in record.values
    }


def test_conflicting_binary_base_declarations_remain_unselected(tmp_path: Path) -> None:
    first = _objects("w3t", "X001", "first", base="A000")
    second = _objects("w3t", "X001", "second", base="B000")
    path = _map(
        tmp_path / "identities.w3x",
        {"war3map.w3t": struct.pack("<iii", 2, 0, 2) + first[12:] + second[12:]},
    )
    catalog = load_reference_catalog(map_path=path)
    record = _map_records(catalog)[0]
    assert not catalog.complete
    assert dict(record.details)["基础ID"] == dict(record.details)["自定义标记"] == ""
    declarations = json.loads(dict(record.details)["完整身份声明"])
    assert [row[0] for row in declarations] == ["A000", "B000"]
    assert {"first", "second"} <= {value.value for value in record.values}
    assert any("声明冲突" in note for note in catalog.diagnostics)


def test_replaced_input_does_not_allow_export_to_retained_original_inode(
    tmp_path: Path,
) -> None:
    path = _map(
        tmp_path / "original.w3x", {"war3map.w3t": _objects("w3t", "X001", "original")}
    )
    alias = tmp_path / "held-old.json"
    os.link(path, alias)
    original_bytes = alias.read_bytes()
    result = search_reference_catalog(load_reference_catalog(map_path=path))
    replacement = _map(tmp_path / "replacement.w3x", {})
    os.replace(replacement, path)
    with pytest.raises(ValueError, match="硬链接"):
        write_reference_export(alias, result)
    assert alias.read_bytes() == original_bytes


def test_loader_without_matching_snapshot_proof_is_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool.archive_source import PathArchiveSource

    path = _map(tmp_path / "unbound.w3x", {})
    original = source_module.load_map

    def unbound(name: str, **kwargs):
        md = original(name, **kwargs)
        md.archive_source = PathArchiveSource(name)
        return md

    monkeypatch.setattr(source_module, "load_map", unbound)
    catalog = load_reference_catalog(map_path=path)
    assert not catalog.complete
    assert all(not scope.complete for scope in catalog.map_scopes)
    assert any("快照身份" in note for note in catalog.diagnostics)


def _custom_fields(code: str, base: str, fields: tuple[tuple[str, str], ...]) -> bytes:
    mods = b"".join(
        key.encode() + struct.pack("<i", 3) + value.encode("utf-8") + b"\0" + b"\0" * 4
        for key, value in fields
    )
    return (
        struct.pack("<iii", 2, 0, 1)
        + base.encode()
        + code.encode()
        + struct.pack("<i", len(fields))
        + mods
    )


def test_empty_binary_mods_and_zero_mod_declaration_keep_member_sources(
    tmp_path: Path,
) -> None:
    empty = _custom_fields(
        "E001", "ratf", (("unam", "empty probe"), ("ides", ""), ("xxxx", ""))
    )
    zero = _custom_fields("Z001", "ratf", ())
    path = _map(
        tmp_path / "empty.w3x",
        {"war3map.w3t": struct.pack("<iii", 2, 0, 2) + empty[12:] + zero[12:]},
    )
    catalog = load_reference_catalog(map_path=path)
    assert catalog.complete, catalog.diagnostics
    records = {row.id: row for row in _map_records(catalog)}
    fields = records["E001"].values
    for key in ("ides", "xxxx"):
        raw = [
            value
            for value in fields
            if value.key == key
            and dict(value.extras).get("证据角色") == "二进制原始修改"
        ]
        assert len(raw) == 1 and raw[0].value == ""
    source_id = f"{path}!war3map.w3t"
    assert source_id in records["Z001"].sources
    found = search_reference_catalog(
        catalog, "Z001", kind="objects", source="war3map.w3t"
    )
    assert found.records == (records["Z001"],)


def test_wts_dependency_and_exact_raw_trigger_token_are_queryable(
    tmp_path: Path,
) -> None:
    path = _map(
        tmp_path / "wts.w3x",
        {
            "war3map.w3t": _custom_fields(
                "T001", "ratf", (("unam", "TRIGSTR_000001"),)
            ),
            "war3map.wts": b"STRING 1\n{\nresolved WTS name\n}\n",
        },
    )
    catalog = load_reference_catalog(map_path=path)
    assert catalog.complete, catalog.diagnostics
    record = _map_records(catalog)[0]
    assert record.label == "resolved WTS name"
    assert "TRIGSTR_000001" in {value.value for value in record.values}
    assert f"{path}!war3map.wts" in record.sources
    assert search_reference_catalog(
        catalog, "T001", kind="objects", source="war3map.wts"
    ).records == (record,)


def test_campaign_explicit_shared_base_inherits_by_category_and_empty_overrides(
    tmp_path: Path,
) -> None:
    root_item = _custom_fields(
        "X001", "ratf", (("unam", "shared item"), ("ides", "shared description"))
    )
    root_unit = _custom_fields("X001", "hfoo", (("unam", "shared unit"),))
    child = _archive({"war3map.w3t": _custom_fields("X002", "X001", (("ides", ""),))})
    path = _map(
        tmp_path / "inherit.w3n",
        {
            "war3campaign.w3t": root_item,
            "war3campaign.w3u": root_unit,
            "Chapter.w3x": child,
        },
    )
    catalog = load_reference_catalog(map_path=path)
    assert catalog.complete, catalog.diagnostics
    records = _map_records(catalog)
    assert len(records) == 3
    current = next(row for row in records if row.id == "X002")
    assert current.category == "物品" and current.label == "shared item"
    assert dict(current.details)["共享基础范围"] == str(path)
    assert any(
        value.key == "ides"
        and value.value == ""
        and value.state == "raw-binary-evidence"
        for value in current.values
    )
    parent_descriptions = [
        value for value in current.values if value.value == "shared description"
    ]
    assert parent_descriptions and all(
        value.state == "overridden-campaign" for value in parent_descriptions
    )
    assert not any(value.value == "shared unit" for value in current.values)
    assert f"{path}!war3campaign.w3t" in current.sources


def test_campaign_transitive_bases_cycles_missing_and_builtin_overrides(
    tmp_path: Path,
) -> None:
    roots = (
        _custom_fields(
            "A003", "ratf", (("unam", "ancestor"), ("ides", "ancestor description"))
        ),
        _custom_fields("B003", "A003", (("igol", "321"),)),
        _custom_fields("ratf", "ratf", (("igol", "123"),)),
        _custom_fields("cy01", "cy02", ()),
        _custom_fields("cy02", "cy01", ()),
        _custom_fields("MISS", "none", ()),
    )
    shared = struct.pack("<iii", 2, 0, len(roots)) + b"".join(row[12:] for row in roots)
    local = (
        _custom_fields("C003", "B003", (("unam", "chapter"),)),
        _custom_fields("G003", "ratf", (("unam", "shared gold"),)),
    )
    child = _archive(
        {
            "war3map.w3t": struct.pack("<iii", 2, 0, 2)
            + b"".join(row[12:] for row in local)
        }
    )
    path = _map(
        tmp_path / "chains.w3n", {"war3campaign.w3t": shared, "Chapter.w3x": child}
    )
    catalog = load_reference_catalog(map_path=path)
    assert not catalog.complete
    rows = {row.id: row for row in _map_records(catalog)}
    assert "ancestor description" in {value.value for value in rows["C003"].values}
    assert any(value.value == "321" for value in rows["C003"].values)
    assert rows["B003"].label == "ancestor"
    assert any(
        "循环" in note and "cy01" in note and "cy02" in note
        for note in catalog.diagnostics
    )
    assert any("none" in note and "未在同类别" in note for note in catalog.diagnostics)
    assert not any(
        value.source.startswith("builtin:")
        and value.label == "金币"
        and value.state
        in {"inherited-evidence", "campaign-inherited", "base-reference"}
        for value in rows["G003"].values
    )
    assert any(value.value == "123" for value in rows["G003"].values)


def test_conflicting_wts_keeps_unresolved_dependency_link(tmp_path: Path) -> None:
    path = _map(
        tmp_path / "wts-conflict.w3x",
        {
            "war3map.w3t": _custom_fields("W002", "ratf", (("unam", "TRIGSTR_1"),)),
            "war3map.wts": b"STRING 1\n{\nfirst\n}\nSTRING 1\n{\nsecond\n}\n",
        },
    )
    catalog = load_reference_catalog(map_path=path)
    assert not catalog.complete
    record = _map_records(catalog)[0]
    assert f"{path}!war3map.wts" in record.sources
    assert search_reference_catalog(
        catalog, "W002", kind="objects", source="war3map.wts"
    ).records == (record,)
    assert "TRIGSTR_1" in {value.value for value in record.values}


def test_incomplete_shared_base_propagates_to_dependent_child_scope(
    tmp_path: Path,
) -> None:
    shared = _custom_fields("A004", "none", (("unam", "shared missing base"),))
    child = _archive({"war3map.w3t": _custom_fields("C004", "A004", ())})
    path = _map(
        tmp_path / "partial-chain.w3n",
        {"war3campaign.w3t": shared, "Chapter.w3x": child},
    )
    catalog = load_reference_catalog(map_path=path)
    assert not catalog.complete
    scopes = {scope.member_path: scope for scope in catalog.map_scopes}
    assert not scopes["Chapter.w3x"].complete
    assert any(
        "none" in note and "A004" in note and "继承来源" in note
        for note in scopes["Chapter.w3x"].diagnostics
    )
    record = next(row for row in _map_records(catalog) if row.id == "C004")
    assert record.label == "shared missing base" and record.diagnostics
