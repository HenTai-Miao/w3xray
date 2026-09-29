"""基础目录双语表（BASE_NAMES_EN / BASE_CATEGORIES）与生成器测试。

表断言只用已提交的生成表；生成器测试只用合成快照数据（临时目录），
不依赖真实游戏安装或网络。风格对齐 tests/test_build_base_names.py。
"""

from __future__ import annotations

from w3xtool.api import GameObject
from w3xtool.base_names import BASE_CATEGORIES, BASE_NAMES, BASE_NAMES_EN
from w3xtool.base_objects import BASE_OBJECTS
from w3xtool.item_relation_models import (
    ItemRelation,
    ItemRelationKind,
    RelationCompleteness,
    RelationConfidence,
    RelationEvidence,
    RelationObject,
)
from w3xtool.item_relation_query import filter_item_relations
from w3xtool.object_detail_presentation import format_object_summary
from w3xtool.object_materialization import (
    merge_object_candidates,
    named_base_candidates,
)

import build_base_catalog as bbc


def test_bilingual_names_spot_checks():
    # 中英名与 trainer 同源快照对账（中文来自本机游戏安装，英文来自 enUS 快照）
    assert BASE_NAMES["ckng"] == "国王之冠 +5"
    assert BASE_NAMES_EN["ckng"] == "Crown of Kings +5"
    assert BASE_NAMES_EN["AHhb"] == "Holy Light"
    assert BASE_NAMES_EN["Hpal"] == "Paladin"
    assert BASE_NAMES_EN["htow"] == "Town Hall"


def test_fine_categories_spot_checks():
    assert BASE_CATEGORIES["ckng"] == ("神器", "Artifact")
    assert BASE_CATEGORIES["AHhb"] == ("英雄技能", "Hero Ability")
    assert BASE_CATEGORIES["AIat"] == ("物品技能", "Item Ability")
    assert BASE_CATEGORIES["Adef"] == ("普通技能", "Standard Ability")
    assert BASE_CATEGORIES["Hpal"] == ("英雄", "Hero")
    assert BASE_CATEGORIES["htow"] == ("建筑", "Building")
    assert BASE_CATEGORIES["hfoo"] == ("单位", "Unit")
    assert BASE_CATEGORIES["gemt"] == ("其他物品", "Item")


def test_table_invariants():
    # 键是四字符 rawcode；细类值是双语二元组；中文表未被合并改写
    for table in (BASE_NAMES_EN, BASE_CATEGORIES):
        assert table
        assert all(len(code) == 4 for code in table)
    for value in BASE_CATEGORIES.values():
        assert isinstance(value, tuple) and len(value) == 2
        assert value[0] and value[1]
    assert len(BASE_NAMES) >= 2200


def test_object_search_text_is_bilingual():
    # 物化后的基础对象搜索文本应包含英文名与细类，浏览器可用英文关键字命中
    objects = merge_object_candidates(named_base_candidates(BASE_OBJECTS), BASE_OBJECTS)
    by_id = {obj.obj_id: obj for obj in objects}
    crown = by_id["ckng"]
    assert "Crown of Kings" in crown.search_text
    assert "神器" in crown.search_text
    paladin = by_id["Hpal"]
    assert "Paladin" in paladin.search_text


def test_object_summary_includes_english_and_fine_category():
    obj = GameObject(
        category="物品",
        ext="w3t",
        obj_id="I001",
        base_id="ckng",
        name="火焰之冠",
        is_custom=True,
        fields=[],
    )
    summary = format_object_summary(obj)
    assert "英文名：Crown of Kings +5" in summary
    assert "细类：神器（Artifact）" in summary
    assert "分类：物品" in summary


def test_object_summary_without_catalog_entry_keeps_plain_lines():
    obj = GameObject(
        category="物品",
        ext="w3t",
        obj_id="I002",
        base_id="z999",
        name="未知基底",
        is_custom=True,
        fields=[],
    )
    summary = format_object_summary(obj)
    assert "英文名：" not in summary
    assert "细类：" not in summary


def _crown_drop_relation() -> ItemRelation:
    return ItemRelation(
        kind=ItemRelationKind.UNIT_DROP,
        item=RelationObject("物品", "ckng", "国王之冠 +5"),
        source=RelationObject("单位", "nckb", "红龙"),
        evidence=RelationEvidence(source="war3mapUnits.doo", offset=128),
        confidence=RelationConfidence.CONFIRMED,
        completeness=RelationCompleteness.COMPLETE,
    )


def test_relation_filter_matches_english_name():
    records = (_crown_drop_relation(),)
    assert filter_item_relations(records, "crown") == records
    assert filter_item_relations(records, "国王") == records
    assert filter_item_relations(records, "kings") == records
    assert filter_item_relations(records, "sword") == ()
    assert filter_item_relations(records, "town hall") == ()


def test_relation_endpoints_carry_fine_category():
    from w3xtool.api import MapData
    from w3xtool.item_relation_endpoints import resolve_relation_object

    md = MapData(path="x", name="x")
    crown, resolved = resolve_relation_object(md, "ckng", "物品")
    assert resolved
    assert crown.name == "国王之冠 +5"
    assert crown.fine_category == "神器"
    holy, resolved = resolve_relation_object(md, "AHhb", "技能")
    assert resolved
    assert holy.fine_category == "英雄技能"
    unknown, resolved = resolve_relation_object(md, "I999", "物品")
    assert not resolved
    assert unknown.fine_category == ""


# ---- 生成器（合成快照）----


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _synthetic_objectdata(root) -> None:
    enus_units = root / "_locales" / "enus.w3mod" / "units"
    _write(enus_units / "itemstrings.txt", "[ckng]\nName=Crown of Kings +5\n")
    units = root / "units"
    _write(
        units / "itemdata.slk",
        "ID;PWXL\nB;Y2;X2\n"
        'C;X1;Y1;K"itemID"\nC;X2;Y1;K"class"\n'
        'C;X1;Y2;K"ckng"\nC;X2;Y2;K"Artifact"\n'
        'C;X1;Y3;K"gemt"\nC;X2;Y3;K"Miscellaneous"\nE\n',
    )
    _write(
        units / "abilitydata.slk",
        "ID;PWXL\nB;Y2;X3\n"
        'C;X1;Y1;K"alias"\nC;X2;Y1;K"hero"\nC;X3;Y1;K"item"\n'
        'C;X1;Y2;K"AHhb"\nC;X2;Y2;K"1"\nC;X3;Y2;K"0"\n'
        'C;X1;Y3;K"AIat"\nC;X2;Y3;K"0"\nC;X3;Y3;K"1"\nE\n',
    )
    _write(
        units / "unitbalance.slk",
        "ID;PWXL\nB;Y2;X3\n"
        'C;X1;Y1;K"unitBalanceID"\nC;X2;Y1;K"Primary"\nC;X3;Y1;K"isbldg"\n'
        'C;X1;Y2;K"Hpal"\nC;X2;Y2;K"STR"\nC;X3;Y2;K"0"\n'
        'C;X1;Y3;K"htow"\nC;X2;Y3;K"_"\nC;X3;Y3;K"1"\nE\n',
    )


def test_parse_object_categories_from_synthetic_snapshot(tmp_path):
    root = tmp_path / "objectdata"
    _synthetic_objectdata(root)
    assert bbc.parse_object_categories(str(root)) == {
        "AHhb": ("英雄技能", "Hero Ability"),
        "AIat": ("物品技能", "Item Ability"),
        "ckng": ("神器", "Artifact"),
        "gemt": ("其他物品", "Item"),
        "Hpal": ("英雄", "Hero"),
        "htow": ("建筑", "Building"),
    }


def test_parse_en_names_strings_first_func_fill(tmp_path):
    root = tmp_path / "objectdata"
    _synthetic_objectdata(root)
    # 根目录 func 只补缺：enus strings 的名字优先
    _write(root / "units" / "itemfunc.txt", "[ckng]\nName=Wrong\n[zzzx]\nName=Fill\n")
    assert bbc.parse_en_names(str(root)) == {
        "ckng": "Crown of Kings +5",
        "zzzx": "Fill",
    }


def test_prefer_existing_casing_normalizes_keys():
    existing = {"AHhb": "圣光"}
    table = {"ahhb": "Holy Light", "hfoo": "Footman"}
    assert bbc._prefer_existing_casing(table, existing, "测试") == {
        "AHhb": "Holy Light",
        "hfoo": "Footman",
    }


def test_merge_objectdata_preserves_chinese_and_appends_tables(tmp_path):
    root = tmp_path / "objectdata"
    _synthetic_objectdata(root)
    out = tmp_path / "out"
    out.mkdir()
    bbc.merge_objectdata(str(root), out_dir=str(out))
    text = (out / "base_names.py").read_text(encoding="utf-8")
    # 中文名来自包内现有表，原样保留
    assert "'ckng': \"国王之冠 +5\"" in text
    assert "'hfoo': \"步兵\"" in text
    # 英文名/细类来自合成快照
    assert "'ckng': \"Crown of Kings +5\"" in text
    assert "'ckng': ('神器', 'Artifact')" in text
    assert "'AHhb': ('英雄技能', 'Hero Ability')" in text
