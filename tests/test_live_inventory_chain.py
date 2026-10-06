# -*- coding: utf-8 -*-
"""hero_chain 结构启发式链的合成内存回归测试。"""

import struct

import pytest

np = pytest.importorskip("numpy")

from w3xtool.hero_chain import read_inventory  # noqa: E402

BASE = 0x08000000
SIZE = 0x41000


def _p32(buf, off, v):
    struct.pack_into("<I", buf, off, v)


@pytest.fixture()
def fake_world():
    buf = bytearray(SIZE)
    names = {}
    unit_names = {}

    def put(off, b):
        buf[off : off + len(b)] = b

    # 10 个物品 def: 布局 名字指针@+0x30, 四码@+0x38 (d=8, off_np=0x30)
    def_bases = []
    for i in range(10):
        d0 = 0x1000 + i * 0x80
        def_bases.append(BASE + d0)
        name_off = 0x10000 + i * 0x40
        code = f"I0A{i}".encode()
        put(d0 + 0x38, code)
        put(name_off, f"测试护符第{i}号".encode("gbk"))
        _p32(buf, d0 + 0x30, BASE + name_off)
        names[code] = f"测试护符第{i}号"
    # 16 字节步长哈希表 (应被过滤)
    for i in range(20):
        _p32(buf, 0x20000 + i * 16, def_bases[i % 10])
    # 6 个 CItem: def 指针 @+0x10
    citem = []
    for i in range(6):
        c0 = 0x30000 + i * 0x40
        citem.append(BASE + c0)
        _p32(buf, c0 + 0x10, def_bases[i])
    # 英雄 def + 英雄对象 (槽位数组 6 连)
    put(0x5000 + 0x38, b"O002")
    put(0x18000, "易大师传奇".encode("gbk"))
    _p32(buf, 0x5000 + 0x30, BASE + 0x18000)
    unit_names[b"O002"] = "易大师传奇"
    _p32(buf, 0x40000, BASE + 0x5000)
    for i, c in enumerate(citem):
        _p32(buf, 0x40100 + i * 4, c)
    return [(BASE, bytes(buf))], names, unit_names


def test_read_inventory_synthetic(fake_world):
    regions, names, unit_names = fake_world
    res = read_inventory(regions, names, unit_names=unit_names)
    assert res, "链路应产出结果"
    best = res[0]
    assert len(best["items"]) == 6
    got = [it["fourcc"] for it in best["items"]]
    assert got == [f"I0A{i}" for i in range(6)]
    assert best["verified"] is True


def test_read_inventory_no_anchors(fake_world):
    regions, _names, _u = fake_world
    # 换成无关名字 -> 学不出布局, 返回空而不是崩
    res = read_inventory(regions, {b"I0ZZ": "完全不存在的物品名字"})
    assert res == []
