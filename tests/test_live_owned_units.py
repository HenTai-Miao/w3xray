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
    salvage_big_owner_units,
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


def test_salvage_big_owner_units_rescues_heroes_from_huge_slots():
    # 大槽位 (生成物件挂玩家号 0) -> summarize_owners 清空;
    # 该槽位里的带物品英雄应被打捞, 小槽位条目不重复补录。
    units = [OwnedUnit(i, "YTlb", 0, 1.0, 2.0) for i in range(20)]
    hero = OwnedUnit(0x77, "H00O", 0, -16404.0, -4152.0)
    units.append(hero)
    mate = OwnedUnit(0x98, "h00E", 3, 8.0, 9.0)  # 小槽位 (玩家号3) 本来就在 listed
    units.append(mate)
    counts, listed = summarize_owners(units)
    assert [(u.owner, u.code) for u in listed] == [(3, "h00E")]
    item_entries = [
        hero,
        OwnedUnit(0x99, "H01L", 3, 10.0, 20.0),  # 小槽位 (玩家号3) 不打捞
    ]
    rescued = salvage_big_owner_units(counts, listed, item_entries)
    assert [(u.addr, u.code, u.owner) for u in rescued] == [(0x77, "H00O", 0)]


def test_salvage_big_owner_units_dedups_by_addr():
    units = [OwnedUnit(0x77, "H00O", 0, -16404.0, -4152.0)]
    units += [OwnedUnit(i, "YTlb", 0, 1.0, 2.0) for i in range(1, 21)]
    counts, listed = summarize_owners(units)
    assert listed == []  # 玩家号 0 是大槽位, 唯一英雄也被过滤
    rescued = salvage_big_owner_units(counts, listed, [units[0]])
    assert [u.addr for u in rescued] == [0x77]
    # 同一单位出现在 listed 里 (小槽位场景) 时不重复
    small_units = [OwnedUnit(0x77, "H00O", 3, 5.0, 6.0)]
    counts2, listed2 = summarize_owners(small_units)
    assert salvage_big_owner_units(counts2, listed2, small_units) == []


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
