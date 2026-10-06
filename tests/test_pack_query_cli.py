# -*- coding: utf-8 -*-
"""pack-query 子命令：解析、加载器与端到端查询测试（合成资料包）。"""

from __future__ import annotations

import pytest

from w3xtool.pack_query_cli import (
    PackQueryCliOptionError,
    _base_prices,
    load_formulas,
    load_item_bases,
    load_item_gold_overrides,
    load_items,
    load_placements,
    parse_pack_query_cli_options,
    run_pack_query_cli,
)


@pytest.fixture()
def pack(tmp_path):
    obj = tmp_path / "对象ID"
    obj.mkdir()
    (obj / "物品.tsv").write_text(
        "物品\t四码\t数值\t四码2\t名称\t英雄\t描述\n"
        "物品\tI0AA\t1\tI0AA\t|cffff0000冰晶|r\t是\t'+10攻|n【冰】：减速\n"
        "物品\tI0BB\t2\tI0BB\t雪白的熊掌\t是\t材料\n"
        "物品\tI0CC\t3\tratf\t攻击之爪+15样\t否\t继承基础价\n"
        "物品\tI0DD\t4\tratc\t攻击之爪+12样\t否\t无覆写走基础价\n",
        encoding="utf-8",
    )
    (obj / "单位.tsv").write_text(
        "单位\t四码\t数值\t四码2\t名称\n"
        "单位\tu0AA\t1\tu0AA\t雪妖\n"
        "单位\th0AA\t2\th0AA\t老伯基蓝\n",
        encoding="utf-8",
    )
    (tmp_path / "脚本调用参数索引.tsv").write_text(
        "war3map.j\t1\tF\tcall\t1\t'x'\t\t\t\tcall YDWENewItemsFormula('I0BB', 4, 'ches', 0, 'I0AA')\n"
        "war3map.j\t5\tF\tcall\t1\t'x'\t\t\t\tcall YDWENewItemsFormula('I0BB', 4, 'ches', 0, 'I0AA')\n"
        "war3map.j\t2\tF\tCreateUnit\t1\tp\t\t\t普通参数\tset u=CreateUnit(p, 'u0AA', - 6144.0, 24320.0, 270.000)\n"
        "war3map.j\t3\tF\tCreateItem\t1\t'I0AA'\t\t\t对象码\tcall CreateItem('I0AA', - 7082.0, 25177.5)\n"
        "war3map.j\t4\tF\tCreateItemLoc\t1\t'I0BB'\t\t\t对象码\tcall CreateItemLoc('I0BB', GetRectCenter(gg_rct_x))\n",
        encoding="utf-8",
    )
    (tmp_path / "掉落与获取关系.tsv").write_text(
        "hash\t地图\t类型\t四码\t名称\t来源类\t来源\n"
        "h1\t测试图\t脚本/触发奖励\tI0AA\t冰晶\t单位\tu0AA\n",
        encoding="utf-8",
    )
    (tmp_path / "对象字段.tsv").write_text(
        "物品\tI0CC\t攻击之爪+15样\tigol\t黄金\t123\twar3map.w3t\n"
        "物品\tI0AA\t冰晶\tbase:金币\t金币\t999\tbase:I0AA\n",
        encoding="utf-8",
    )
    (tmp_path / "脚本字符串索引.tsv").write_text(
        'war3map.j\t99\tTrig_xActions\tCreateQuestBJ\t字符串\t消失的玻璃球\t\tset udg=CreateQuestBJ(1, "消失的玻璃球", "找到老爷爷丢失的玻璃球")\n',
        encoding="utf-8",
    )
    return tmp_path


def test_parse_ok():
    o = parse_pack_query_cli_options(["pack", "item", "冰晶"])
    assert (o.command, o.query, o.limit) == ("item", "冰晶", 20)
    o = parse_pack_query_cli_options(["pack", "text", "x", "--limit", "3"])
    assert o.limit == 3


def test_parse_errors():
    with pytest.raises(PackQueryCliOptionError):
        parse_pack_query_cli_options(["pack", "nope", "x"])
    with pytest.raises(PackQueryCliOptionError):
        parse_pack_query_cli_options(["pack", "item"])
    with pytest.raises(PackQueryCliOptionError):
        parse_pack_query_cli_options(["pack", "item", ""])
    with pytest.raises(PackQueryCliOptionError):
        parse_pack_query_cli_options(["pack", "item", "x", "--limit"])
    with pytest.raises(PackQueryCliOptionError):
        parse_pack_query_cli_options(["pack", "item", "x", "--limit", "0"])


def test_load_items_strips_colors(pack):
    items = load_items(pack)
    assert items["I0AA"][0] == "冰晶"
    assert "+10攻" in items["I0AA"][1]
    assert "|c" not in items["I0AA"][1]


def test_load_formulas_filters_fillers(pack):
    f = load_formulas(pack)
    assert f == [("I0AA", [("I0BB", 4)]), ("I0AA", [("I0BB", 4)])]


def test_load_placements_unit_and_ground_item(pack):
    p = sorted(load_placements(pack))
    assert ("I0AA", -7082.0, 25177.5, "item") in p
    assert ("u0AA", -6144.0, 24320.0, "unit") in p
    assert all(code != "I0BB" for code, _x, _y, _k in p)


def test_run_cli_item_query(pack, capsys):
    rc = run_pack_query_cli(parse_pack_query_cli_options([str(pack), "item", "I0AA"]))
    out = capsys.readouterr().out
    assert rc == 0
    assert "冰晶" in out and "减速" in out


def test_run_cli_recipe_by_material(pack, capsys):
    rc = run_pack_query_cli(parse_pack_query_cli_options([str(pack), "recipe", "熊掌"]))
    out = capsys.readouterr().out
    assert rc == 0
    assert "雪白的熊掌x4" in out and "冰晶" in out


def test_run_cli_where_and_drop_and_quest(pack, capsys):
    rc = run_pack_query_cli(parse_pack_query_cli_options([str(pack), "where", "雪妖"]))
    assert rc == 0 and "(-6144, 24320)" in capsys.readouterr().out
    rc = run_pack_query_cli(parse_pack_query_cli_options([str(pack), "drop", "冰晶"]))
    assert rc == 0 and "u0AA" in capsys.readouterr().out
    rc = run_pack_query_cli(
        parse_pack_query_cli_options([str(pack), "quest", "玻璃球"])
    )
    assert rc == 0 and "老爷爷" in capsys.readouterr().out


def test_run_cli_price_query(pack, capsys):
    rc = run_pack_query_cli(parse_pack_query_cli_options([str(pack), "price", "I0CC"]))
    out = capsys.readouterr().out
    assert rc == 0
    assert "金币: 123" in out and "地图价" in out and "ratf" in out


def test_load_item_gold_overrides(pack):
    ov = load_item_gold_overrides(pack)
    assert ov == {"I0CC": "123"}


def test_price_falls_back_to_base_without_override(pack, capsys):
    rc = run_pack_query_cli(parse_pack_query_cli_options([str(pack), "price", "I0DD"]))
    out = capsys.readouterr().out
    assert rc == 0
    assert "金币: 500" in out and "继承" in out


def test_run_cli_item_includes_price(pack, capsys):
    rc = run_pack_query_cli(
        parse_pack_query_cli_options([str(pack), "item", "攻击之爪"])
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "金币: 123 (地图价)" in out and "金币: 500" in out


def test_run_cli_price_base_code_direct(pack, capsys):
    rc = run_pack_query_cli(parse_pack_query_cli_options([str(pack), "price", "RATF"]))
    out = capsys.readouterr().out
    assert rc == 0
    assert "金币: 800" in out


def test_load_item_bases(pack):
    bases = load_item_bases(pack)
    assert bases["I0CC"] == "ratf"
    assert bases.get("I0AA", "") in ("", "i0aa")


def test_base_prices_has_known_entries():
    prices = _base_prices()
    assert prices.get("ratf") == "800"
    assert prices.get("ckng") is not None


def test_run_cli_recipe_dedupes(pack, capsys):
    rc = run_pack_query_cli(parse_pack_query_cli_options([str(pack), "recipe", "冰晶"]))
    out = capsys.readouterr().out
    assert rc == 0
    assert out.count("<-") == 1


def test_run_cli_miss_returns_two(pack, capsys):
    rc = run_pack_query_cli(parse_pack_query_cli_options([str(pack), "item", "不存在"]))
    assert rc == 2
    assert "未找到" in capsys.readouterr().out


def test_run_cli_missing_pack(tmp_path, capsys):
    rc = run_pack_query_cli(
        parse_pack_query_cli_options([str(tmp_path / "x"), "item", "a"])
    )
    assert rc == 2
