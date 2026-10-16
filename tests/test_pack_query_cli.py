# -*- coding: utf-8 -*-
"""pack-query 子命令：解析、加载器与端到端查询测试（合成资料包）。"""

from __future__ import annotations

import pytest

from w3xtool.pack_query_cli import (
    PackQueryCliOptionError,
    _base_prices,
    load_formulas,
    load_item_bases,
    load_item_equipped_effects,
    load_item_gold_overrides,
    load_items,
    load_item_tooltips,
    load_shop_stocks,
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
        "物品\tI0DD\t4\tratc\t攻击之爪+12样\t否\t无覆写走基础价\n"
        "物品\tI0EE\t5\tI0EE\t力量戒指SLK\t是\t材料\n"
        "物品\tI0P1\t6\tI0P1\t奖池甲\t是\t测试奖池物1\n"
        "物品\tI0P2\t7\tI0P2\t奖池乙\t是\t测试奖池物2\n",
        encoding="utf-8",
    )
    (obj / "单位.tsv").write_text(
        "单位\t四码\t数值\t四码2\t名称\n"
        "单位\tu0AA\t1\tu0AA\t雪妖\n"
        "单位\th0AA\t2\th0AA\t老伯基蓝\n"
        "单位\tnbos\t3\tnbos\t奖池怪\n",
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
    (tmp_path / "预放置单位.tsv").write_text(
        "序号\t类型ID\t名称\t玩家\tX\tY\tZ\n"
        "1\tu0AA\t雪妖\t敌对\t10.0\t20.0\t0\n"
        "2\th0AA\t老伯基蓝\t中立\t9000.0\t9000.0\t0\n",
        encoding="utf-8",
    )
    # 列位故意多一列(名称后带备注)，验证表头驱动而非固定列位
    (tmp_path / "预放置装饰物.tsv").write_text(
        "序号\t类型ID\t名称\t备注\tX\tY\tZ\n"
        "1\tD0ZZ\t测试阵\t圈\t12.0\t18.0\t0\n"
        "2\tD0ZZ\t测试阵\t圈\t14.0\t22.0\t0\n"
        "3\tD0ZZ\t测试阵\t圈\t8000.0\t8000.0\t0\n",
        encoding="utf-8",
    )
    (tmp_path / "掉落与获取关系.tsv").write_text(
        "hash\t地图\t类型\t四码\t名称\t来源类\t来源\n"
        "h1\t测试图\t脚本/触发奖励\tI0AA\t冰晶\t单位\tu0AA\n",
        encoding="utf-8",
    )
    (tmp_path / "对象字段.tsv").write_text(
        "物品\tI0CC\t攻击之爪+15样\tigol\t黄金\t123\twar3map.w3t\n"
        "物品\tI0AA\t冰晶\tigol\t黄金\t999\twar3map.w3t\n"
        + "物品\tI0BB\t雪白的熊掌\tgoldcost\t金币\t4500\twar3map *Data.slk\n"
        "物品\tI0AA\t冰晶\tiabi\t携带技能\tA0AA\twar3map.w3t\n"
        "技能\tA0AA\t力量\tIstr:1\t力量奖励 (等级1)\t11\twar3map.w3a\n"
        "技能\tA0AA\t力量\tbase:Istr:1\t力量奖励 (等级1)\t1\tbase:AIs1\n"
        "物品\tI0EE\t力量戒指SLK\tiabi\t携带技能\tA0AB\twar3map.w3t\n"
        "技能\tA0AB\t力量\tIstr1\t力量奖励 (等级1)\t7\twar3map *UnitData.slk\n"
        "单位\th0BB\t铁匠铺\tusei\t售出的物品\t冰晶(I0AA), I0CC\twar3map.w3u\n"
        "单位\th0BB\t铁匠铺\tbase:Sellitems\tSellitems\told1\tbase:nshe\n"
        "单位\tngme\t地精商店\tbase:Sellitems\tSellitems\tstwp, bspd\tbase:ngme\n"
        "科技\tR0AA\t改良伐木测试\tglvl\t等级数\t10\twar3map.w3q\n"
        "科技\tR0AA\t改良伐木测试\tglmb\t基础木材\t100\twar3map.w3q\n"
        "科技\tR0AA\t改良伐木测试\tglmm\t木材增量\t20\twar3map.w3q\n"
        "科技\tR0AA\t改良伐木测试\tgglm\t金币增量\t20\twar3map.w3q\n"
        "科技\tR0AA\t改良伐木测试\tgub1:1\t扩展提示 (等级1)\t每级+1木\twar3map.w3q\n"
        "科技\tR0AA\t改良伐木测试\tgub1:10\t扩展提示 (等级10)\t高级+2木\twar3map.w3q\n"
        "科技\tR0AA\t改良伐木测试\tgreq:1\t依赖科技 (等级1)\tR0A9\twar3map.w3q\n"
        "科技\tR0AA\t改良伐木测试\tbase:gglb\t基础金\t555\tbase:rhlh\n",
        encoding="utf-8",
    )
    (obj / "科技.tsv").write_text(
        "科技	四码	数值	四码2	名称	自定义	说明\n"
        "科技	R0AA	1	rhlh	改良伐木测试	是	说明\n",
        encoding="utf-8",
    )
    script_dir = tmp_path / "脚本可读文本"
    script_dir.mkdir()
    (script_dir / "war3map.j").write_text(
        "function Trig_ABCActions takes nothing returns nothing\r"
        "call KillUnit(GetTriggerUnit())\r"
        "endfunction\r"
        "function Trig_hgtConditions takes nothing returns boolean\r"
        "return true\r"
        "endfunction\r"
        "function Trig_hgtActions takes nothing returns nothing\r"
        "call PanCameraToTimedLocForPlayer(GetTriggerPlayer(), udg_fhd, 0.10)\r"
        "endfunction\r"
        "function InitTrig_ABC takes nothing returns nothing\r"
        "set gg_trg_ABC=CreateTrigger()\r"
        'call TriggerRegisterPlayerChatEvent(gg_trg_ABC, Player(1), "自杀", true)\r'
        'call TriggerRegisterPlayerChatEvent(gg_trg_ABC, Player(2), "自杀", true)\r'
        "call TriggerAddAction(gg_trg_ABC, function Trig_ABCActions)\r"
        "endfunction\r"
        "function InitTrig_hgt takes nothing returns nothing\r"
        "set gg_trg_hgt=CreateTrigger()\r"
        'call TriggerRegisterPlayerChatEvent(gg_trg_hgt, Player(1), "hg", false)\r'
        "call TriggerAddCondition(gg_trg_hgt, Condition(function Trig_hgtConditions))\r"
        "call TriggerAddAction(gg_trg_hgt, function Trig_hgtActions)\r"
        "endfunction\r"
        "function InitTrig_zst takes nothing returns nothing\r"
        "set gg_trg_zst=CreateTrigger()\r"
        'call TriggerRegisterPlayerChatEvent(gg_trg_zst, ConvertedPlayer(GetForLoopIndexA()), "-zs", true)\r'
        "call TriggerAddAction(gg_trg_zst, function Trig_ABCActions)\r"
        "endfunction\r"
        "function InitTrig_zoom takes nothing returns nothing\r"
        "set gg_trg_zoom=CreateTrigger()\r"
        'call TriggerRegisterPlayerChatEvent(gg_trg_zoom, Player(0), "-", true)\r'
        "call TriggerAddAction(gg_trg_zoom, function Trig_ABCActions)\r"
        "endfunction\r"
        "function Trig_poolConditions takes nothing returns boolean\r"
        "return ( ( GetUnitTypeId(GetDyingUnit()) == 'nbos' ) )\r"
        "endfunction\r"
        "function Trig_poolActions takes nothing returns nothing\r"
        "call SaveInteger(YDLOC, GetHandleId(GetTriggeringTrigger()), 0x34CF9D83, 100)\r"
        "if ( ( GetRandomInt(1, 100) <= LoadInteger(YDLOC, GetHandleId(GetTriggeringTrigger()), 0x34CF9D83) ) ) then\r"
        "set bj_lastPoolAbstractedItem=PlaceRandomItem((udg_WPool[2]), 0.0, 0.0)\r"
        "endif\r"
        "endfunction\r"
        "function InitTrig_pool takes nothing returns nothing\r"
        "set gg_trg_pool=CreateTrigger()\r"
        "call TriggerRegisterAnyUnitEventBJ(gg_trg_pool, EVENT_PLAYER_UNIT_DEATH)\r"
        "call TriggerAddCondition(gg_trg_pool, Condition(function Trig_poolConditions))\r"
        "call TriggerAddAction(gg_trg_pool, function Trig_poolActions)\r"
        "endfunction\r"
        "set gg_rct_testrect=Rect(- 5184.0, - 64.0, 4512.0, 64.0)\r"
        "set udg_WPool[2]=CreateItemPool()\r"
        "call ItemPoolAddItemType(udg_WPool[2], 'I0P1', 15.00)\r"
        "call ItemPoolAddItemType(udg_WPool[2], 'I0P2', 30.00)\r",
        encoding="utf-8",
    )
    ref_rows = [
        "来源\t行号\t函数\t对象码\t10进制\t分类\t名称\t对象来源\t上下文\t机制\t摘要\t英文名\t细类",
        "war3map.j\t10\tTrig_A\tIZYY\t1\t物品\t断链弓\ttxt\tObjectCode\tObjectCode\tcall UnitAddItemByIdSwapped('IZYY',GetTriggerUnit())\t\t",
        "war3map.j\t11\tTrig_A\tIZYY\t1\t物品\t断链弓\ttxt\tObjectCode\tObjectCode\tcall UnitAddItemToSlotById(gg_unit_X,'IZYY',1)\t\t",
        "war3map.j\t20\tTrig_B\tIZZZ\t1\t物品\t链上弓\ttxt\tObjectCode\tObjectCode\tcall UnitAddItemByIdSwapped('IZZZ',GetTriggerUnit())\t\t",
        "war3map.j\t21\tTrig_B\tIZZZ\t1\t物品\t链上弓\ttxt\tObjectCode\tObjectCode\tif((YDWEUnitHasItemOfTypeBJNull(GetTriggerUnit(),'IZZZ')==true))then\t\t",
        "war3map.j\t30\tCreateNeutralHostile\tu0ZZ\t1\t单位\t假英雄\ttxt\t赋值\t赋值\tset u=CreateUnit(p,'u0ZZ',1.0,2.0,0)\t\t",
        "war3map.j\t40\tYDWETimer\tEMPT\t1\t技能\t\ttxt\tObjectCode\tObjectCode\tset i=LoadInteger(YDHT,id,'EMPT')\t\t",
    ]
    (tmp_path / "脚本对象码出现索引.tsv").write_text(
        "\n".join(ref_rows) + "\n", encoding="utf-8"
    )
    (tmp_path / "脚本字符串索引.tsv").write_text(
        'war3map.j\t99\tTrig_xActions\tCreateQuestBJ\t字符串\t消失的玻璃球\t\tset udg=CreateQuestBJ(1, "消失的玻璃球", "找到老爷爷丢失的玻璃球")\n',
        encoding="utf-8",
    )
    return tmp_path


def test_parse_tech_command():
    o = parse_pack_query_cli_options(["pack", "tech", "R0AA"])
    assert (o.command, o.query) == ("tech", "R0AA")


def test_query_tech_sheet_custom_overrides_and_base_inherit(pack):
    from w3xtool.pack_query_cli import _query_tech, load_tech_fields, load_techs

    assert load_techs(pack)["R0AA"][0] == "改良伐木测试"
    assert load_tech_fields(pack)["R0AA"]["glvl"] == "10"
    assert "base:gglb" not in load_tech_fields(pack)["R0AA"]
    lines = _query_tech(pack, "R0AA", 20)
    text = "\n".join(lines)
    assert lines[0] == "[R0AA] 改良伐木测试  (基础: rhlh)"
    assert "最大等级: 10" in text
    # 金基数走 base_objects 继承(rhlh=100), 不吃 base: 行的 555
    assert "每级费用: 金 100+20/级, 木 100+20/级" in text
    assert "满级累计: 金1900 木1900" in text
    assert "效果(1级): 每级+1木" in text
    assert "效果(10级): 高级+2木" in text
    assert "前置: 1级←R0A9" in text
    assert _query_tech(pack, "zz不存在", 20) == ["未找到科技: zz不存在"]


def test_query_cmd_effect_chain(pack):
    from w3xtool.pack_query_cli import _query_cmd, load_script

    script = load_script(pack)
    assert script is not None and "\r" not in script
    lines = _query_cmd(pack, "自杀", 10)
    text = "\n".join(lines)
    assert '指令 "自杀" (精确, 注册2个玩家位) -> gg_trg_ABC' in text
    assert "KillUnit" in text
    hg = "\n".join(_query_cmd(pack, "hg", 10))
    assert '指令 "hg" (前缀' in hg
    assert "条件: function Trig_hgtConditions" in hg
    assert "PanCameraToTimedLocForPlayer" in hg
    assert _query_cmd(pack, "不存在zz", 10) == ["未找到聊天指令: 不存在zz"]


def test_parse_cmd_command():
    o = parse_pack_query_cli_options(["pack", "cmd", "自杀"])
    assert (o.command, o.query) == ("cmd", "自杀")


def test_query_refs_chain_termination_and_classification(pack):
    from w3xtool.pack_query_cli import _query_refs

    dead = "\n".join(_query_refs(pack, "IZYY", 10))
    assert "[IZYY] 断链弓  (物品)  共2处引用" in dead
    assert "给予/创建: 2 处" in dead
    assert "零消耗引用" in dead
    live = "\n".join(_query_refs(pack, "IZZZ", 10))
    assert "作为材料/触发媒介(被检测或移除): 1 处" in live
    assert "零消耗引用" not in live
    unit = "\n".join(_query_refs(pack, "假英雄", 10))
    assert "[u0ZZ] 假英雄  (单位)" in unit and "给予/创建: 1 处" in unit
    assert _query_refs(pack, "不存在zz", 10) == ["未找到引用: 不存在zz"]


def test_parse_refs_command():
    o = parse_pack_query_cli_options(["pack", "refs", "IZYY"])
    assert (o.command, o.query) == ("refs", "IZYY")


def test_query_cmd_exact_precedence_and_loop_registration(pack):
    from w3xtool.pack_query_cli import _query_cmd

    zs = "\n".join(_query_cmd(pack, "-zs", 10))
    assert '指令 "-zs" (精确' in zs
    assert '指令 "-"' not in zs
    dash = "\n".join(_query_cmd(pack, "-", 10))
    assert '指令 "-" (精确' in dash
    assert '指令 "-zs"' not in dash


def test_query_near_header_driven_and_rect_normalize(pack):
    from w3xtool.pack_query_cli import _query_near

    lines = _query_near(pack, "15 20 200", 10)
    text = "\n".join(lines)
    assert "== 坐标 (15, 20) 半径 200 ==" in text
    assert "单位: 雪妖 [u0AA] ×1 @(10,20) 距5" in text
    assert "装饰群: 测试阵 [D0ZZ] ×2 @(13,20)" in text
    assert "×3" not in text  # 8000,8000 那座不在半径内
    assert "所在矩形: gg_rct_testrect" in text  # 负号带空格归一后才含 (15,20)
    usage = _query_near(pack, "1", 10)
    assert usage[0].startswith("用法: near")
    bad = _query_near(pack, "a b", 10)
    assert bad[0].startswith("坐标与半径")


def test_query_drop_script_pool_fallback(pack):
    from w3xtool.pack_query_cli import _query_drop

    lines = _query_drop(pack, "nbos", 10)
    text = "\n".join(lines)
    assert "奖池怪 [nbos]  ⚠ 脚本死亡奖池" in text
    assert "必掉" in text
    assert "池 udg_WPool[2] 共2件" in text
    assert "奖池甲 [I0P1]  15/45  非卖品" in text
    assert "奖池乙 [I0P2]  30/45  非卖品" in text
    # 估值 vs 在售: goldcost 存在但无货架 → 估值+无货架 (连弩事故)
    (pack / "对象字段.tsv").write_text(
        (pack / "对象字段.tsv").read_text(encoding="utf-8")
        + "物品\tI0P1\t1\tgoldcost\tgoldcost\t450\tslk\n",
        encoding="utf-8",
    )
    re_run = "\n".join(_query_drop(pack, "奖池怪", 10))
    assert "奖池甲 [I0P1]  15/45  估值450金(无货架)" in re_run
    assert "奖池乙 [I0P2]  30/45  非卖品" in re_run
    # 名称推断的部位标注 (月光银狼池样例形态)
    from w3xtool.pack_query_cli import _item_slot_by_name

    assert _item_slot_by_name("狼牙链") == "饰品"
    assert _item_slot_by_name("月光手套") == "手部"
    assert _item_slot_by_name("纱布轻靴") == "脚部"
    assert _item_slot_by_name("白狼牙爪") == "武器"
    assert _item_slot_by_name("葵花宝典") == "书籍/杂物"
    assert _item_slot_by_name("无名物") == ""
    by_name = "\n".join(_query_drop(pack, "奖池怪", 10))
    assert "脚本死亡奖池" in by_name
    # 四字中文名不得被误当 fourcc (月光银狼事故)
    four_char = "\n".join(_query_drop(pack, "四字怪名", 10))
    assert "未找到获取途径: 四字怪名" in four_char
    assert _query_drop(pack, "zz不存在", 10) == ["未找到获取途径: zz不存在"]


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
    assert ov == {"I0AA": "999", "I0CC": "123", "I0BB": "4500"}


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
    assert "金币: 123 (地图价)" in out
    assert "金币: 500 (继承基础 ratc)" in out


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


def test_load_shop_stocks_parses_paren_codes(pack):
    stocks = load_shop_stocks(pack)
    # 自定义货架优先；仅有继承货架的原版商店也列出；同单位继承行被压制。
    assert stocks == [
        ("h0BB", "铁匠铺", ["I0AA", "I0CC"]),
        ("ngme", "地精商店", ["stwp", "bspd"]),
    ]


def test_run_cli_shop_query(pack, capsys):
    rc = run_pack_query_cli(parse_pack_query_cli_options([str(pack), "shop", "铁匠铺"]))
    out = capsys.readouterr().out
    assert rc == 0
    assert "冰晶" in out and "攻击之爪+15样" in out
    assert "999金" in out and "123金" in out and "地图价" in out


def test_run_cli_miss_returns_two(pack, capsys):
    rc = run_pack_query_cli(parse_pack_query_cli_options([str(pack), "item", "不存在"]))
    assert rc == 2
    assert "未找到" in capsys.readouterr().out


def test_run_cli_missing_pack(tmp_path, capsys):
    rc = run_pack_query_cli(
        parse_pack_query_cli_options([str(tmp_path / "x"), "item", "a"])
    )
    assert rc == 2


def test_load_item_equipped_effects_custom_over_base(pack):
    """装备效果取 iabi 技能的属性字段，自定义行(11)压过继承行(1)。"""
    effects = load_item_equipped_effects(pack)
    assert effects["I0AA"] == ["+11 力量"]


def test_load_item_equipped_effects_accepts_slk_level_suffix(pack):
    """SLK 导出的等级字段无冒号（Istr1），同样要解析出装备效果。"""
    effects = load_item_equipped_effects(pack)
    assert effects["I0EE"] == ["+7 力量"]


def test_run_cli_item_shows_equipped_effects(pack, capsys):
    rc = run_pack_query_cli(parse_pack_query_cli_options([str(pack), "item", "I0AA"]))
    out = capsys.readouterr().out
    assert rc == 0
    assert "装备效果: +11 力量" in out


def test_load_item_tooltips_prefers_ides(pack):
    """地图自定义 ides(描述) 优先于 utub(提示文本)，并剥离转义前缀单引号。"""
    (pack / "对象字段.tsv").write_text(
        "物品\tI0AA\t冰晶\tutub\t提示文本\t'utub兜底文本\twar3map.w3t\n"
        "物品\tI0AA\t冰晶\tides\t描述\t'ides真实提示\twar3map.w3t\n",
        encoding="utf-8",
    )
    tips = load_item_tooltips(pack)
    assert tips["I0AA"] == "ides真实提示"


def test_run_cli_item_prefers_real_tooltip(pack, capsys):
    """item 输出用地图真实提示文本；继承模板描述不再冒充真实效果。"""
    with (pack / "对象字段.tsv").open("a", encoding="utf-8") as f:
        f.write(
            "物品\tI0AA\t冰晶\tides\t描述\t'+5攻|n【冰·真】真实冻伤提示\twar3map.w3t\n"
        )
    rc = run_pack_query_cli(parse_pack_query_cli_options([str(pack), "item", "I0AA"]))
    out = capsys.readouterr().out
    assert rc == 0
    assert "真实冻伤提示" in out
    assert "减速" not in out  # 模板描述被真实提示取代


def test_load_item_gold_overrides_accepts_goldcost(pack):
    """SLK 系地图的金币字段键是 goldcost，必须与 igol 一样被识别为地图价。"""
    o = load_item_gold_overrides(pack)
    assert o.get("I0CC") == "123"  # igol 路径保持不变
    assert o.get("I0BB") == "4500"  # goldcost 路径（西方世界的劫难系）
