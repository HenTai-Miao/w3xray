"""field_meta 生成表（适用性/值域/常量）与 fields 查询助手测试。

表断言只用已提交的生成表；生成器测试用临时合成输入，不依赖游戏安装或网络。
"""

from __future__ import annotations

from w3xtool.api import GameObject
from w3xtool.field_meta import (
    FIELD_TYPES,
    GENERATED_FIELD_APPLICABILITY,
    GENERATED_FIELD_BOUNDS,
    GENERATED_FIELD_CONSTANTS,
    GENERATED_FIELD_LABELS,
)
from w3xtool.fields import (
    ability_field_applicable,
    ability_field_bounds,
    ability_field_constant,
    ability_field_specificity,
)
from w3xtool.object_detail_presentation import format_object_fields

import build_field_labels as bfl


def test_generated_tables_spot_checks():
    # 与快照/常量源对账：Efk1 完整三件套，amcs 无适用性限定
    assert GENERATED_FIELD_APPLICABILITY["Efk1"] == (("AEfk", "Aroc"), ())
    assert GENERATED_FIELD_BOUNDS["Efk1"] == ("0", "99999")
    assert GENERATED_FIELD_CONSTANTS["Efk1"] == "ABILITY_RLF_DAMAGE_PER_TARGET_EFK1"
    assert GENERATED_FIELD_CONSTANTS["Hbz1"] == "ABILITY_ILF_NUMBER_OF_WAVES"
    assert GENERATED_FIELD_APPLICABILITY.get("amcs", ((), ())) == ((), ())
    # 双逗号空段已被过滤（Iagi 的 useSpecific 含连续逗号）
    assert all(code for code in GENERATED_FIELD_APPLICABILITY["Iagi"][0])


def test_ability_field_helpers():
    assert ability_field_specificity("Efk1") == (("AEfk", "Aroc"), ())
    assert ability_field_bounds("Efk1") == ("0", "99999")
    assert ability_field_constant("Hbz1") == "ABILITY_ILF_NUMBER_OF_WAVES"
    assert ability_field_constant("zzz9") == ""
    # 适用性判定：useSpecific 命中/未命中，无元数据不做断言
    assert ability_field_applicable("Efk1", "AEfk") is True
    assert ability_field_applicable("Efk1", "AHhb") is False
    assert ability_field_applicable("amcs", "AHhb") is None


def _ability_object() -> GameObject:
    return GameObject(
        category="技能",
        ext="w3a",
        obj_id="A001",
        base_id="AEfk",
        name="自定义鹰身女妖风暴",
        is_custom=True,
        fields=[("数据", "200"), ("数据", "1")],
        field_values={"Efk1": "200", "Ocr6": "1"},
        field_labels={"Efk1": "伤害(每目标)", "Ocr6": "排除物品伤害"},
    )


def test_detail_fields_annotate_bounds_and_applicability_in_full_mode():
    text = format_object_fields(_ability_object(), detailed=True)
    assert "范围 ≥0，≤99999" in text
    assert "常量 ABILITY_RLF_DAMAGE_PER_TARGET_EFK1" in text
    # Ocr6 的 useSpecific 是 AOcr/ACct/ANdb，基础 AEfk 未列出
    assert "基础技能未列出此字段" in text


def test_detail_fields_keep_current_mode_clean():
    text = format_object_fields(_ability_object(), detailed=False)
    assert "范围 ≥" not in text
    assert "基础技能未列出此字段" not in text
    assert "常量 ABILITY_" not in text


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="latin-1")


def _synthetic_meta(tmp_path):
    meta = tmp_path / "meta"
    _write(
        meta / "units" / "abilitymetadata.slk",
        "ID;PWXL\nB;Y3;X6\n"
        'C;X1;Y1;K"id"\nC;X2;Y1;K"displayName"\nC;X3;Y1;K"type"\n'
        'C;X4;Y1;K"useSpecific"\nC;X5;Y1;K"minVal"\nC;X6;Y1;K"maxVal"\n'
        'C;X1;Y2;K"Efk1"\nC;X2;Y2;K"WESTRING_AEVAL_EFK1"\nC;X3;Y2;K"unreal"\n'
        'C;X4;Y2;K"AEfk,,Aroc"\nC;X5;Y2;K"0"\nC;X6;Y2;K"99999"\n'
        'C;X1;Y3;K"Ocr6"\nC;X2;Y3;K"WESTRING_AEVAL_OCR6"\nC;X3;Y3;K"bool"\n'
        'C;X4;Y3;K"AOcr"\nE\n',
    )
    common = tmp_path / "common.j"
    common.write_text(
        "constant abilityintegerlevelfield ABILITY_ILF_NUMBER_OF_WAVES"
        " = ConvertAbilityIntegerLevelField('Hbz1')\n",
        encoding="utf-8",
    )
    return str(meta), str(common)


def test_generator_build_extracts_new_tables_and_preserves_labels(tmp_path):
    meta_dir, common_j = _synthetic_meta(tmp_path)
    before_labels = dict(GENERATED_FIELD_LABELS)
    before_types = dict(FIELD_TYPES)
    labels, types, applicability, bounds, constants, found, _unresolved = bfl.build(
        meta_dir, common_j
    )
    # 标签/类型保留现有值，只补新码
    assert all(labels[k] == v for k, v in before_labels.items())
    assert all(types[k] == v for k, v in before_types.items())
    assert found == 2
    assert applicability == {
        "Efk1": (("AEfk", "Aroc"), ()),
        "Ocr6": (("AOcr",), ()),
    }
    assert bounds == {"Efk1": ("0", "99999")}
    assert constants == {"Hbz1": "ABILITY_ILF_NUMBER_OF_WAVES"}


def test_generator_write_module_emits_all_tables(tmp_path):
    out = tmp_path / "field_meta_out.py"
    bfl.write_module(
        {"Efk1": "伤害"},
        {"Efk1": "unreal"},
        {"Efk1": (("AEfk",), ())},
        {"Efk1": ("0", "99999")},
        {"Hbz1": "ABILITY_ILF_NUMBER_OF_WAVES"},
        str(out),
    )
    text = out.read_text(encoding="utf-8")
    assert "GENERATED_FIELD_LABELS" in text
    assert "GENERATED_FIELD_APPLICABILITY" in text
    assert "GENERATED_FIELD_BOUNDS" in text
    assert "GENERATED_FIELD_CONSTANTS" in text
    assert "'Hbz1': 'ABILITY_ILF_NUMBER_OF_WAVES'" in text
