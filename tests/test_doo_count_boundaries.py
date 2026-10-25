"""Byte-derived DOO count limits, required tails, and layout completeness."""

from __future__ import annotations

import struct
from dataclasses import dataclass

import pytest

from gametool.doo import (
    _Reader,
    _attempt_doodads,
    _attempt_units,
    _read_doodad,
    _read_unit,
    parse_doodads,
    parse_units,
)
from gametool.doo_drops import DropCountError, read_drop_sets


@dataclass(frozen=True)
class _Record:
    data: bytes
    counts: dict[str, int]


def _i32(value: int) -> bytes:
    return struct.pack("<i", value)


def _header(count: int, *, version: int = 8) -> bytes:
    return b"W3do" + _i32(version) + _i32(11) + _i32(count)


def _unit_record(
    *,
    kind: str = "",
    count: int = 0,
    skin: bool = False,
    v7: bool = False,
    serial: int = 1,
    random_flag: int = -1,
) -> _Record:
    data = bytearray(b"hfoo" + _i32(0) + struct.pack("<7f", 0, 0, 0, 0, 1, 1, 1))
    if skin:
        data += b"\0" * 4  # Deliberately plausible to the wrong classic layout.
    data += b"\0" + _i32(0) + b"\0\0" + _i32(0) * 2 + _i32(-1)
    counts: dict[str, int] = {}

    def add_count(name: str, value: int) -> None:
        counts[name] = len(data)
        data.extend(_i32(value))

    groups = count if kind == "drop_groups" else (1 if kind == "drop_entries" else 0)
    add_count("drop_groups", groups)
    for index in range(groups):
        entries = count if kind == "drop_entries" else 0
        add_count(f"drop_entries_{index}", entries)
        data += (b"ratf" + _i32(100)) * entries
    data += _i32(0) * 3  # Gold, acquisition range, hero level.
    if not v7:
        data += _i32(0) * 3
    items = count if kind == "items" else 0
    add_count("items", items)
    data += (_i32(0) + b"ratf") * items
    abilities = count if kind == "abilities" else 0
    add_count("abilities", abilities)
    data += (b"AHbz" + _i32(1) + _i32(2)) * abilities
    flag = 2 if kind == "random" else random_flag
    data += _i32(flag)
    if flag == 0:
        data += _i32(0)
    elif flag == 1:
        data += _i32(3) + _i32(7)
    elif flag == 2:
        add_count("random", count)
        data += (b"hpea" + _i32(100)) * count
    if not v7:
        data += _i32(-1) * 2
    data += _i32(serial)
    return _Record(bytes(data), counts)


def _doodad_record(
    *, kind: str = "", count: int = 0, skin: bool = False, serial: int = 1
) -> _Record:
    data = bytearray(b"LTlt" + _i32(0) + struct.pack("<7f", 0, 0, 0, 0, 1, 1, 1))
    if skin:
        data += b"\0" * 4
    data += b"\0\0" + _i32(0)
    counts = {"drop_groups": len(data)}
    groups = count if kind == "drop_groups" else (1 if kind == "drop_entries" else 0)
    data += _i32(groups)
    for index in range(groups):
        entries = count if kind == "drop_entries" else 0
        counts[f"drop_entries_{index}"] = len(data)
        data += _i32(entries) + (b"ratf" + _i32(100)) * entries
    data += _i32(serial)
    return _Record(bytes(data), counts)


def _replace_count(record: _Record, field: str, count: int) -> bytes:
    data = bytearray(record.data)
    struct.pack_into("<i", data, record.counts[field], count)
    return bytes(data)


@pytest.mark.parametrize("skin,v7", [(False, True), (False, False), (True, False)])
@pytest.mark.parametrize(
    "kind", ["drop_groups", "drop_entries", "items", "abilities", "random"]
)
@pytest.mark.parametrize("count", [0, 1, 256, 257, 1025])
def test_unit_counts_follow_bytes_not_a_256_cap(
    skin: bool, v7: bool, kind: str, count: int
) -> None:
    first = _unit_record(kind=kind, count=count, skin=skin, v7=v7, serial=11)
    second = _unit_record(skin=skin, v7=v7, serial=22)
    data = _header(2, version=7 if v7 else 8) + first.data + second.data
    units = parse_units(data)
    assert [(unit.type_id, unit.serial) for unit in units] == [
        ("hfoo", 11),
        ("hfoo", 22),
    ]
    assert units[1].source_offset == 16 + len(first.data)
    first_unit = units[0]
    if kind == "drop_groups":
        assert len(first_unit.drop_sets) == count
        assert all(not group.entries for group in first_unit.drop_sets)
    elif kind == "drop_entries":
        assert len(first_unit.drop_sets[0].entries) == count
        assert first_unit.drops == [("ratf", 100)] * count
        assert [entry.entry_index for entry in first_unit.drop_sets[0].entries] == list(
            range(count)
        )
    elif kind == "items":
        assert first_unit.items == [(0, "ratf")] * count
    elif kind == "abilities":
        assert first_unit.abilities == [("AHbz", 1, 2)] * count
    # Random groups are consumed rather than published, so the second record's
    # exact serial and offset above are the completeness check for that branch.


@pytest.mark.parametrize("skin", [False, True])
@pytest.mark.parametrize("kind", ["drop_groups", "drop_entries"])
@pytest.mark.parametrize("count", [0, 1, 256, 257, 1025])
def test_doodad_counts_keep_following_instances(
    skin: bool, kind: str, count: int
) -> None:
    first = _doodad_record(kind=kind, count=count, skin=skin, serial=11)
    second = _doodad_record(skin=skin, serial=22)
    data = _header(2) + first.data + second.data + _i32(0) * 2
    doodads = parse_doodads(data)
    assert [(row.type_id, row.serial) for row in doodads] == [
        ("LTlt", 11),
        ("LTlt", 22),
    ]
    assert doodads[1].source_offset == 16 + len(first.data)
    assert len(doodads[0].drop_sets) == (count if kind == "drop_groups" else 1)
    assert doodads[0].drops == (
        [("ratf", 100)] * count if kind == "drop_entries" else []
    )


@pytest.mark.parametrize("skin,v7", [(False, True), (False, False), (True, False)])
@pytest.mark.parametrize(
    "kind,field",
    [
        ("drop_groups", "drop_groups"),
        ("drop_entries", "drop_entries_0"),
        ("items", "items"),
        ("abilities", "abilities"),
        ("random", "random"),
    ],
)
@pytest.mark.parametrize("bad_count", [-1, -2147483648, 2147483647])
def test_unit_malicious_counts_fail_before_reading_entries(
    skin: bool, v7: bool, kind: str, field: str, bad_count: int
) -> None:
    record = _unit_record(kind=kind, skin=skin, v7=v7)
    reader = _Reader(_replace_count(record, field, bad_count))
    with pytest.raises(DropCountError) as caught:
        _read_unit(reader, skin, v7)
    assert caught.value.count == bad_count
    assert reader.p == record.counts[field] + 4


@pytest.mark.parametrize("skin", [False, True])
@pytest.mark.parametrize(
    "kind,field", [("drop_groups", "drop_groups"), ("drop_entries", "drop_entries_0")]
)
@pytest.mark.parametrize("bad_count", [-1, -2147483648, 2147483647])
def test_doodad_malicious_counts_fail_before_reading_entries(
    skin: bool, kind: str, field: str, bad_count: int
) -> None:
    record = _doodad_record(kind=kind, skin=skin)
    reader = _Reader(_replace_count(record, field, bad_count))
    with pytest.raises(DropCountError) as caught:
        _read_doodad(reader, skin)
    assert caught.value.count == bad_count
    assert reader.p == record.counts[field] + 4


@pytest.mark.parametrize("v7", [False, True])
@pytest.mark.parametrize(
    "kind", ["drop_groups", "drop_entries", "items", "abilities", "random"]
)
def test_unit_count_cannot_borrow_bytes_from_its_required_tail(
    v7: bool, kind: str
) -> None:
    record = _unit_record(kind=kind, v7=v7)
    field = "drop_entries_0" if kind == "drop_entries" else kind
    reader = _Reader(_replace_count(record, field, 1))
    with pytest.raises(DropCountError):
        _read_unit(reader, False, v7)
    assert reader.p == record.counts[field] + 4


def test_nested_drop_count_reserves_later_group_headers() -> None:
    reader = _Reader(_i32(2) + _i32(2) + b"ratf" + _i32(100) + _i32(0) + _i32(99))
    with pytest.raises(DropCountError, match="掉落物品数"):
        read_drop_sets(reader, tail_bytes=4)
    assert reader.p == 8


def test_doodad_drop_count_reserves_serial() -> None:
    record = _doodad_record(kind="drop_groups")
    reader = _Reader(_replace_count(record, "drop_groups", 1))
    with pytest.raises(DropCountError):
        _read_doodad(reader, False)
    assert reader.p == record.counts["drop_groups"] + 4


@pytest.mark.parametrize("skin", [False, True])
def test_unit_layout_requires_exact_eof(skin: bool) -> None:
    record = _unit_record(skin=skin, serial=123)
    data = _header(1) + record.data
    result, full = _attempt_units(data, 1, skin)
    assert full
    assert result[0].serial == 123
    assert not _attempt_units(data + b"\0", 1, skin)[1]
    assert parse_units(data)[0].serial == 123
    if skin:
        assert not _attempt_units(data, 1, False)[1]


@pytest.mark.parametrize("skin", [False, True])
@pytest.mark.parametrize("special_count", [0, 1, 257])
def test_doodad_layout_validates_special_table_tail(
    skin: bool, special_count: int
) -> None:
    record = _doodad_record(skin=skin, serial=123)
    data = (
        _header(1)
        + record.data
        + _i32(0)
        + _i32(special_count)
        + b"\0" * (16 * special_count)
    )
    result, full = _attempt_doodads(data, 1, skin)
    assert full
    assert result[0].serial == 123
    assert parse_doodads(data)[0].serial == 123
    if skin:
        assert not _attempt_doodads(data, 1, False)[1]


@pytest.mark.parametrize(
    "tail",
    [
        b"",
        _i32(0),
        _i32(0) + _i32(-1),
        _i32(0) + _i32(2147483647),
        _i32(0) + _i32(1),
        _i32(0) * 2 + b"\0",
    ],
)
def test_malformed_special_table_is_not_a_complete_doodad_layout(tail: bytes) -> None:
    record = _doodad_record()
    assert not _attempt_doodads(_header(1) + record.data + tail, 1, False)[1]


@pytest.mark.parametrize("skin", [False, True])
def test_bad_later_unit_count_keeps_preceding_instances(skin: bool) -> None:
    good = _unit_record(skin=skin, serial=77)
    bad = _unit_record(kind="abilities", skin=skin)
    data = _header(2) + good.data + _replace_count(bad, "abilities", 2147483647)
    units = parse_units(data)
    assert [(unit.type_id, unit.serial) for unit in units] == [("hfoo", 77)]


@pytest.mark.parametrize("count", [-1, -2147483648, 2147483647])
def test_hostile_top_level_counts_do_not_produce_instances(count: int) -> None:
    assert parse_units(_header(count)) == []
    assert parse_doodads(_header(count)) == []


@pytest.mark.parametrize("skin,v7", [(False, True), (False, False), (True, False)])
@pytest.mark.parametrize("random_flag", [-1, 0, 1, 2])
def test_all_random_layouts_keep_the_following_unit(
    skin: bool, v7: bool, random_flag: int
) -> None:
    first = _unit_record(skin=skin, v7=v7, random_flag=random_flag, serial=11)
    second = _unit_record(skin=skin, v7=v7, serial=22)
    data = _header(2, version=7 if v7 else 8) + first.data + second.data
    assert _attempt_units(data, 2, skin, v7)[1]
    assert [row.serial for row in parse_units(data)] == [11, 22]


def test_unknown_random_flag_is_still_rejected() -> None:
    with pytest.raises(ValueError, match="未知 randomFlag"):
        _read_unit(_Reader(_unit_record(random_flag=3).data), False)


@pytest.mark.parametrize("v7", [False, True])
def test_unit_minimum_record_length_is_exact(v7: bool) -> None:
    record = _unit_record(v7=v7)
    assert len(record.data) == (87 if v7 else 107)
    reader = _Reader(record.data)
    assert _read_unit(reader, False, v7).serial == 1
    assert reader.remaining == 0
    with pytest.raises(ValueError, match="单位记录截断"):
        _read_unit(_Reader(record.data[:-1]), False, v7)


def test_top_level_inflated_count_keeps_a_valid_prefix() -> None:
    unit = _unit_record(serial=77)
    doodad = _doodad_record(serial=77)
    assert [row.serial for row in parse_units(_header(2147483647) + unit.data)] == [77]
    assert [row.serial for row in parse_doodads(_header(2147483647) + doodad.data)] == [
        77
    ]
