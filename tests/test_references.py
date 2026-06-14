"""对象引用分析测试：引用边抽取(类型驱动/列名驱动) + 引用图与孤立判定。

只读分析——把优化器 [SearchObjectData] 的"哪些字段指向别的对象"知识落成本工具的
正向/反向引用与孤立对象报告。
"""
import unittest

from w3xtool.api import GameObject, MapData
from w3xtool.references import (
    _split_codes, extract_refs_by_type, extract_refs_by_column,
    build_reference_graph, REF_TYPES,
)
from w3xtool.w3obj import Modification


class _FakeType:
    """模拟 fields.field_type：按预设字典返回字段类型。"""
    def __init__(self, mapping):
        self.mapping = mapping

    def __call__(self, fid):
        return self.mapping.get(fid, "")


class SplitCodesTest(unittest.TestCase):
    def test_single_code(self):
        self.assertEqual(_split_codes("A001"), ["A001"])

    def test_comma_list(self):
        self.assertEqual(_split_codes("A001,A002,hfoo"), ["A001", "A002", "hfoo"])

    def test_pipe_separator(self):
        self.assertEqual(_split_codes("A001|A002"), ["A001", "A002"])

    def test_filters_placeholders_and_numbers(self):
        # 空占位、纯数字(计数而非码)、长度不为4 的都剔除
        self.assertEqual(_split_codes("A001,_,____,0000,12,1234abc, ,hpea"),
                         ["A001", "hpea"])

    def test_non_string(self):
        self.assertEqual(_split_codes(5), [])
        self.assertEqual(_split_codes(None), [])

    def test_denylist_words(self):
        # 4 字符英文词/枚举值(targs 等)不是对象码，剔除
        self.assertEqual(_split_codes("self,tree,none,A001,true"), ["A001"])


class ExtractByTypeTest(unittest.TestCase):
    def test_keeps_only_reference_types(self):
        ft = _FakeType({"uabi": "abilityList", "uhpm": "int", "ucod": "unitCode"})
        mods = [
            Modification("uabi", 3, 0, "AHbz,AHtb"),   # 引用类(技能列表)
            Modification("uhpm", 0, 0, 500),            # int，非引用
            Modification("ucod", 3, 0, "hfoo"),         # unitCode，引用
        ]
        refs = extract_refs_by_type(mods, ft)
        self.assertEqual(refs, [("uabi", ["AHbz", "AHtb"]), ("ucod", ["hfoo"])])

    def test_empty_ref_field_dropped(self):
        ft = _FakeType({"uabi": "abilityList"})
        mods = [Modification("uabi", 3, 0, "_,____")]  # 全是占位
        self.assertEqual(extract_refs_by_type(mods, ft), [])

    def test_ref_types_cover_expected(self):
        for t in ("abilCode", "unitList", "itemList", "buffList", "techList"):
            self.assertIn(t, REF_TYPES)

    def test_dedup_across_levels(self):
        # w3a 技能引用字段逐等级各一条(同 field_id 多次)：应按 field_id 合并去重
        ft = _FakeType({"uabi": "abilityList"})
        mods = [Modification("uabi", 3, 1, "A001"),
                Modification("uabi", 3, 2, "A001"),
                Modification("uabi", 3, 3, "A001")]
        self.assertEqual(extract_refs_by_type(mods, ft), [("uabi", ["A001"])])

    def test_aggregate_distinct_codes_across_levels(self):
        ft = _FakeType({"uabi": "abilityList"})
        mods = [Modification("uabi", 3, 1, "A001"), Modification("uabi", 3, 2, "A002")]
        self.assertEqual(extract_refs_by_type(mods, ft), [("uabi", ["A001", "A002"])])


class ExtractByColumnTest(unittest.TestCase):
    def test_unit_columns(self):
        fields = {"Name": "步兵", "abilList": "AHbz,Aave", "Trains": "hfoo,hbar",
                  "uhpm": "ignored"}
        refs = dict(extract_refs_by_column(fields, "单位"))
        self.assertEqual(refs["abilList"], ["AHbz", "Aave"])
        self.assertEqual(refs["Trains"], ["hfoo", "hbar"])
        self.assertNotIn("Name", refs)

    def test_unknown_category(self):
        self.assertEqual(extract_refs_by_column({"abilList": "AHbz"}, "增益"), [])


def _obj(cat, oid, name, is_custom=True, ref_fields=None):
    return GameObject(category=cat, ext="w3u", obj_id=oid, base_id=oid,
                      name=name, is_custom=is_custom, ref_fields=ref_fields or [])


class BuildGraphTest(unittest.TestCase):
    def _mk(self):
        # 单位 H001 引用技能 A001；技能 A001 无引用；物品 I001 谁都不引用(孤立)
        unit = _obj("单位", "H001", "英雄", ref_fields=[("uabi", ["A001"])])
        abil = _obj("技能", "A001", "火球")
        item = _obj("物品", "I001", "孤立物品")
        md = MapData(path="x", name="x")
        md.objects = {"单位": [unit], "技能": [abil], "物品": [item]}
        md.obj_index = {"H001": unit, "A001": abil, "I001": item}
        return md, unit, abil, item

    def test_forward_reference_resolved(self):
        md, unit, abil, item = self._mk()
        build_reference_graph(md)
        self.assertIn("H001", md.references)
        label, resolved = md.references["H001"][0]
        self.assertEqual(resolved, [("A001", "火球")])  # 码还原成名字

    def test_reverse_index(self):
        md, *_ = self._mk()
        build_reference_graph(md)
        self.assertIn("A001", md.referenced_by)
        referrer_id, referrer_name, _label = md.referenced_by["A001"][0]
        self.assertEqual((referrer_id, referrer_name), ("H001", "英雄"))

    def test_orphan_is_unreferenced_custom(self):
        md, *_ = self._mk()
        build_reference_graph(md)
        orphan_ids = {o.obj_id for o in md.orphans}
        self.assertIn("I001", orphan_ids)       # 没人引用 → 孤立
        self.assertNotIn("A001", orphan_ids)    # 被 H001 引用 → 不孤立

    def test_referenced_object_not_orphan(self):
        md, *_ = self._mk()
        build_reference_graph(md)
        self.assertNotIn("A001", {o.obj_id for o in md.orphans})

    def test_base_object_never_orphan(self):
        md, *_ = self._mk()
        base = _obj("单位", "hfoo", "原版农民", is_custom=False)
        md.objects["单位"].append(base)
        md.obj_index["hfoo"] = base
        build_reference_graph(md)
        self.assertNotIn("hfoo", {o.obj_id for o in md.orphans})  # 原版不计孤立

    def test_self_reference_still_orphan(self):
        # 对象只引用自己 → 自引用不计入"被引用"，对象仍应判为孤立
        unit = _obj("单位", "H001", "英雄", ref_fields=[("uabi", ["H001"])])
        md = MapData(path="x", name="x")
        md.objects = {"单位": [unit]}
        md.obj_index = {"H001": unit}
        build_reference_graph(md)
        self.assertIn("H001", {o.obj_id for o in md.orphans})
        self.assertNotIn("H001", md.referenced_by)   # 自引用不进反向

    def test_no_duplicate_reverse_edges(self):
        # 同对象同标签重复引用同码 → 反向只一条
        unit = _obj("单位", "H001", "英雄",
                    ref_fields=[("uabi", ["A001"]), ("uabi", ["A001"])])
        abil = _obj("技能", "A001", "火球")
        md = MapData(path="x", name="x")
        md.objects = {"单位": [unit], "技能": [abil]}
        md.obj_index = {"H001": unit, "A001": abil}
        build_reference_graph(md)
        self.assertEqual(len(md.referenced_by["A001"]), 1)

    def test_reverse_collapses_level_columns(self):
        # SLK 的 BuffID1/BuffID2 等逐级列引用同一码 → 反向"被谁引用"应折叠为一条(去等级)
        abil = _obj("技能", "A001", "火球",
                    ref_fields=[("BuffID1", ["B001"]), ("BuffID2", ["B001"])])
        buff = _obj("增益", "B001", "灼烧")
        md = MapData(path="x", name="x")
        md.objects = {"技能": [abil], "增益": [buff]}
        md.obj_index = {"A001": abil, "B001": buff}
        build_reference_graph(md)
        self.assertEqual(len(md.referenced_by["B001"]), 1)
        _rid, _rn, label = md.referenced_by["B001"][0]
        self.assertEqual(label, "buff效果")        # 已去掉"(等级N)"

    def test_unloaded_ref_falls_back_to_base_names(self):
        # 引用到一个未作为对象加载的标准 buff，名字应回退取 BASE_NAMES(而非裸码/None)
        from w3xtool import base_names
        code = next((k for k in base_names.BASE_NAMES if k[:1] == "B"), None)
        self.assertIsNotNone(code)               # 表里应有 buff 名(本次补充后)
        abil = _obj("技能", "A001", "火球", ref_fields=[("BuffID1", [code])])
        md = MapData(path="x", name="x")
        md.objects = {"技能": [abil]}             # 只加载技能；buff 不作为对象
        md.obj_index = {"A001": abil}
        build_reference_graph(md)
        _lab, resolved = md.references["A001"][0]
        rcode, rname = resolved[0]
        self.assertEqual(rcode, code)
        self.assertEqual(rname, base_names.BASE_NAMES[code])   # 回退到原版名

    def test_slk_column_label_translated(self):
        # SLK/文本对象的引用字段是列名(UnitID1)，标签应经 slk_col_label 中文化
        abil = _obj("技能", "A001", "火球", ref_fields=[("UnitID1", ["U001"])])
        summon = _obj("单位", "U001", "水元素")
        md = MapData(path="x", name="x")
        md.objects = {"技能": [abil], "单位": [summon]}
        md.obj_index = {"A001": abil, "U001": summon}
        build_reference_graph(md)
        label, resolved = md.references["A001"][0]
        self.assertEqual(label, "召唤/创建单位 (等级1)")
        self.assertEqual(resolved, [("U001", "水元素")])

    def test_low_coverage_flag(self):
        # 50+ 自定义对象、却几乎没有引用字段 → 判低覆盖（模拟 SLK 优化图）
        md = MapData(path="x", name="x")
        objs = [_obj("技能", f"A{i:03d}", f"技能{i}") for i in range(100)]
        objs[0].ref_fields = [("uabi", ["A001"])]   # 仅 1 个有引用
        md.objects = {"技能": objs}
        md.obj_index = {o.obj_id: o for o in objs}
        build_reference_graph(md)
        self.assertTrue(md.ref_low_coverage)

    def test_high_coverage_not_flagged(self):
        md, *_ = self._mk()           # 小图、单位有引用 → 不判低覆盖
        build_reference_graph(md)
        self.assertFalse(md.ref_low_coverage)

    def test_preplaced_type_is_root(self):
        from w3xtool.doo import Unit
        md, _u, _a, item = self._mk()
        # 把孤立物品改成被预放置引用(假装它是个被摆上去的单位类型)
        md.units = [Unit(type_id="I001", variation=0, x=0, y=0, z=0, angle=0)]
        build_reference_graph(md)
        self.assertNotIn("I001", {o.obj_id for o in md.orphans})  # 预放置 → 不孤立


if __name__ == "__main__":
    unittest.main()
