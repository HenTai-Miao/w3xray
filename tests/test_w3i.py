"""war3map.w3i 地图信息解析测试（移植自 w3x2lni frontend_w3i.lua）。

合成 v25(TFT) 验证逐字段，真实夹具 v25/v18 验证端到端不崩、字段合理。
"""
import os
import struct
import unittest

from w3xtool.w3i import parse_w3i

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _z(s):
    return s.encode("utf-8") + b"\x00"


def _build_v25(map_name="测试地图", author="作者A", players=None, forces=None,
               flags=0, script_after=b""):
    players = players if players is not None else []
    forces = forces if forces is not None else []
    b = struct.pack("<i", 25)
    b += struct.pack("<ii", 1, 6060)            # map_version, we_version
    b += _z(map_name) + _z(author) + _z("描述") + _z("推荐:2")
    b += struct.pack("<8f", *([0.0] * 8))       # 镜头边界
    b += struct.pack("<4i", *([0] * 4))         # 镜头补足
    b += struct.pack("<ii", 64, 64)             # 宽, 高
    b += struct.pack("<I", flags)               # flags
    b += b"L"                                    # c1 主地表
    # version>=25:
    b += struct.pack("<i", 0) + _z("") + _z("") + _z("") + _z("")  # 载入屏 id+4z
    b += struct.pack("<i", 0)                    # game_data_set
    b += _z("") + _z("") + _z("") + _z("")       # 序章 4z
    b += struct.pack("<i", 0) + struct.pack("<3f", 0, 0, 0) + b"\x00\x00\x00\x00"  # 雾
    b += b"none" + _z("") + b"L" + b"\x00\x00\x00\x00"  # 环境: weather c4 + sound z + light c1 + water 4B
    b += script_after                            # v28+ 才有脚本类型，这里默认空
    # 玩家段
    b += struct.pack("<i", len(players))
    for p in players:
        pid, ptype, race, name = p
        b += struct.pack("<iiii", pid, ptype, race, 0)   # id type race fixstart
        b += _z(name)
        b += struct.pack("<2f", 0.0, 0.0)                # start
        b += struct.pack("<II", 0, 0)                    # ally low/high
    # 队伍段
    b += struct.pack("<i", len(forces))
    for f in forces:
        fflag, mask, fname = f
        b += struct.pack("<II", fflag, mask) + _z(fname)
    b += b"\xff"                                  # upgrade/tech/random 段空哨兵
    return b


class TestParseW3i(unittest.TestCase):
    def test_basic_header(self):
        info = parse_w3i(_build_v25(map_name="我的地图", author="张三", flags=0x4))
        self.assertEqual(info.version, 25)
        self.assertEqual(info.map_name, "我的地图")
        self.assertEqual(info.author, "张三")
        self.assertEqual(info.width, 64)
        self.assertTrue(info.melee)              # flag bit2 = 对战图

    def test_players_and_forces(self):
        info = parse_w3i(_build_v25(
            players=[(0, 1, 1, "玩家1"), (1, 2, 2, "电脑2")],
            forces=[(0, 0xFFFFFFFF, "队伍甲")]))
        self.assertEqual(len(info.players), 2)
        self.assertEqual(info.players[0].name, "玩家1")
        self.assertEqual(info.players[0].type, 1)
        self.assertEqual(info.players[1].race, 2)
        self.assertEqual(len(info.forces), 1)
        self.assertEqual(info.forces[0].name, "队伍甲")

    def test_trigstr_resolved_via_wts(self):
        info = parse_w3i(_build_v25(map_name="TRIGSTR_010"),
                         wts={10: "还原后的地图名"})
        self.assertEqual(info.map_name, "还原后的地图名")

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_w3i(b""))
        self.assertIsNone(parse_w3i(b"\x01\x02"))

    def test_real_v25_fixture(self):
        data = open(os.path.join(FIX, "w3i_v25.w3i"), "rb").read()
        info = parse_w3i(data)
        self.assertEqual(info.version, 25)
        self.assertTrue(isinstance(info.map_name, str))
        self.assertGreaterEqual(len(info.players), 1)

    def test_real_v18_fixture(self):
        data = open(os.path.join(FIX, "w3i_v18.w3i"), "rb").read()
        info = parse_w3i(data)
        self.assertEqual(info.version, 18)
        self.assertGreaterEqual(len(info.players), 1)


def _build_w3f(name="战役名", difficulty="普通", author="作者C", desc="战役描述"):
    b = struct.pack("<i", 1)                     # version
    b += struct.pack("<ii", 1, 6060)             # campaign_version, editor_version
    b += _z(name) + _z(difficulty) + _z(author) + _z(desc)
    return b


class TestParseW3f(unittest.TestCase):
    def test_basic(self):
        from w3xtool.w3i import parse_w3f
        info = parse_w3f(_build_w3f(name="远古战役", author="老李"))
        self.assertEqual(info.name, "远古战役")
        self.assertEqual(info.author, "老李")
        self.assertEqual(info.difficulty, "普通")

    def test_trigstr_resolved(self):
        from w3xtool.w3i import parse_w3f
        info = parse_w3f(_build_w3f(name="TRIGSTR_003"), wts={3: "真战役名"})
        self.assertEqual(info.name, "真战役名")

    def test_garbage_returns_none(self):
        from w3xtool.w3i import parse_w3f
        self.assertIsNone(parse_w3f(b""))


class _FakeArchive:
    def __init__(self, files):
        self._files = files

    def has_file(self, n):
        return n in self._files

    def read_file(self, n):
        return self._files[n]

    @property
    def _data(self):
        return b""

    path = "x.w3x"


class TestW3iIntegration(unittest.TestCase):
    def test_add_w3i_sets_mapdata_and_name(self):
        from w3xtool.api import _add_w3i, MapData
        w3i = _build_v25(map_name="真实地图名", author="作者X")
        md = MapData(path="x", name="占位名")
        _add_w3i(md, _FakeArchive({"war3map.w3i": w3i}), {})
        self.assertIsNotNone(md.w3i)
        self.assertEqual(md.w3i.author, "作者X")
        self.assertEqual(md.name, "真实地图名")     # 地图名优先取 w3i

    def test_add_w3i_keeps_name_if_w3i_absent(self):
        from w3xtool.api import _add_w3i, MapData
        md = MapData(path="x", name="占位名")
        _add_w3i(md, _FakeArchive({}), {})
        self.assertIsNone(md.w3i)
        self.assertEqual(md.name, "占位名")


if __name__ == "__main__":
    unittest.main()
