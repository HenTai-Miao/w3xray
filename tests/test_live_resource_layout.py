# -*- coding: utf-8 -*-
"""live 玩家资源定位 (--resources) 的合成内存测试。"""

from __future__ import annotations

import struct

from w3xtool.live_handle_chain import (
    MemoryReader,
    PlayerResources,
    find_resource_layout,
)


def _region_with_players(entries):
    """构造 stride=0x300 的玩家资源数组: 金@+0x40 木@+0x58 人口@+0x5C。"""
    blob = bytearray()
    for gold, lumber, food in entries:
        slot = bytearray(0x300)
        struct.pack_into("<f", slot, 0x40, gold)
        struct.pack_into("<f", slot, 0x58, lumber)
        if food is not None:
            struct.pack_into("<f", slot, 0x5C, food)
        blob += slot
    return bytes(blob)


def test_find_resource_layout_locates_all_players():
    entries = [(169.0, 808.0, 5.0), (300.0, 120.0, 7.0), (40.0, 999.0, None)]
    data = _region_with_players(entries)
    reader = MemoryReader([(0x20000000, data)])
    found = find_resource_layout(reader, 169.0, 808.0)
    assert len(found) == 1
    res = found[0]
    assert isinstance(res, PlayerResources)
    assert res.gold == 169.0
    assert res.lumber == 808.0
    assert res.addr == 0x20000000 + 0x40
    assert res.food == 5


def test_find_resource_layout_requires_co_located_pair():
    # 两个值相距超过窗口: 找不到布局。
    blob = bytearray(0x400)
    struct.pack_into("<f", blob, 0x10, 169.0)
    struct.pack_into("<f", blob, 0x300, 808.0)
    reader = MemoryReader([(0x20000000, bytes(blob))])
    assert find_resource_layout(reader, 169.0, 808.0) == []


def test_find_resource_layout_no_match_returns_empty():
    blob = bytearray(0x100)
    struct.pack_into("<f", blob, 0x10, 42.0)
    reader = MemoryReader([(0x20000000, bytes(blob))])
    assert find_resource_layout(reader, 169.0, 808.0) == []


def test_find_resource_layout_picks_most_common_delta():
    # 主布局: 木在金+0x18; 另有一处巧合对 木在金+0x8。
    blob = bytearray(0x400)
    struct.pack_into("<f", blob, 0x40, 169.0)
    struct.pack_into("<f", blob, 0x58, 808.0)
    struct.pack_into("<f", blob, 0x140, 169.0)
    struct.pack_into("<f", blob, 0x158, 808.0)
    struct.pack_into("<f", blob, 0x240, 169.0)
    struct.pack_into("<f", blob, 0x248, 808.0)
    reader = MemoryReader([(0x20000000, bytes(blob))])
    found = find_resource_layout(reader, 169.0, 808.0)
    assert [f.addr for f in found] == [0x20000000 + 0x40, 0x20000000 + 0x140]
