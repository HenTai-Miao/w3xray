"""war3map.wtg trigger tree summary parsing."""

import struct
import unittest

from w3xtool.api import MapData
from w3xtool.wtg import parse_wtg


def _i(value):
    return struct.pack("<i", value)


def _u(value):
    return struct.pack("<I", value)


def _z(text):
    return text.encode("utf-8") + b"\x00"


def _classic_trigger(name, enabled=1, custom=0, off=0, init=0, eca_count=0):
    return (
        _z(name) + _z("说明") + _i(0) + _i(enabled) + _i(custom)
        + _i(off) + _i(init) + _i(42) + _i(eca_count)
    )


def _classic_wtg():
    return (
        b"WTG!" + _i(7)
        + _i(1) + _i(42) + _z("系统") + _i(0)
        + _i(0)
        + _i(2)
        + _z("Count") + _z("integer") + _i(1) + _i(0) + _i(1) + _i(1) + _z("5")
        + _z("Players") + _z("player") + _i(1) + _i(1) + _i(12) + _i(0) + _z("")
        + _i(2)
        + _classic_trigger("初始化", enabled=1, init=1)
        + _classic_trigger("禁用脚本", enabled=0, custom=1, off=1, eca_count=1)
    )


def _type_info(total):
    return _i(total) + _i(0)


def _reforged_trigger_object(name, object_type, object_id, enabled=1, custom=0):
    return (
        _i(object_type) + _z(name) + _z("")
        + _i(1 if object_type == 16 else 0)
        + _i(object_id) + _i(enabled) + _i(custom)
        + _i(0) + _i(0) + _i(0x02000000) + _i(0)
    )


def _reforged_wtg():
    return (
        b"WTG!" + _u(0x80000004) + _i(7)
        + _type_info(1) + _type_info(0) + _type_info(1)
        + _type_info(1) + _type_info(1) + _type_info(1) + _type_info(1)
        + _i(0) + _i(0) + _i(1)
        + _i(1)
        + _z("loc1") + _z("location") + _i(1) + _i(0) + _i(1)
        + _i(0) + _z("") + _i(0x06000001) + _i(0x02000000)
        + _i(6)
        + _i(1) + _i(0) + _z("Map") + _i(0) + _i(0) + _i(-1)
        + _i(4) + _i(0x02000000) + _z("Folder") + _i(1) + _i(1) + _i(0)
        + _reforged_trigger_object("Init", 8, 0x03000001)
        + _reforged_trigger_object("Note", 16, 0x04000001)
        + _reforged_trigger_object("ScriptA", 32, 0x05000001, enabled=0, custom=1)
        + _i(64) + _i(0x06000001) + _z("loc1") + _i(0x02000000)
    )


class WtgParseTest(unittest.TestCase):
    def test_parse_classic_wtg_summary(self):
        # Given: a classic TFT trigger file with categories, variables and trigger headers.
        data = _classic_wtg()

        # When: the WTG file is parsed.
        summary = parse_wtg(data)

        # Then: editor-facing trigger metadata is available without ECA expansion.
        self.assertFalse(summary.is_reforged)
        self.assertEqual(summary.version, 7)
        self.assertEqual(summary.category_count, 1)
        self.assertEqual(summary.variable_count, 2)
        self.assertEqual(summary.trigger_count, 2)
        self.assertEqual(summary.categories[0].name, "系统")
        self.assertEqual(summary.variables[1].array_size, 12)
        self.assertEqual(summary.triggers[0].name, "初始化")
        self.assertTrue(summary.triggers[0].run_on_init)
        self.assertFalse(summary.triggers[1].is_enabled)
        self.assertTrue(summary.triggers[1].is_custom_text)
        self.assertTrue(summary.has_unexpanded_functions)

    def test_parse_reforged_wtg_tree_summary(self):
        # Given: a Reforged 1.36 trigger file skeleton.
        data = _reforged_wtg()

        # When: the WTG file is parsed.
        summary = parse_wtg(data)

        # Then: TypeInfo counts and tree object headers are summarized.
        self.assertTrue(summary.is_reforged)
        self.assertEqual(summary.version, 7)
        self.assertEqual(summary.category_count, 1)
        self.assertEqual(summary.variable_count, 1)
        self.assertEqual(summary.trigger_count, 1)
        self.assertEqual(summary.comment_count, 1)
        self.assertEqual(summary.script_count, 1)
        self.assertEqual([category.name for category in summary.categories], ["Map", "Folder"])
        self.assertEqual(summary.variables[0].name, "loc1")
        self.assertEqual([trigger.name for trigger in summary.triggers], ["Init", "Note", "ScriptA"])

    def test_add_trigger_summary_fills_mapdata(self):
        # Given: an archive exposing war3map.wtg.
        from w3xtool.map_extras import add_trigger_summary

        md = MapData(path="x", name="x")
        archive = _FakeArchive({"war3map.wtg": _classic_wtg()})

        # When: trigger summary loading runs.
        add_trigger_summary(md, archive)

        # Then: parsed trigger metadata is attached to MapData.
        self.assertIsNotNone(md.trigger_summary)
        self.assertEqual(md.trigger_summary.trigger_count, 2)


class _FakeArchive:
    def __init__(self, files):
        self._files = files

    def has_file(self, name):
        return name in self._files

    def read_file(self, name):
        return self._files[name]


if __name__ == "__main__":
    unittest.main()
