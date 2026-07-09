"""对象编辑器数据(w3u/w3t/w3a…)二进制解析测试。

格式：version(i32) + 原始表 + 自定义表；每表 count(i32) 个对象，
每对象 oldId(4)+newId(4)+numMods(i32)+mods；带等级类型(w3a/w3q/w3d)每个 mod 多 level+dataPtr 两个 i32。
"""
import struct
import unittest
from unittest.mock import patch

from w3xtool.w3obj import parse_object_data


def _tag(s):
    return s.encode("latin-1")


def _mod(field_id, var_type, value, level=None):
    b = _tag(field_id) + struct.pack("<i", var_type)
    if level is not None:
        b += struct.pack("<i", level) + struct.pack("<i", 0)   # level + data ptr(忽略)
    if var_type == 0:
        b += struct.pack("<i", value)
    elif var_type in (1, 2):
        b += struct.pack("<f", value)
    elif var_type == 3:
        b += value.encode("utf-8") + b"\x00"
    b += struct.pack("<I", 0)                                  # 末尾校验，忽略
    return b


def _obj(old_id, new_id, mods):
    return _tag(old_id) + _tag(new_id) + struct.pack("<i", len(mods)) + b"".join(mods)


def _obj_v3(old_id, new_id, mods, sets=None):
    # 格式版本 3（重制版）：oldId+newId 后是 sets 数量，每个 set = setsFlag(u32) + 修改数 + 修改项
    # 默认单 set；sets 可传 [(flag,[mods]),...] 表示多 set(HD/SD 皮肤)
    if sets is None:
        sets = [(0, mods)]
    b = _tag(old_id) + _tag(new_id) + struct.pack("<I", len(sets))
    for flag, smods in sets:
        b += struct.pack("<I", flag) + struct.pack("<i", len(smods)) + b"".join(smods)
    return b


def _build(original, custom, version=2):
    out = struct.pack("<i", version)
    out += struct.pack("<i", len(original)) + b"".join(original)
    out += struct.pack("<i", len(custom)) + b"".join(custom)
    return out


class TestParseObjectData(unittest.TestCase):
    def test_original_and_custom_tables(self):
        original = [_obj("hpea", "hpea", [_mod("unam", 3, "Peasant"), _mod("uhpm", 0, 100)])]
        custom = [_obj("hpea", "x000", [_mod("unam", 3, "My Peasant")])]
        objs = parse_object_data(_build(original, custom), "w3u")
        self.assertEqual(len(objs), 2)

        base = objs[0]
        self.assertFalse(base.is_custom)
        self.assertEqual(base.old_id, "hpea")
        self.assertEqual([(m.field_id, m.value) for m in base.mods],
                         [("unam", "Peasant"), ("uhpm", 100)])

        cust = objs[1]
        self.assertTrue(cust.is_custom)
        self.assertEqual(cust.new_id, "x000")
        self.assertEqual(cust.mods[0].value, "My Peasant")

    def test_leveled_ability_format(self):
        # w3a 每个 mod 多 level + dataPtr
        ab = [_obj("AHbz", "A000", [_mod("ahdu", 1, 5.0, level=2)])]
        objs = parse_object_data(_build(ab, []), "w3a")
        self.assertEqual(len(objs), 1)
        m = objs[0].mods[0]
        self.assertEqual(m.field_id, "ahdu")
        self.assertEqual(m.level, 2)
        self.assertAlmostEqual(m.value, 5.0, places=4)

    def test_unknown_var_type_stops_gracefully(self):
        # 未知字段类型(此后游标已错位)→ 该对象中断，保留之前成功的对象，
        # 不再抛异常拖垮整个文件。此处只有这个坏对象 → 返回空。
        bad = [_obj("hpea", "hpea", [_mod("unam", 99, 0)])]
        self.assertEqual(parse_object_data(_build(bad, []), "w3u"), [])

    def test_partial_recovery_keeps_objects_before_corruption(self):
        # 一个好对象 + 一个坏对象(未知类型)。坏对象之前的应保留，而非整文件丢弃。
        good = _obj("hpea", "hpea", [_mod("unam", 3, "Peasant")])
        bad = _obj("hfoo", "hfoo", [_mod("unam", 99, 0)])
        objs = parse_object_data(_build([good, bad], []), "w3u")   # count=2
        self.assertEqual(len(objs), 1)
        self.assertEqual(objs[0].old_id, "hpea")
        self.assertEqual(objs[0].mods[0].value, "Peasant")

    def test_recovers_later_object_after_corrupt_record(self):
        # Given: 一个坏对象夹在表内，后面还有完整对象。
        bad = (
            _tag("hbad") + _tag("xbad") + struct.pack("<i", 1)
            + _tag("unam") + struct.pack("<i", 99) + b"corrupt bytes"
        )
        good = _obj("hfoo", "hfoo", [_mod("unam", 3, "Footman")])

        # When: 解析对象表。
        objs = parse_object_data(_build([bad, good], []), "w3u")

        # Then: 不因为前一条坏记录丢掉后续可识别对象。
        self.assertEqual(len(objs), 1)
        self.assertEqual(objs[0].old_id, "hfoo")
        self.assertEqual(objs[0].mods[0].value, "Footman")

    def test_absurd_count_does_not_hang(self):
        # 注水的超大 count(远超剩余字节)应立即判损坏，而非进入数十亿次循环
        data = struct.pack("<iii", 2, 0x7FFFFFFF, 0)   # version, 原始表 count=21亿, 自定义表空
        self.assertEqual(parse_object_data(data, "w3u"), [])

    def test_gbk_string_value_decoded(self):
        # 老地图(1.20~1.27)的字符串可能是 GBK 编码；UTF-8 解会乱码 → 应回退 GBK
        gbk = "测试".encode("gbk")          # b'\xb2\xe2\xca\xd4'，非法 UTF-8（首字节是续字节）
        self.assertRaises(UnicodeDecodeError, gbk.decode, "utf-8")   # 确认确实非法 UTF-8
        mod = _tag("unam") + struct.pack("<i", 3) + gbk + b"\x00" + struct.pack("<I", 0)
        obj = _tag("hpea") + _tag("hpea") + struct.pack("<i", 1) + mod
        objs = parse_object_data(_build([obj], []), "w3u")
        self.assertEqual(objs[0].mods[0].value, "测试")

    def test_windows_acp_string_value_precedes_gbk(self):
        # Given: a legacy object string saved under Traditional Chinese ACP.
        raw = "測試".encode("cp950")
        mod = _tag("unam") + struct.pack("<i", 3) + raw + b"\x00" + struct.pack("<I", 0)
        obj = _tag("hpea") + _tag("hpea") + struct.pack("<i", 1) + mod

        # When: the active Windows ACP is cp950.
        with patch("w3xtool.war3_encoding.default_legacy_codecs", return_value=("cp950", "gbk")):
            objs = parse_object_data(_build([obj], []), "w3u")

        # Then: the string is not mis-decoded as GBK.
        self.assertEqual(objs[0].mods[0].value, "測試")

    def test_version3_extra_header_fields(self):
        # 1.32+/新编辑器存的格式版本 3：每个对象头多两个 uint32
        original = [_obj_v3("hpea", "hpea", [_mod("unam", 3, "Peasant"), _mod("uhpm", 0, 100)])]
        custom = [_obj_v3("hpea", "x000", [_mod("unam", 3, "村民")])]
        data = _build(original, custom, version=3)
        objs = parse_object_data(data, "w3u")
        self.assertEqual(len(objs), 2)
        self.assertEqual([(m.field_id, m.value) for m in objs[0].mods],
                         [("unam", "Peasant"), ("uhpm", 100)])
        self.assertEqual(objs[1].new_id, "x000")
        self.assertEqual(objs[1].mods[0].value, "村民")

    def test_version3_leveled_ability(self):
        ab = [_obj_v3("AHbz", "A000", [_mod("ahdu", 1, 5.0, level=2)])]
        objs = parse_object_data(_build(ab, [], version=3), "w3a")
        self.assertEqual(objs[0].mods[0].level, 2)
        self.assertAlmostEqual(objs[0].mods[0].value, 5.0, places=4)

    def test_version3_multiple_sets(self):
        # 重制版 HD/SD 皮肤：一个对象可有多个修改 set，全部 mods 都要收进来
        s0 = [_mod("unam", 3, "标准")]
        s1 = [_mod("umdl", 3, "HD模型"), _mod("uhpm", 0, 200)]
        obj = _obj_v3("hpea", "x001", [], sets=[(0, s0), (1, s1)])
        objs = parse_object_data(_build([obj], [], version=3), "w3u")
        self.assertEqual(len(objs), 1)
        fields = [(m.field_id, m.value) for m in objs[0].mods]
        self.assertIn(("unam", "标准"), fields)
        self.assertIn(("umdl", "HD模型"), fields)
        self.assertIn(("uhpm", 200), fields)


class _FakeArchive:
    def __init__(self, fn, data):
        self._fn, self._data = fn, data

    def has_file(self, n):
        return n == self._fn

    def read_file(self, n):
        return self._data


class TestBuildObjectsRobust(unittest.TestCase):
    def test_malformed_object_file_returns_empty_not_crash(self):
        from w3xtool.api import _build_objects
        # 截断/畸形的 w3u：声明 1 个对象但数据不够 → 解析中途出错
        bad = struct.pack("<ii", 2, 1) + b"shor"   # version, count=1, 残缺
        arch = _FakeArchive("war3map.w3u", bad)
        self.assertEqual(_build_objects(arch, "w3u", {}), [])   # 优雅返回空，不抛

    def test_missing_file_returns_empty(self):
        from w3xtool.api import _build_objects
        arch = _FakeArchive("war3map.w3t", b"")
        self.assertEqual(_build_objects(arch, "w3u", {}), [])


if __name__ == "__main__":
    unittest.main()
