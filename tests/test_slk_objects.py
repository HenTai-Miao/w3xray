"""内嵌 SLK 对象数据解析测试：找文件→解析→合并，及引用列抽取。

SLK 优化图(本工具借鉴来源的工具包产物)把对象数据转成 *Data.slk；本测试验证
slk_objects 能解出对象与字段，并配合 references.extract_refs_by_column 抽出引用。
真图断言用随包的 U9 失落的宿命(若存在)。
"""
import hashlib
from pathlib import Path
import unittest

from w3xtool.slk_objects import (
    parse_category_objects, has_any_slk_objects, slk_col_label, SLK_CATEGORY_FILES,
)
from w3xtool.references import extract_refs_by_column

REFERENCE_MAP = Path(__file__).parent / "fixtures" / "reference" / "stormlib-slk-map.w3x"
REFERENCE_MAP_SHA256 = "eee3f01c2dbe16a22913b4a621780452dc2febe0557a97c54479e8742ec73b9f"


def _slk(cols, rows):
    """造一个最小 SLK 文本：cols=列名表(第1列是码键)，rows=[(码, {列:值})]。"""
    lines = ["ID;P", f"B;X{len(cols)};Y{len(rows) + 1}"]
    for x, c in enumerate(cols, 1):
        lines.append(f'C;X{x};Y1;K"{c}"')
    for y, (code, d) in enumerate(rows, 2):
        lines.append(f'C;X1;Y{y};K"{code}"')
        for x, c in enumerate(cols, 1):
            if c in d:
                lines.append(f'C;X{x};Y{y};K"{d[c]}"')
    lines.append("E")
    return "\n".join(lines)


class _FakeArchive:
    def __init__(self, files):           # {内部名: 文本}
        self.files = files

    def has_file(self, name):
        return name in self.files

    def read_file(self, name):
        return self.files[name].encode("latin-1")


class ParseCategoryTest(unittest.TestCase):
    def test_parse_and_merge_units(self):
        # 单位跨 UnitData + UnitWeapons 合并同码列
        a = _FakeArchive({
            "Units\\UnitData.slk": _slk(["unitID", "race"], [("hfoo", {"race": "human"})]),
            "Units\\UnitWeapons.slk": _slk(["unitID", "dmgplus1"], [("hfoo", {"dmgplus1": "5"})]),
        })
        objs = parse_category_objects(a, "单位")
        self.assertIn("hfoo", objs)
        self.assertEqual(objs["hfoo"].get("race"), "human")
        self.assertEqual(objs["hfoo"].get("dmgplus1"), "5")

    def test_malformed_sibling_slk_keeps_valid_category_data(self):
        # Given: one corrupt unit table and one valid sibling table.
        a = _FakeArchive({
            "Units\\UnitData.slk": "not an slk",
            "Units\\UnitWeapons.slk": _slk(["unitID", "dmgplus1"], [("hfoo", {"dmgplus1": "7"})]),
        })

        # When: the category is parsed.
        objs = parse_category_objects(a, "单位")

        # Then: the valid sibling source is not discarded.
        self.assertEqual(objs["hfoo"]["dmgplus1"], "7")

    def test_filters_non_code_rows(self):
        a = _FakeArchive({"AbilityData.slk": _slk(
            ["code", "BuffID1"], [("AHwe", {"BuffID1": "BHwe"}), ("toolong", {"BuffID1": "Bx"})])})
        objs = parse_category_objects(a, "技能")
        self.assertIn("AHwe", objs)
        self.assertNotIn("toolong", objs)        # 非 4 字符码行剔除

    def test_has_any_slk(self):
        self.assertFalse(has_any_slk_objects(_FakeArchive({})))
        self.assertTrue(has_any_slk_objects(_FakeArchive(
            {"Units\\AbilityData.slk": _slk(["code"], [("AHbz", {})])})))

    def test_ref_extraction_on_slk_row(self):
        # SLK 技能行的 UnitID1/BuffID1 应被 extract_refs_by_column 抽为引用
        a = _FakeArchive({"Units\\AbilityData.slk": _slk(
            ["code", "UnitID1", "BuffID1"], [("AHwe", {"UnitID1": "hwat", "BuffID1": "BHwe"})])})
        row = parse_category_objects(a, "技能")["AHwe"]
        refs = dict(extract_refs_by_column(row, "技能"))
        self.assertEqual(refs.get("UnitID1"), ["hwat"])
        self.assertEqual(refs.get("BuffID1"), ["BHwe"])

    def test_col_label(self):
        self.assertEqual(slk_col_label("Name"), "名称")
        self.assertEqual(slk_col_label("ZzUnknown"), "ZzUnknown")   # 未知列原样

    def test_col_label_level_suffix(self):
        # 等级后缀列：去数字查基名 + (等级N)
        self.assertEqual(slk_col_label("Cast2"), "施法间隔 (等级2)")
        self.assertEqual(slk_col_label("BuffID1"), "buff效果 (等级1)")
        self.assertEqual(slk_col_label("DataA3"), "数据A (等级3)")
        # 多位等级后缀也认（去整段末尾数字）
        self.assertEqual(slk_col_label("DataA10"), "数据A (等级10)")
        self.assertEqual(slk_col_label("Cost12"), "魔法消耗 (等级12)")
        # 基名不认识的带数字列不乱改
        self.assertEqual(slk_col_label("Zz9"), "Zz9")

    def test_noise_cols(self):
        from w3xtool.slk_objects import is_noise_col
        self.assertTrue(is_noise_col("code", "技能"))        # 冗余自码
        self.assertTrue(is_noise_col("comments", "技能"))    # [AlwaysEmpty]
        self.assertTrue(is_noise_col("InBeta", "物品"))
        self.assertFalse(is_noise_col("BuffID1", "技能"))    # 玩法列保留
        self.assertFalse(is_noise_col("race", "单位"))       # race 对单位有意义(不在其噪声表)

    def test_all_categories_have_files(self):
        for cat in ("单位", "物品", "技能", "科技", "可破坏物", "增益", "装饰物"):
            self.assertIn(cat, SLK_CATEGORY_FILES)


class ReferenceSlkMapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from w3xtool.api import load_map
        cls.md = load_map(str(REFERENCE_MAP))

    def test_reference_fixture_hash_is_pinned(self):
        self.assertEqual(hashlib.sha256(REFERENCE_MAP.read_bytes()).hexdigest(), REFERENCE_MAP_SHA256)

    def test_slk_objects_parsed(self):
        slk_objs = [o for objs in self.md.objects.values() for o in objs if o.ext == "slk"]
        self.assertTrue(slk_objs)                # 解出了 SLK 独有对象

    def test_ability_data_recovered(self):
        # AHwe(召唤水元素) 原本只有名字；SLK 解析后应有大量字段 + UnitID1 引用
        o = self.md.obj_index.get("AHwe")
        self.assertIsNotNone(o)
        self.assertGreater(len(o.fields), 10)
        refs = self.md.references.get("AHwe") or []
        targets = {c for _lab, resolved in refs for c, _n in resolved}
        self.assertIn("hwat", targets)           # 召唤的水元素

    def test_no_duplicate_codes(self):
        codes = [o.obj_id for objs in self.md.objects.values() for o in objs]
        self.assertEqual(len(codes), len(set(codes)))

    def test_noise_hidden_and_levels_labeled(self):
        # AHbz：编辑器噪声列(code/comments/version)应被隐藏；等级后缀列应是中文带等级
        o = self.md.obj_index.get("AHbz")
        self.assertIsNotNone(o)
        labels = [lab for lab, _ in o.fields]
        for noise in ("code", "comments", "version", "sort", "InBeta"):
            self.assertNotIn(noise, labels)
        self.assertTrue(any("(等级" in lab for lab in labels))   # 如 施法间隔 (等级2)

if __name__ == "__main__":
    unittest.main()
