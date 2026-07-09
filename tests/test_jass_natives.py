"""脚本侧引用补全测试：native 参数分类提码 + BJ 特征/隐式码。

数据(jass_natives.py)由 build_jass_natives.py 从 common.j/blizzard.j 离线生成。
"""
import unittest

from w3xtool import script_scan
from w3xtool.script_scan import (
    scan_object_refs, scan_script_features, scan_all_referenced_codes,
)


class BakedTableTest(unittest.TestCase):
    def test_native_table_nonempty_and_sane(self):
        N = script_scan.NATIVE_OBJ_FUNCS
        self.assertGreater(len(N), 20)
        # 关键 native 的分类正确
        self.assertEqual(N.get("CreateUnit"), "单位")
        self.assertEqual(N.get("UnitAddAbility"), "技能")
        self.assertEqual(N.get("CreateItem"), "物品")
        self.assertEqual(N.get("CreateDestructable"), "可破坏物")

    def test_bj_tables_nonempty(self):
        self.assertIn("MeleeStartingUnitsHuman", script_scan.BJ_FEATURES)
        self.assertTrue(script_scan.BJ_FUNC_CODES.get("MeleeStartingUnitsHuman"))
        self.assertEqual(script_scan.BJ_CODE_CONSTANTS.get("bj_ELEVATOR_CODE01"), "DTrf")


class ScanObjectRefsTest(unittest.TestCase):
    def test_ability_code_categorized(self):
        # 早期版本只认 物品/单位；现在技能码也能归类
        script = "call UnitAddAbility(u, 'AHbz')\n"
        refs = scan_object_refs(script)
        self.assertIn("AHbz", refs["技能"])

    def test_unit_and_item(self):
        script = ("set u = CreateUnit(p, 'hfoo', 0, 0, 0)\n"
                  "call UnitAddItemById(u, 'Iitm')\n")
        refs = scan_object_refs(script)
        self.assertIn("hfoo", refs["单位"])
        self.assertIn("Iitm", refs["物品"])

    def test_multiline_native_call_is_categorized(self):
        # Given: GUI-generated JASS may wrap native arguments across lines.
        script = "\n".join((
            "call CreateUnit(",
            "    Player(0),",
            "    'hfoo',",
            "    0.,",
            "    0.,",
            "    270.",
            ")",
        ))

        # When: object references are scanned.
        refs = scan_object_refs(script)

        # Then: the unit code is still categorized.
        self.assertIn("hfoo", refs["单位"])

    def test_destructable(self):
        script = "call CreateDestructable('Dtre', 0, 0, 0, 1, 0)\n"
        refs = scan_object_refs(script)
        self.assertIn("Dtre", refs["可破坏物"])

    def test_all_categories_keys_present(self):
        refs = scan_object_refs("")
        for c in ("单位", "物品", "技能", "科技", "可破坏物", "增益"):
            self.assertIn(c, refs)

    def test_non_object_line_ignored(self):
        # 不含对象码 native 的行不收码（避免误收伤害/金钱等整数）
        refs = scan_object_refs("set damage = 1234\ncall BJDebugMsg(\"hi\")\n")
        self.assertEqual(sum(len(s) for s in refs.values()), 0)

    def test_multi_native_line_not_miscategorized(self):
        # 一行同时调单位与物品 native：歧义行不归类，避免把码错配到分类
        script = "set x = CreateUnit(p,'hfoo',0,0,0)\ncall UnitAddItemById(u,'Iitm')\n"
        # 分行时各自单类 → 正常归类
        refs = scan_object_refs(script)
        self.assertIn("hfoo", refs["单位"])
        self.assertIn("Iitm", refs["物品"])
        # 同一行嵌套调用两类 native → 整行不归类(码不会错配到对方分类)
        one = scan_object_refs("set it = UnitAddItemById(CreateUnit(p,'hfoo',0,0,0), 'Iitm')\n")
        self.assertNotIn("Iitm", one["单位"])
        self.assertNotIn("hfoo", one["物品"])

    def test_get_object_name_excluded(self):
        # GetObjectName 是泛型(取任意对象名)，按 objectId 参数名会误判为可破坏物，应被排除
        self.assertNotIn("GetObjectName", script_scan.NATIVE_OBJ_FUNCS)

    def test_bj_implicit_codes_are_categorized_as_object_refs(self):
        script = ("call MeleeStartingUnitsHuman(p, loc, true, true, true)\n"
                  "call MeleeGrantItemsToHero(hero)\n")
        refs = scan_object_refs(script)
        self.assertIn("hpea", refs["单位"])
        self.assertIn("Amic", refs["技能"])
        self.assertIn("stwp", refs["物品"])

    def test_bj_code_constants_are_categorized(self):
        refs = scan_object_refs("set blocker = bj_ELEVATOR_CODE01\n")
        self.assertIn("DTrf", refs["可破坏物"])


class ScriptFeaturesTest(unittest.TestCase):
    def test_melee_feature_and_implicit_codes(self):
        script = "call MeleeStartingUnitsHuman(p, loc, true, true, true)\n"
        feats, implicit = scan_script_features(script)
        self.assertIn("人族对战开局", feats)
        self.assertIn("htow", implicit)        # 人族主基地是隐式引用

    def test_no_feature(self):
        feats, implicit = scan_script_features("call DoNothing()\n")
        self.assertEqual(feats, [])
        self.assertEqual(implicit, set())

    def test_elevator_constant(self):
        feats, implicit = scan_script_features("set id = bj_ELEVATOR_CODE01\n")
        self.assertIn("DTrf", implicit)


class AllReferencedCodesTest(unittest.TestCase):
    def test_collects_literals_and_implicit(self):
        script = ("call SomethingWith('Ax01')\n"
                  "call MeleeStartingUnitsOrc(p, loc, true, true, true)\n")
        codes = scan_all_referenced_codes(script)
        self.assertIn("Ax01", codes)           # 裸 'xxxx' 字面量也算根
        self.assertTrue(any(c.islower() for c in codes))  # 兽族隐式基础单位码

    def test_collects_fourcc_double_quoted(self):
        # Lua 写法 FourCC("Axyz") 不带单引号、所在行无 native，也应进根集合
        codes = scan_all_referenced_codes('local id = FourCC("Axyz")\n')
        self.assertIn("Axyz", codes)

    def test_ignores_comment_and_display_string_rawcodes(self):
        # Given: comments and user-facing strings mention text that looks like rawcodes.
        script = "\n".join((
            "// removed old unit 'hfoo'",
            "call BJDebugMsg(\"debug marker 'A001'\")",
            "call DoNothing()",
        ))

        # When: root object references are collected for orphan analysis.
        codes = scan_all_referenced_codes(script)

        # Then: non-executable text does not suppress orphan detection.
        self.assertNotIn("hfoo", codes)
        self.assertNotIn("A001", codes)


if __name__ == "__main__":
    unittest.main()
