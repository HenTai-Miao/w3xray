"""预放置实例解析测试：war3map.doo（装饰物/可破坏物）与 war3mapUnits.doo（单位）。

格式参考 w3x2lni frontend_doo.lua（装饰物），单位 doo 经 61/62 张真实地图逐字节验证。
单位记录是变长的（物品/技能/掉落数决定长度），损坏/老格式时优雅降级、保留已读对象。
"""
import math
import os
import struct
import unittest

from w3xtool.doo import parse_doodads, parse_units

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _f(v):
    return struct.pack("<f", v)


def _i(v):
    return struct.pack("<i", v)


def _doodad(tid, var, pos, angle_rad, scale, vis, life, drops, serial, skin=None):
    b = tid.encode("latin-1") + _i(var)
    b += _f(pos[0]) + _f(pos[1]) + _f(pos[2]) + _f(angle_rad)
    b += _f(scale[0]) + _f(scale[1]) + _f(scale[2])
    if skin is not None:                 # 重制版：scale 后多 4 字节皮肤码
        b += skin.encode("latin-1")
    b += bytes([vis]) + bytes([life])
    b += _i(-1)                          # 掉落列表指针
    b += _i(len(drops))
    for did, chance in drops:
        b += did.encode("latin-1") + _i(chance)
    b += _i(serial)
    return b


def _build_doo(doodads, version=8):
    b = b"W3do" + _i(version) + _i(11)
    b += _i(len(doodads)) + b"".join(doodads)
    b += _i(0)                           # special head version
    b += _i(0)                           # special count
    return b


def _unit(tid, var, pos, rot, scale, flags, player, hp, mana,
          gold, ta, hlev, items, abils, serial, dropsets=None,
          rng=(0, (0,)), color=-1, waygate=-1):
    b = tid.encode("latin-1") + _i(var)
    b += _f(pos[0]) + _f(pos[1]) + _f(pos[2]) + _f(rot)
    b += _f(scale[0]) + _f(scale[1]) + _f(scale[2])
    b += bytes([flags]) + _i(player) + b"\x00\x00"
    b += _i(hp) + _i(mana)
    b += _i(-1)                          # dropped-item-set 指针
    dropsets = dropsets or []
    b += _i(len(dropsets))
    for s in dropsets:
        b += _i(len(s))
        for did, chance in s:
            b += did.encode("latin-1") + _i(chance)
    b += _i(gold) + _f(ta) + _i(hlev)
    b += _i(0) + _i(0) + _i(0)           # hero str/agi/int
    b += _i(len(items))
    for slot, iid in items:
        b += _i(slot) + iid.encode("latin-1")
    b += _i(len(abils))
    for aid, active, level in abils:
        b += aid.encode("latin-1") + _i(active) + _i(level)
    rflag, rdata = rng
    b += _i(rflag)
    if rflag == 0:
        b += _i(rdata[0])
    elif rflag == 1:
        b += _i(rdata[0]) + _i(rdata[1])
    elif rflag == 2:
        b += _i(len(rdata))
        for rid, rchance in rdata:
            b += rid.encode("latin-1") + _i(rchance)
    b += _i(color) + _i(waygate) + _i(serial)
    return b


def _build_units(units, version=8, sub=11):
    return b"W3do" + _i(version) + _i(sub) + _i(len(units)) + b"".join(units)


class TestParseDoodads(unittest.TestCase):
    def test_single_doodad(self):
        d = _doodad("LTlt", 1, (832.0, -2368.0, 0.0), math.pi,
                    (0.9, 0.9, 0.9), 2, 100, [], 5)
        objs = parse_doodads(_build_doo([d]))
        self.assertEqual(len(objs), 1)
        o = objs[0]
        self.assertEqual(o.type_id, "LTlt")
        self.assertEqual(o.variation, 1)
        self.assertAlmostEqual(o.x, 832.0, places=2)
        self.assertAlmostEqual(o.y, -2368.0, places=2)
        self.assertAlmostEqual(o.angle, 180.0, places=2)   # 弧度→度
        self.assertEqual(o.life, 100)
        self.assertEqual(o.serial, 5)

    def test_doodad_with_drops(self):
        d = _doodad("YOl0", 0, (0.0, 0.0, 0.0), 0.0, (1, 1, 1),
                    2, 100, [("ratf", 100), ("rde1", 50)], 7)
        objs = parse_doodads(_build_doo([d]))
        self.assertEqual(objs[0].drops, [("ratf", 100), ("rde1", 50)])

    def test_multiple_doodads(self):
        ds = [_doodad("LTlt", i, (float(i), 0.0, 0.0), 0.0, (1, 1, 1),
                      2, 100, [], i) for i in range(3)]
        objs = parse_doodads(_build_doo(ds))
        self.assertEqual(len(objs), 3)
        self.assertEqual([o.serial for o in objs], [0, 1, 2])

    def test_bad_magic_returns_empty(self):
        self.assertEqual(parse_doodads(b"XXXX" + _i(8) + _i(11) + _i(0)), [])
        self.assertEqual(parse_doodads(b""), [])

    def test_truncated_keeps_objects_before_corruption(self):
        good = _doodad("LTlt", 0, (1.0, 2.0, 0.0), 0.0, (1, 1, 1), 2, 100, [], 1)
        data = b"W3do" + _i(8) + _i(11) + _i(3) + good + b"\x00\x03tr"  # 声明3个，第2个截断
        objs = parse_doodads(data)
        self.assertEqual(len(objs), 1)
        self.assertEqual(objs[0].serial, 1)

    def test_reforged_skin_field_auto_detected(self):
        # 重制版每条 scale 后多 4 字节皮肤码（版本仍 8/11）→ 自动识别带 skin 的布局
        ds = [_doodad("LTlt", i, (float(i), 0.0, 0.0), 0.0, (1, 1, 1),
                      2, 100, [], i, skin="LTlt") for i in range(4)]
        data = b"W3do" + _i(8) + _i(11) + _i(len(ds)) + b"".join(ds) + _i(0) + _i(0)
        objs = parse_doodads(data)
        self.assertEqual(len(objs), 4)
        self.assertEqual([o.serial for o in objs], [0, 1, 2, 3])
        self.assertEqual(objs[0].type_id, "LTlt")

    def test_reforged_skin_with_drops(self):
        d = _doodad("YOl0", 0, (0.0, 0.0, 0.0), 0.0, (1, 1, 1),
                    2, 100, [("ratf", 100)], 7, skin=" B00")
        data = b"W3do" + _i(8) + _i(11) + _i(1) + d + _i(0) + _i(0)
        objs = parse_doodads(data)
        self.assertEqual(len(objs), 1)
        self.assertEqual(objs[0].drops, [("ratf", 100)])


class TestParseUnits(unittest.TestCase):
    def test_single_unit(self):
        u = _unit("hpea", 0, (100.0, 200.0, 0.0), 0.0, (1, 1, 1),
                  2, 0, -1, -1, 0, -1.0, 1, [], [], 1)
        units = parse_units(_build_units([u]))
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].type_id, "hpea")
        self.assertEqual(units[0].player, 0)
        self.assertAlmostEqual(units[0].x, 100.0, places=2)
        self.assertEqual(units[0].serial, 1)

    def test_unit_with_items_and_abilities(self):
        u = _unit("Hpal", 0, (0.0, 0.0, 0.0), 0.0, (1, 1, 1), 2, 1, 500, 200,
                  0, -1.0, 3, [(0, "ratf"), (1, "rde1")],
                  [("AHbz", 1, 2)], 9)
        units = parse_units(_build_units([u]))
        self.assertEqual(units[0].items, [(0, "ratf"), (1, "rde1")])
        self.assertEqual(units[0].abilities, [("AHbz", 1, 2)])
        self.assertEqual(units[0].hero_level, 3)

    def test_multiple_units_stay_in_sync(self):
        us = [_unit("hpea", 0, (float(i), 0.0, 0.0), 0.0, (1, 1, 1),
                    2, i % 2, -1, -1, 0, -1.0, 1, [], [], i) for i in range(4)]
        units = parse_units(_build_units(us))
        self.assertEqual(len(units), 4)
        self.assertEqual([u.serial for u in units], [0, 1, 2, 3])

    def test_random_flag_variants(self):
        u0 = _unit("uDNR", 0, (0.0, 0.0, 0.0), 0.0, (1, 1, 1), 2, 0, -1, -1,
                   0, -1.0, 1, [], [], 1, rng=(0, (0,)))
        u2 = _unit("uDNR", 0, (0.0, 0.0, 0.0), 0.0, (1, 1, 1), 2, 0, -1, -1,
                   0, -1.0, 1, [], [], 2, rng=(2, [("hfoo", 50), ("hkni", 50)]))
        units = parse_units(_build_units([u0, u2]))
        self.assertEqual(len(units), 2)

    def test_bad_magic_returns_empty(self):
        self.assertEqual(parse_units(b"NOPE" + _i(8) + _i(11) + _i(0)), [])

    def test_real_map_fixture(self):
        # 真实地图的 war3mapUnits.doo（1 个出生点单位 'sloc'）
        data = open(os.path.join(FIX, "matrix.units.doo"), "rb").read()
        units = parse_units(data)
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].type_id, "sloc")


class _PreplacedArchive:
    def __init__(self, files):
        self._files = files

    def has_file(self, n):
        return n in self._files

    def read_file(self, n):
        return self._files[n]


class TestPreplacedIntegration(unittest.TestCase):
    def test_add_preplaced_fills_mapdata(self):
        from w3xtool.api import _add_preplaced, MapData
        doo = _build_doo([_doodad("LTlt", 0, (1.0, 2.0, 0.0), 0.0,
                                  (1, 1, 1), 2, 100, [], 1)])
        udoo = _build_units([_unit("hpea", 0, (0.0, 0.0, 0.0), 0.0,
                                   (1, 1, 1), 2, 0, -1, -1, 0, -1.0, 1,
                                   [], [], 1)])
        md = MapData(path="x", name="x")
        _add_preplaced(md, _PreplacedArchive(
            {"war3map.doo": doo, "war3mapUnits.doo": udoo}))
        self.assertEqual(len(md.doodads), 1)
        self.assertEqual(len(md.units), 1)
        self.assertEqual(md.units[0].type_id, "hpea")

    def test_add_preplaced_no_files_is_noop(self):
        from w3xtool.api import _add_preplaced, MapData
        md = MapData(path="x", name="x")
        _add_preplaced(md, _PreplacedArchive({}))
        self.assertEqual(md.doodads, [])
        self.assertEqual(md.units, [])


if __name__ == "__main__":
    unittest.main()
