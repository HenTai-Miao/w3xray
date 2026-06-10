"""对象编辑器数据(w3u/w3t/w3a…)二进制解析测试。

格式：version(i32) + 原始表 + 自定义表；每表 count(i32) 个对象，
每对象 oldId(4)+newId(4)+numMods(i32)+mods；带等级类型(w3a/w3q/w3d)每个 mod 多 level+dataPtr 两个 i32。
"""
import struct
import unittest

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


def _obj_v3(old_id, new_id, mods):
    # 格式版本 3：oldId+newId 之后多两个 uint32 头字段，再是 numMods
    return (_tag(old_id) + _tag(new_id) + struct.pack("<II", 0, 0)
            + struct.pack("<i", len(mods)) + b"".join(mods))


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

    def test_unknown_var_type_raises(self):
        bad = [_obj("hpea", "hpea", [_mod("unam", 99, 0)])]
        with self.assertRaises(ValueError):
            parse_object_data(_build(bad, []), "w3u")

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
