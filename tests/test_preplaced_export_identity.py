"""Preplaced exports never cross category boundaries to resolve names."""

from __future__ import annotations

import csv
from io import StringIO
import json
from pathlib import Path

import pytest

from gametool.api import GameObject, MapData
from gametool.base_catalog import english_name_for, fine_category_for
from gametool.doo import Doodad, Unit
from gametool.doo_drops import DropEntry, DropSet
from gametool.knowledge_preplaced_exports import (
    format_preplaced_doodads_tsv,
    format_preplaced_units_tsv,
)
from gametool.pack_query_cli import execute_pack_query
from gametool.pack_query_options import PackQueryCliOptions


@pytest.fixture(autouse=True)
def isolated_memo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from gametool import pack_query_cli

    monkeypatch.setattr(pack_query_cli, "_memo_dir", lambda: tmp_path / "memo")


def _obj(
    category: str, code: str = "X001", *, name: str = "", base: str = ""
) -> GameObject:
    return GameObject(
        category,
        {
            "单位": "w3u",
            "物品": "w3t",
            "技能": "w3a",
            "装饰物": "w3d",
            "可破坏物": "w3b",
        }[category],
        code,
        base or code,
        name or category + "名称",
        True,
    )


def _map(
    categories: tuple[str, ...],
    *,
    legacy_only: bool = False,
    identity_only: bool = False,
) -> MapData:
    md = MapData(path="read-only.w3x", name="类别导出")
    objects = [_obj(category) for category in categories]
    md.obj_index = {obj.obj_id: obj for obj in objects}
    if identity_only:
        md.obj_identity_index = {(obj.category, obj.obj_id): obj for obj in objects}
    elif not legacy_only:
        md.objects = {obj.category: [obj] for obj in objects}
    md.units = [Unit("X001", 0, 1.25, -2.5, 0.0, 0.0)]
    md.doodads = [Doodad("X001", 0, 1.25, -2.5, 0.0, 0.0)]
    return md


def _row(text: str) -> dict[str, str]:
    return next(csv.DictReader(StringIO(text), delimiter="\t"))


def test_script_placeholder_does_not_hide_a_real_category_definition() -> None:
    md = _map(("单位",))
    actual = md.objects["单位"][0]
    md.obj_identity_index[("单位", "X001")] = actual
    md.objects["单位"] = [GameObject("单位", "script", "X001", "", "错误占位", True)]
    row = _row(format_preplaced_units_tsv(md))
    assert row["名称"] == "单位名称" and row["分类"] == "单位"


def test_script_reference_alone_does_not_prove_a_placement_category() -> None:
    md = _map(("单位",))
    md.objects["单位"][0].ext = "script"
    row = _row(format_preplaced_units_tsv(md))
    assert row["名称"] == "X001" and not row["分类"] and row["分类诊断"]


def test_custom_unit_and_same_code_vanilla_item_remain_ambiguous() -> None:
    md = MapData(path="read-only.w3x", name="原版冲突")
    md.objects = {"单位": [_obj("单位", "ratf", name="自定义单位", base="Hpal")]}
    md.units = [Unit("ratf", 0, 1.25, -2.5, 0.0, 0.0)]
    row = _row(format_preplaced_units_tsv(md))
    assert row["名称"] == "ratf" and not row["分类"]
    assert all(category in row["分类诊断"] for category in ("单位", "物品"))


def test_foreign_base_never_supplies_placement_bilingual_metadata() -> None:
    md = _map(("单位",))
    md.objects["单位"][0].base_id = "AHhb"
    row = _row(format_preplaced_units_tsv(md))
    assert row["分类"] == "单位" and not row["英文名"] and not row["细类"]


def test_case_distinct_nested_codes_keep_their_own_names() -> None:
    md = _map(("单位", "物品"))
    md.objects["物品"].append(_obj("物品", "x001", name="小写物品"))
    md.units[0].items = [(0, "X001"), (1, "x001")]
    assert (
        _row(format_preplaced_units_tsv(md))["物品栏"]
        == "0:X001(物品名称); 1:x001(小写物品)"
    )


def test_export_name_cache_is_local_to_one_call() -> None:
    md = _map(("单位",))
    assert _row(format_preplaced_units_tsv(md))["名称"] == "单位名称"
    md.objects["单位"][0].name = "更新后的单位"
    assert _row(format_preplaced_units_tsv(md))["名称"] == "更新后的单位"


def test_live_pack_cache_version_retires_old_export_without_removing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool import live_cli

    source = tmp_path / "map.w3x"
    source.write_bytes(b"read-only-key-input")
    current = live_cli.live_pack_cache_dir(str(source))
    assert live_cli.LIVE_PACK_CACHE_VERSION == "live-pack-v34"
    previous_version = "live-pack-v" + str(
        int(live_cli.LIVE_PACK_CACHE_VERSION.rsplit("v", 1)[1]) - 1
    )
    monkeypatch.setattr(live_cli, "LIVE_PACK_CACHE_VERSION", previous_version)
    old = live_cli.live_pack_cache_dir(str(source))
    old.mkdir(parents=True, exist_ok=True)
    sentinel = old / "old-export.txt"
    sentinel.write_text("保留旧缓存", encoding="utf-8")
    assert current != old and sentinel.read_text(encoding="utf-8") == "保留旧缓存"


@pytest.mark.parametrize("category", ["单位", "物品", "可破坏物", "装饰物"])
@pytest.mark.parametrize("storage", ["objects", "identity", "legacy"])
def test_primary_names_use_the_matching_category_when_legacy_code_is_unrelated(
    category: str, storage: str
) -> None:
    md = _map(
        (category, "技能"),
        legacy_only=storage == "legacy",
        identity_only=storage == "identity",
    )
    if storage == "legacy":
        md.obj_index = {"X001": _obj(category)}
    formatter = (
        format_preplaced_units_tsv
        if category in ("单位", "物品")
        else format_preplaced_doodads_tsv
    )
    row = _row(formatter(md))
    assert row["名称"] == category + "名称" and row["分类"] == category
    assert not row["分类诊断"]


@pytest.mark.parametrize("identity_only", [False, True])
def test_inventory_abilities_and_drop_groups_resolve_their_own_categories(
    identity_only: bool,
) -> None:
    md = _map(
        ("单位", "物品", "技能", "可破坏物", "装饰物"), identity_only=identity_only
    )
    md.units[0].items = [(0, "X001")]
    md.units[0].abilities = [("X001", 1, 2)]
    drops = (DropSet(0, (DropEntry("X001", 70, 0, 0, 100),)),)
    md.units[0].drop_sets = drops
    md.doodads[0].drop_sets = drops
    unit, decor = (
        _row(format_preplaced_units_tsv(md)),
        _row(format_preplaced_doodads_tsv(md)),
    )
    assert unit["物品栏"] == "0:X001(物品名称)"
    assert unit["技能"] == "X001(技能名称):启用:2"
    assert unit["掉落"] == decor["掉落"] == "组1[X001(物品名称):70%]"


@pytest.mark.parametrize(
    "category,base", [("单位", "Hpal"), ("物品", "ratf"), ("技能", "AHhb")]
)
def test_known_custom_placement_metadata_uses_its_matching_base(
    category: str, base: str
) -> None:
    md = _map((category,))
    md.objects[category][0].base_id = base
    formatter = (
        format_preplaced_units_tsv
        if category in ("单位", "物品")
        else format_preplaced_doodads_tsv
    )
    row = _row(formatter(md))
    if category == "技能":
        assert row["名称"] == "X001" and not row["分类"]
        assert not row["英文名"] and not row["细类"] and row["分类诊断"]
    else:
        assert row["英文名"] == english_name_for(base)
        assert row["细类"] == fine_category_for(base)


@pytest.mark.parametrize("decor", [False, True])
def test_ambiguous_categories_keep_literal_identity_and_full_candidates(
    decor: bool,
) -> None:
    categories = ("装饰物", "可破坏物") if decor else ("单位", "物品")
    md = _map(categories)
    for obj in md.objects.values():
        obj[0].name += "完整" * 3000
    row = _row(
        (format_preplaced_doodads_tsv if decor else format_preplaced_units_tsv)(md)
    )
    assert row["名称"] == "X001" and row["分类"] == ""
    assert not row["英文名"] and not row["细类"]
    assert all(category in row["分类诊断"] for category in categories)
    assert all(obj[0].name in row["分类诊断"] for obj in md.objects.values())


def test_unrelated_vanilla_code_never_supplies_a_placement_name_or_metadata() -> None:
    md = MapData(path="read-only.w3x", name="原版同码")
    md.units = [Unit("AHhb", 0, 1.25, -2.5, 0.0, 0.0)]
    row = _row(format_preplaced_units_tsv(md))
    assert row["名称"] == "AHhb" and not row["分类"]
    assert not row["英文名"] and not row["细类"] and row["分类诊断"]


def test_missing_nested_category_keeps_the_literal_code() -> None:
    md = _map(("单位", "可破坏物"))
    md.units[0].items = [(0, "X001")]
    md.units[0].abilities = [("X001", 1, 2)]
    md.doodads[0].drops = [("X001", 100)]
    unit, decor = (
        _row(format_preplaced_units_tsv(md)),
        _row(format_preplaced_doodads_tsv(md)),
    )
    assert unit["物品栏"] == "0:X001(X001)"
    assert unit["技能"] == "X001(X001):启用:2"
    assert decor["掉落"] == "X001(X001):100%"


@pytest.mark.parametrize("decor", [False, True])
def test_export_query_round_trip_retains_unknown_category_and_coordinates(
    tmp_path: Path, decor: bool
) -> None:
    md = _map(("装饰物", "可破坏物") if decor else ("单位", "物品"))
    formatter, relative = (
        (format_preplaced_doodads_tsv, "预放置装饰物.tsv")
        if decor
        else (format_preplaced_units_tsv, "预放置单位.tsv")
    )
    (tmp_path / relative).write_text(formatter(md), encoding="utf-8")
    result = execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "1.25 -2.5 1")
    )
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 0 and len(data["entries"]) == 1
    assert data["entries"][0]["kind"] == "类别未确认"
    assert data["entries"][0]["positions"] == [[1.25, -2.5]]
    assert data["spatial_diagnostics"]


def test_all_nested_records_and_source_indexes_are_preserved() -> None:
    md = _map(("单位", "物品", "技能"))
    md.units[0].items = [(i, "X001") for i in range(2000)]
    md.units[0].abilities = [("X001", 1, i) for i in range(2000)]
    before = (
        dict(md.obj_index),
        dict(md.obj_identity_index),
        {cat: list(objects) for cat, objects in md.objects.items()},
    )
    row = _row(format_preplaced_units_tsv(md))
    assert row["物品栏"].split("; ") == [f"{i}:X001(物品名称)" for i in range(2000)]
    assert row["技能"].split("; ") == [f"X001(技能名称):启用:{i}" for i in range(2000)]
    assert (md.obj_index, md.obj_identity_index, md.objects) == before
