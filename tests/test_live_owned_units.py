# -*- coding: utf-8 -*-
"""live --players: 单位所有者/坐标读取与玩家号归并的测试。"""

from __future__ import annotations

import struct

from gametool import live_cli
from gametool.live_handle_chain import (
    UNIT_OWNER_OFF,
    UNIT_POS_X_OFF,
    MemoryReader,
    OwnedUnit,
    read_unit_owner,
    read_unit_pos,
    summarize_owners,
)
from gametool.live_handle_chain import (
    PlayerResources,
    format_player_rows,
    owner_slot_codes,
    parse_nick_overrides,
)


def test_parse_nick_overrides_maps_and_ignores_garbage():
    assert parse_nick_overrides("1=飞信对信,2=大白海岸,3=萌新") == {
        0: "飞信对信",
        1: "大白海岸",
        2: "萌新",
    }
    assert parse_nick_overrides("x, 0=坏 , 13=超界,=空") == {}
    assert parse_nick_overrides(None) == {}
    assert parse_nick_overrides("") == {}


def test_format_player_rows_nick_first_and_multi_hero():
    rows = [
        PlayerResources(0x1, 100.0, 5.0, 5, 5),
        PlayerResources(0x2, 200.0, None, 5, 5),
        PlayerResources(0x3, 300.0, 1.0, 5, 5),
        PlayerResources(0x4, None, None, 0, 0),  # 空槽
    ]
    slot_codes = {
        1: {"O001": 7, "n000": 40},  # 多英雄/召唤: 英雄型优先
        2: {"O002": 1, "H01L": 1},  # 双英雄用 · 连接
    }
    unit_names = {b"O001": "云玎", b"O002": "牛母", b"H01L": "凛冬"}
    lines = format_player_rows(rows, slot_codes, unit_names, 2, {2: "萌新"})
    assert lines == [
        "玩家1(无英雄): 金100 木5 人口5",
        "玩家2(云玎): 金200 木- 人口5",
        "玩家3(萌新): 金300 木1 人口5  <-- 你",
    ]


def test_owner_slot_codes_counts_by_slot():
    units = [
        OwnedUnit(0x10, "O001", 1, 1.0, 2.0),
        OwnedUnit(0x14, "O001", 1, 3.0, 4.0),
        OwnedUnit(0x18, "n000", 5, 0.0, 0.0),
    ]
    assert owner_slot_codes(units) == {1: {"O001": 2}, 5: {"n000": 1}}


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


def test_summarize_owners_lists_every_unit_sorted_by_slot():
    # 满量纪律: 大槽位 (生成物件挂玩家号 0) 不再被上限过滤整槽隐掉,
    # 全部单位按 (槽位, 四码, 坐标) 排序逐个列出。
    units = [OwnedUnit(i, "YTlb", 0, 1.0, 2.0) for i in range(20)]
    hero = OwnedUnit(0x77, "H00O", 0, -16404.0, -4152.0)
    units.append(hero)
    units.append(OwnedUnit(0x98, "h00E", 3, 8.0, 9.0))
    counts, listed = summarize_owners(units)
    assert counts == {0: 21, 3: 1}
    assert len(listed) == len(units)
    assert all(listed[i].owner <= listed[i + 1].owner for i in range(len(listed) - 1))
    assert (0x77, "H00O", 0) in [(u.addr, u.code, u.owner) for u in listed]


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
