# -*- coding: utf-8 -*-
"""live --players: 单位所有者/坐标读取与玩家号归并的测试。"""

from __future__ import annotations

import struct

from w3xtool import live_cli
from w3xtool.live_handle_chain import (
    UNIT_OWNER_OFF,
    UNIT_POS_X_OFF,
    MemoryReader,
    OwnedUnit,
    read_unit_owner,
    read_unit_pos,
    summarize_owners,
)


def _reader_with_unit(owner: int, x: float, y: float) -> MemoryReader:
    blob = bytearray(0x300)
    blob[UNIT_OWNER_OFF] = owner
    struct.pack_into("<ff", blob, UNIT_POS_X_OFF, x, y)
    return MemoryReader([(0x10000000, bytes(blob))])


def test_read_unit_owner_and_pos():
    reader = _reader_with_unit(4, -123.5, 9876.0)
    assert read_unit_owner(reader, 0x10000000) == 4
    assert read_unit_pos(reader, 0x10000000) == (-123.5, 9876.0)


def test_read_unit_pos_rejects_garbage():
    blob = bytearray(0x300)
    struct.pack_into("<ff", blob, UNIT_POS_X_OFF, 1e12, -1e12)
    reader = MemoryReader([(0x10000000, bytes(blob))])
    assert read_unit_pos(reader, 0x10000000) == (0.0, 0.0)


def test_read_unit_owner_missing_region():
    reader = MemoryReader([(0x10000000, b"\x00" * 8)])
    assert read_unit_owner(reader, 0x10000000) == -1


def test_summarize_owners_lists_small_owners_only():
    units = []
    for _ in range(20):
        units.append(OwnedUnit(1, "YTlb", 8, 1.0, 2.0))
    units.append(OwnedUnit(2, "h00D", 3, 100.0, 200.0))
    units.append(OwnedUnit(3, "h01W", 5, -50.0, 700.0))
    counts, listed = summarize_owners(units)
    assert counts == {8: 20, 3: 1, 5: 1}
    assert [(u.owner, u.code) for u in listed] == [(3, "h00D"), (5, "h01W")]


def test_summarize_owners_respects_cap():
    units = [OwnedUnit(i, "h01U", 2, float(i), 0.0) for i in range(9)]
    counts, listed = summarize_owners(units, list_cap=8)
    assert counts == {2: 9}
    assert listed == []


def test_live_cli_parses_players_flag():
    opts = live_cli.parse_live_cli_options(["地图.w3x", "--players"])
    assert opts.players is True
    opts = live_cli.parse_live_cli_options(["地图.w3x"])
    assert opts.players is False


def test_live_cli_rejects_duplicate_players_flag():
    try:
        live_cli.parse_live_cli_options(["地图.w3x", "--players", "--players"])
    except live_cli.LiveCliOptionError as exc:
        assert "重复" in str(exc)
    else:
        raise AssertionError("重复 --players 应报错")
