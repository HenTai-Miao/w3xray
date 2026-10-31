"""Source fields and category identities survive collection and compatibility paths."""

from __future__ import annotations

import json

from gametool.client_object_data import ClientBaseObject, merge_client_base_objects
from gametool.base_catalog import english_name_for, fine_category_for
from gametool.knowledge_object_exports import format_object_fields
from gametool.map_data import GameObject, MapData
from gametool.object_id_summary import format_object_id_usage_summary
from gametool.object_pipeline import add_base_objects, load_object_pipeline
from gametool.object_text_exports import format_object_text_tsv
from gametool.object_text_presentation import format_complete_text_section
from tests.test_object_candidate_collection import FakeArchive, _binary_object, _slk


def test_empty_function_fields_suppress_inherited_values_and_retain_unknown_keys() -> (
    None
):
    source = "Units\\HumanUnitFunc.txt"
    archive = FakeArchive(
        {source: b"[hfoo]\nSellitems=\nHP=\nArt=\nUnknownExtension=\n"}
    )
    md = MapData("empty.w3x", "empty")
    load_object_pipeline(
        md,
        archive,
        {},
        base_objects={
            "hfoo": (
                "单位",
                (("售出的物品", "I000"), ("生命上限", "420"), ("图标", "old.blp")),
            )
        },
    )
    unit = md.obj_identity_index[("单位", "hfoo")]
    fields = {row.key: row for row in unit.field_evidence if row.source == source}
    assert set(fields) == {"Sellitems", "HP", "Art", "UnknownExtension"}
    assert all(row.value == row.raw_value == "" for row in fields.values())
    assert unit.field_values["Sellitems"] == ""
    assert unit.field_values["HP"] == ""
    assert unit.field_values["UnknownExtension"] == ""
    assert unit.icon == ""
    assert all(value != "I000" for _label, value in unit.fields)
    exported = format_object_fields(md)
    assert "UnknownExtension" in exported and source in exported


def test_slk_editor_and_classification_fields_keep_complete_cell_evidence() -> None:
    source = "Units\\AbilityData.slk"
    expected = {
        "comments": "whole source note",
        "hero": "1",
        "code": "AHbz",
        "version": "",
    }
    archive = FakeArchive(
        {source: _slk(("abilityID", *expected), (("A001", expected),))}
    )
    md = MapData("slk.w3x", "slk")
    load_object_pipeline(md, archive, {}, base_objects={})
    skill = md.obj_identity_index[("技能", "A001")]
    evidence = {row.key: row for row in skill.field_evidence}
    assert set(evidence) == set(expected)
    for key, value in expected.items():
        assert evidence[key].value == value
        assert evidence[key].source == source
        encoded = json.loads(evidence[key].encoded_evidence)
        assert encoded["cell"]["raw"] == f'K"{value}"'
        assert encoded["record"]["raw"].endswith("\n")
    exported = format_object_fields(md)
    assert all(key in exported for key in expected)


def test_source_counts_include_same_rawcode_in_independent_categories() -> None:
    archive = FakeArchive(
        {
            "Units\\HumanUnitStrings.txt": b"[X001]\nName=Unit\n",
            "Units\\ItemStrings.txt": b"[X001]\nName=Item\n",
        }
    )
    md = MapData("categories.w3x", "categories")
    load_object_pipeline(md, archive, {}, base_objects={})
    assert set(md.obj_identity_index) == {("单位", "X001"), ("物品", "X001")}
    assert md.object_source_counts == {"text": 2}


def test_base_addition_preserves_other_category_collision_and_is_idempotent() -> None:
    custom = GameObject("物品", "w3t", "hfoo", "ratf", "Map item", True)
    md = MapData("base.w3x", "base", objects={"物品": [custom]})
    base = {"hfoo": ("单位", (("生命上限", "420"),))}
    add_base_objects(md, base)
    add_base_objects(md, base)
    assert set(md.obj_identity_index) == {("单位", "hfoo"), ("物品", "hfoo")}
    assert md.obj_identity_index[("物品", "hfoo")] is custom
    assert (
        md.obj_identity_index[("单位", "hfoo")].field_values["base:生命上限"] == "420"
    )
    assert sum(len(bucket) for bucket in md.objects.values()) == 2


def test_client_fields_do_not_cross_same_rawcode_category_boundary() -> None:
    base = {"X001": ("单位", (("生命上限", "420"),))}
    snapshot = (
        ClientBaseObject("X001", "物品", (("金币", "250"),)),
        ClientBaseObject("X001", "单位", (("魔法上限", "100"),)),
    )
    merged = merge_client_base_objects(base, snapshot)
    assert merged["X001"] == ("单位", (("生命上限", "420"), ("魔法上限", "100")))
    assert snapshot[0].fields == (("金币", "250"),)


def test_catalog_name_and_classification_require_the_objects_own_category() -> None:
    archive = FakeArchive(
        {"war3map.w3t": _binary_object("hfoo", "X001", (("utub", "Own tooltip"),))}
    )
    md = MapData("category.w3x", "category")
    load_object_pipeline(md, archive, {}, base_objects={})
    item = md.obj_identity_index[("物品", "X001")]
    assert item.name == "X001"
    assert "Footman" not in item.search_text
    text = format_object_text_tsv(md.object_texts)
    assert "Footman" not in text and "步兵" not in text
    assert english_name_for("hfoo", category="物品") == ""
    assert fine_category_for("hfoo", category="物品") == ""
    assert english_name_for("hfoo", category="单位") == "Footman"


def test_large_declared_text_level_preserves_conflicts_export_and_presentation() -> (
    None
):
    digits = "9" * 5000
    archive = FakeArchive(
        {
            "Units\\HumanUpgradeStrings.txt": f"[R001]\ngtp{digits}=first\n".encode(),
            "Units\\OrcUpgradeStrings.txt": f"[R001]\ngtp{digits}=second\n".encode(),
        }
    )
    md = MapData("large-level.w3x", "large-level")
    load_object_pipeline(md, archive, {}, base_objects={})
    rows = [row for row in md.object_texts.records if row.field_key == "gtp" + digits]
    assert len(rows) == 2 and all(row.conflict_group and row.is_current for row in rows)
    exported = format_object_text_tsv(md.object_texts)
    presented = format_complete_text_section(
        md, md.obj_identity_index[("科技", "R001")]
    )
    assert digits in exported and digits in presented
    assert "first" in exported and "second" in exported


def test_object_id_summary_retains_every_category_without_multiplying_id_counts() -> (
    None
):
    unit = GameObject("单位", "w3u", "X001", "hfoo", "unit name", True)
    item = GameObject("物品", "w3t", "X001", "ratf", "item name", True)
    md = MapData("summary.w3x", "summary", objects={"单位": [unit], "物品": [item]})
    md.scripts = {"war3map.j": "call CreateUnit(Player(0), 'X001', 0, 0, 0)"}
    rendered = format_object_id_usage_summary(md)
    (line,) = [line for line in rendered.splitlines() if line.startswith("X001\t")]
    fields = line.split("\t")
    assert "单位" in fields[2] and "物品" in fields[2]
    assert "unit name" in fields[3] and "item name" in fields[3]
    assert "w3u" in fields[4] and "w3t" in fields[4]
    assert fields[5] == "1"
    assert "按ID汇总" in fields[9]
    md.objects = {"物品": [item], "单位": [unit]}
    assert format_object_id_usage_summary(md) == rendered
