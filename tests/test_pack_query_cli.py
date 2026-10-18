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
        "物品\tI0P2\t7\tI0P2\t奖池乙\t是\t测试奖池物2\n"
"物品\tI01O\t8\tI01O\t钻石\t是\t直落\n"
"物品\tI01P\t9\tI01P\t猎刃\t是\t直落\n"
"物品\tI0G1\t10\tI0G1\t图腾石\t是\t直落\n"
"物品\tI0CT\t11\tI0CT\t掉落石\t是\tCreateItem直落\n"
"物品\tI0SH\t12\tI0SH\t上架货\t是\t上架商店\n"
"物品\tI0OL\t13\tI0OL\t独行石\t是\t动作体自判\n"
"物品\tI0CK\t14\tI0CK\t宝箱\t是\t使用触发\n"
"物品\tI0A1\t15\tI0A1\t宝物甲\t是\t数组池\n"
"物品\tI0A2\t16\tI0A2\t宝物乙\t是\t数组池\n"
"物品\tI0TK\t17\tI0TK\t凭证\t是\t拾取触发\n"
"物品\tI0PG\t18\tI0PG\t奖品\t是\t拾取产出\n"
"物品\tI0YD\t19\tI0YD\t死亡随机甲\t是\tYDWE模板\n"
"物品\tI0YE\t20\tI0YE\t死亡随机乙\t是\tYDWE模板\n"
"物品\tI0MA\t21\tI0MA\t复用甲\t是\t同函数复用\n"
"物品\tI0MB\t22\tI0MB\t复用乙\t是\t同函数复用\n",
        encoding="utf-8",
    )
    (obj / "单位.tsv").write_text(
        "单位\t四码\t数值\t四码2\t名称\n"
        "单位\tu0AA\t1\tu0AA\t雪妖\n"
        "单位\th0AA\t2\th0AA\t老伯基蓝\n"
        "单位\tnbos\t3\tnbos\t奖池怪\n"
"单位\tn018\t4\tn018\t炎石守卫\n"
"单位\tu00B\t5\tu00B\t样本怪\n"
"单位\tnen0\t6\tnen0\t样本图腾\n"
"单位\tnstk\t7\tnstk\t补货兽\n"
"单位\tnctm\t8\tnctm\t坐标怪\n"
"单位\tnshp\t9\tnshp\t上架怪\n"
"单位\tnonl\t10\tnonl\t独行怪\n",
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
        "2\th0AA\t老伯基蓝\t中立\t9000.0\t9000.0\t0\n"
        "3\tnctm\t坐标怪\t敌对\t500.0\t500.0\t0\n",
        encoding="utf-8",
    )
    # 列位故意多一列(名称后带备注)，验证表头驱动而非固定列位
    (tmp_path / "预放置装饰物.tsv").write_text(
        "序号\t类型ID\t名称\t备注\tX\tY\tZ\n"
        "1\tD0ZZ\t测试阵\t圈\t12.0\t18.0\t0\n"
        "2\tD0ZZ\t测试阵\t圈\t14.0\t22.0\t0\n"
        "3\tD0ZZ\t测试阵\t圈\t8000.0\t8000.0\t0\n"
        "4\tB007\t路障\t圈\t12.0\t18.0\t0\n",
        encoding="utf-8",
    )
    (tmp_path / "掉落与获取关系.tsv").write_text(
        "关系ID\t地图子图\t关系类型\t装备ID\t装备名称\t来源分类\t来源ID\t来源名称\t实例序号\t玩家\tX\tY\tZ\t掉落组\t组内序号\t概率\t槽位\t合成材料ID\t合成材料名称与数量\t证据文件\n"
        "h1\t测试图\t脚本/触发奖励\tI0AA\t冰晶\t单位\tu0AA\t雪妖\t\t\t\t\t\t\t\t\t\t\t\t\tw3x\n"
        "h2\t测试图\t合成\tI0P2\t奖池乙\t配方\t\t配方桌\t\t\t\t\t\t\t\t\tI0P1\tx2\t\tw3x\n"
        "h3\t测试图\t商店制造\tI0P1\t奖池甲\t单位\th0ZZ\t铁匠铺\t\t\t\t\t\t\t\t\t\t\t\tw3x\n"
        "h4\t测试图\t可破坏物掉落\tI0G1\t图腾石\t可破坏物\tB007\t路障\t\t\t\t\t\t\t\t\t\t\t\tw3x\n"
        "h5\t测试图\t合成\tI0G1\t图腾石\t配方\t\t配方桌\t\t\t\t\t\t\t\t\t\tI0CK;I0A1\t凭证×1;宝物甲×2\tw3x\n"
        "h6\t测试图\t商店出售\tI0A1\t宝物甲\t单位\th0YM\t银月配方商\t\t\t\t\t\t\t\t\t\t\t\tw3x\n"
        "h8\t测试图\t脚本/触发奖励\tI0QT\t任务剑"
        + "\t" * 15
        + "war3map.j\tTrig_questActions\t行 100\tcall UnitAddItemByIdSwapped('I0QT',udg_LMS)\t已确认\t已确认\n",
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
        "function InitTrig_any takes nothing returns nothing\r"
        "set gg_trg_any=CreateTrigger()\r"
        'call TriggerRegisterPlayerChatEvent(gg_trg_any, Player(0), "", false)\r'
        "endfunction\r"
        "function InitTrig_secret takes nothing returns nothing\r"
        "local trigger t = CreateTrigger()\r"
        'call TriggerRegisterPlayerChatEvent(t, Player(0), "secret", true)\r'
        "call TriggerAddAction(t, function Trig_secretActions)\r"
        "endfunction\r"
        "function Trig_secretActions takes nothing returns nothing\r"
        "call DoNothing()\r"
        "endfunction\r"
        "function InitTrig_otherLocal takes nothing returns nothing\r"
        "local trigger t = CreateTrigger()\r"
        'call TriggerRegisterPlayerChatEvent(t, Player(0), "", false)\r'
        "call TriggerAddAction(t, function Trig_unrelatedActions)\r"
        "endfunction\r"
        "function Trig_unrelatedActions takes nothing returns nothing\r"
        "call DoNothing()\r"
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
        "call ItemPoolAddItemType(udg_WPool[2], 'I0P2', 30.00)\r"
        "function Trig_bossConditions takes nothing returns boolean\r"
        "return((GetOwningPlayer(GetDyingUnit())==Player(10)))\r"
        "endfunction\r"
        "function Trig_bossActions takes nothing returns nothing\r"
        "if((GetUnitTypeId(GetDyingUnit())=='nbld'))then\r"
        "set udg_WPP[3]=GetUnitLoc(GetDyingUnit())\r"
        "call CreateItemLoc('I0P3',udg_WPP[3])\r"
        "call RemoveLocation(udg_WPP[3])\r"
        "if((GetRandomReal(1.00,1.70)<=(1.00+(1.00*(udg_DYZS[1]*0.01)))))then\r"
        "set udg_WPP[4]=GetUnitLoc(GetDyingUnit())\r"
        "call CreateItemLoc('I0P4',udg_WPP[4])\r"
        "call RemoveLocation(udg_WPP[4])\r"
        "else\r"
        "endif\r"
        "else\r"
        "endif\r"
        "endfunction\r"
        "function InitTrig_boss takes nothing returns nothing\r"
        "set gg_trg_boss=CreateTrigger()\r"
        "call TriggerRegisterAnyUnitEventBJ(gg_trg_boss, EVENT_PLAYER_UNIT_DEATH)\r"
        "call TriggerAddCondition(gg_trg_boss, Condition(function Trig_bossConditions))\r"
        "call TriggerAddAction(gg_trg_boss, function Trig_bossActions)\r"
        "endfunction\r"
        "function Trig_hexConditions takes nothing returns boolean\r"
        "return GetUnitTypeId(GetDyingUnit())==$6e303138\r"
        "endfunction\r"
        "function Trig_hexActions takes nothing returns nothing\r"
        "call CreateItemLoc($4930314f,GetUnitLoc(GetDyingUnit()))\r"
        "endfunction\r"
        "function Trig_hndConditions takes nothing returns boolean\r"
        "return GetDyingUnit()==udg_HX\r"
        "endfunction\r"
        "function Trig_hndActions takes nothing returns nothing\r"
        "call UnitAddItemByIdSwapped($49303150,GetKillingUnitBJ())\r"
        "endfunction\r"
        "function Trig_gguConditions takes nothing returns boolean\r"
        "return gg_unit_nen0_0001==GetDyingUnit()\r"
        "endfunction\r"
        "function Trig_gguActions takes nothing returns nothing\r"
        "call UnitAddItemByIdSwapped('I0G1',GetKillingUnitBJ())\r"
        "endfunction\r"
        "function Trig_stkConditions takes nothing returns boolean\r"
        "return GetUnitTypeId(GetDyingUnit())=='nstk'\r"
        "endfunction\r"
        "function Trig_stkActions takes nothing returns nothing\r"
        "call AddItemToStockBJ(ChooseRandomItemExBJ(6,ITEM_TYPE_ANY),gg_unit_n000_0001,0,0)\r"
        "endfunction\r"
        "function Trig_ctmConditions takes nothing returns boolean\r"
        "return GetUnitTypeId(GetDyingUnit())=='nctm'\r"
        "endfunction\r"
        "function Trig_ctmActions takes nothing returns nothing\r"
        "call CreateItem('I0CT',100.0,200.0)\r"
        "endfunction\r"
        "function Trig_shpConditions takes nothing returns boolean\r"
        "return GetUnitTypeId(GetDyingUnit())=='nshp'\r"
        "endfunction\r"
        "function Trig_shpActions takes nothing returns nothing\r"
        "call AddItemToStockBJ('I0SH',gg_unit_n000_0001,0,0)\r"
        "endfunction\r"
        "function Trig_onlyActions takes nothing returns nothing\r"
        "if((GetUnitTypeId(GetDyingUnit())=='nonl'))then\r"
        "call CreateItemLoc('I0OL',GetUnitLoc(GetDyingUnit()))\r"
        "endif\r"
        "endfunction\r"
        "function Trig_useConditions takes nothing returns boolean\r"
        "return GetItemTypeId(GetManipulatedItem())=='I0CK'\r"
        "endfunction\r"
        "function Trig_useActions takes nothing returns nothing\r"
        "call ItemPoolAddItemType(LoadItemPoolHandle(YDLOC,GetHandleId(GetTriggeringTrigger()),$1290C38A),udg_ZBS[GetRandomInt(1,2)],1)\r"
        "endfunction\r"
        "function InitTrig_use takes nothing returns nothing\r"
        "set gg_trg_use=CreateTrigger()\r"
        "call TriggerAddCondition(gg_trg_use, Condition(function Trig_useConditions))\r"
        "call TriggerAddAction(gg_trg_use, function Trig_useActions)\r"
        "endfunction\r"
        "function Trig_useLocalConditions takes nothing returns boolean\r"
        "return GetItemTypeId(GetManipulatedItem())=='I0LV'\r"
        "endfunction\r"
        "function Trig_useLocalActions takes nothing returns nothing\r"
        "call CreateItem('I0LV',GetUnitX(GetTriggerUnit()),GetUnitY(GetTriggerUnit()))\r"
        "endfunction\r"
        "function InitTrig_useLocal takes nothing returns nothing\r"
        "local trigger t = CreateTrigger()\r"
        "call TriggerRegisterPlayerUnitEventSimple(t,Player(0),EVENT_PLAYER_UNIT_USE_ITEM)\r"
        "call TriggerAddCondition(t, Condition(function Trig_useLocalConditions))\r"
        "call TriggerAddAction(t, function Trig_useLocalActions)\r"
        "endfunction\r"
        "function InitTrig_decoy takes nothing returns nothing\r"
        "local trigger t = CreateTrigger()\r"
        "call TriggerAddAction(t, function Trig_decoyActions)\r"
        "endfunction\r"
        "function Trig_decoyActions takes nothing returns nothing\r"
        "call DoNothing()\r"
        "endfunction\r"
        "set udg_ZBS[1]='I0A1'\r"
        "set udg_ZBS[2]='I0A2'\r"
        "function Trig_pickConditions takes nothing returns boolean\r"
        "return GetItemTypeId(GetManipulatedItem())=='I0TK'\r"
        "endfunction\r"
        "function Trig_pickActions takes nothing returns nothing\r"
        "if((GetRandomInt(1,300)<=150))then\r"
        "call UnitAddItemByIdSwapped('I0PG',GetManipulatingUnit())\r"
        "endif\r"
        "endfunction\r"
        "function InitTrig_pick takes nothing returns nothing\r"
        "set gg_trg_pick=CreateTrigger()\r"
        "call TriggerRegisterPlayerUnitEventSimple(gg_trg_pick,Player(0),EVENT_PLAYER_UNIT_PICKUP_ITEM)\r"
        "call TriggerAddCondition(gg_trg_pick, Condition(function Trig_pickConditions))\r"
        "call TriggerAddAction(gg_trg_pick, function Trig_pickActions)\r"
        "endfunction\r"
        "function Unit_ydweDropItems takes nothing returns nothing\r"
        "call RandomDistReset()\r"
        "call RandomDistAddItem('I0YD', 70)\r"
        "call RandomDistAddItem('I0YE', 30)\r"
        "call UnitDropItem(GetTriggerUnit(), RandomDistChoose())\r"
        "endfunction\r"
        "function InitTrig_ydweDrop takes nothing returns nothing\r"
        "local unit u=null\r"
        "local trigger t=null\r"
        "set u=CreateUnit(Player(0),'nctm',0.0,0.0,0.0)\r"
        "set t=CreateTrigger()\r"
        "call TriggerRegisterUnitEvent(t,u,EVENT_UNIT_DEATH)\r"
        "call TriggerAddAction(t,function Unit_ydweDropItems)\r"
        "endfunction\r"
        "function Trig_multiAConditions takes nothing returns boolean\r"
        "return GetItemTypeId(GetManipulatedItem())=='I0MA'\r"
        "endfunction\r"
        "function Trig_multiAActions takes nothing returns nothing\r"
        "call CreateItem('I0MA',GetUnitX(GetTriggerUnit()),GetUnitY(GetTriggerUnit()))\r"
        "endfunction\r"
        "function Trig_multiBConditions takes nothing returns boolean\r"
        "return GetItemTypeId(GetManipulatedItem())=='I0MB'\r"
        "endfunction\r"
        "function Trig_multiBActions takes nothing returns nothing\r"
        "call CreateItem('I0MB',GetUnitX(GetTriggerUnit()),GetUnitY(GetTriggerUnit()))\r"
        "endfunction\r"
        "function InitTrig_multi takes nothing returns nothing\r"
        "local trigger t=null\r"
        "set t=CreateTrigger()\r"
        "call TriggerRegisterPlayerUnitEventSimple(t,Player(0),EVENT_PLAYER_UNIT_USE_ITEM)\r"
        "call TriggerAddCondition(t, Condition(function Trig_multiAConditions))\r"
        "call TriggerAddAction(t, function Trig_multiAActions)\r"
        "set t=CreateTrigger()\r"
        "call TriggerRegisterPlayerUnitEventSimple(t,Player(0),EVENT_PLAYER_UNIT_PICKUP_ITEM)\r"
        "call TriggerAddCondition(t, Condition(function Trig_multiBConditions))\r"
        "call TriggerAddAction(t, function Trig_multiBActions)\r"
        "endfunction\r"
        "set udg_HX=CreateUnit(Player(11),$75303042,0.0,0.0,0.0)\r",
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
    miss = _query_cmd(pack, "不存在zz", 10)
    # 图里有空串聊天事件时必须如实说明 (不能只答「未找到」)
    assert miss[0] == "⚠ 未找到具名聊天指令: 不存在zz"
    assert "空串聊天事件" in miss[1]


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


def test_unit_death_random_dist_drops(pack):
    # YDWE 每单位死亡模板: bj_lastDyingWidget + RandomDistAddItem, 动作体既无
    # GetDyingUnit() 也无 CreateItem 调用——旧两种死亡形态都扫不到
    from w3xtool.pack_query_cli import (
        _query_drop,
        _unit_death_random_drops,
        load_script,
    )

    handlers = {
        fn: regs
        for _code, fn, regs in _unit_death_random_drops(load_script(pack))
    }
    assert handlers["Unit_ydweDropItems"] == [("I0YD", 70), ("I0YE", 30)]
    unit_text = "\n".join(_query_drop(pack, "nctm", 30))
    assert "Unit_ydweDropItems" in unit_text
    assert "I0YD" in unit_text and "I0YE" in unit_text
    item_text = "\n".join(_query_drop(pack, "I0YD", 30))
    assert "死亡随机掉落" in item_text
    assert "nctm" in item_text and "Unit_ydweDropItems" in item_text
    # guide drops 段与 pack-query 同源: 第三形态同样进入玩家报告
    from w3xtool.pack_query_cli import script_death_drop_lines

    guide_text = "\n".join(
        script_death_drop_lines(load_script(pack), lambda c: c)
    )
    assert "Unit_ydweDropItems" in guide_text
    assert "权重70/100" in guide_text
    # where 与 drop 同源: 物品获取途径同样能看到第三形态
    from w3xtool.pack_query_cli import _query_where

    where_text = "\n".join(_query_where(pack, "I0YD", 30))
    assert "死亡随机掉落" in where_text


def test_item_trigger_blocks_scope_local_vars(pack):
    # 局部 trigger t 跨函数重名: 条件/动作必须按注册所在函数配对,
    # 否则 I0LV 的使用触发器会配到 decoy 的动作体 (假证据)
    from w3xtool.pack_query_cli import _item_trigger_blocks, load_script

    blocks = _item_trigger_blocks(load_script(pack))
    hit = [b for b in blocks if "I0LV" in b[1]]
    assert hit, "I0LV 使用触发器未进入块列表"
    body = hit[0][2]
    assert "CreateItem" in body and "I0LV" in body
    assert "DoNothing" not in body


def test_query_where_script_award_shows_evidence_source(pack):
    # 脚本奖励行没有来源对象: 展示证据函数/行号, 而不是 "来源 []";
    # 且空来源不得因 "" in query 恒真而出现在任何查询里
    from w3xtool.pack_query_cli import _query_where

    text = "\n".join(_query_where(pack, "I0QT", 50))
    assert "脚本/触发奖励 <- Trig_questActions 行 100" in text
    other = "\n".join(_query_where(pack, "I0A1", 50))
    assert "I0QT" not in other
    assert "来源 []" not in other


def test_query_cmd_scopes_local_trigger_handlers(pack):
    # 局部 trigger 变量在多个函数里重名: 处理器必须按注册所在函数配对,
    # 全脚本按变量名配对会把无关函数当动作 (YDWE Version 事故回归)
    from w3xtool.pack_query_cli import _query_cmd

    text = "\n".join(_query_cmd(pack, "secret", 10))
    assert '指令 "secret" (精确' in text
    assert "-> t" in text
    assert "注册函数: InitTrig_secret" in text
    assert "动作: function Trig_secretActions" in text
    assert "Trig_unrelatedActions" not in text


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
    # 有货架 → 逐店标注; 同名异码 → 价随码警告 (多店不同价事故)
    (pack / "对象字段.tsv").write_text(
        (pack / "对象字段.tsv").read_text(encoding="utf-8")
        + "物品\tI0P1\t1\tgoldcost\tgoldcost\t450\tslk\n"
        + "物品\tI0P2\t1\tgoldcost\tgoldcost\t600\tslk\n"
        + "单位\th0ZZ\t杂货铺\tSellitems\tusei\tI0P1, I0P2\tunits\n"
        + "单位\th0ZY\t黑店\tusei\tusei\tI0P2\tunits\n",
        encoding="utf-8",
    )
    item_tsv = pack / "对象ID" / "物品.tsv"
    item_tsv.write_text(
        item_tsv.read_text(encoding="utf-8")
        + "物品\tI0Q9\t9\tI0Q9\t奖池甲\t是\t同名异码测试\n",
        encoding="utf-8",
    )
    re_run = "\n".join(_query_drop(pack, "奖池怪", 10))
    assert (
        "奖池甲 [I0P1]  15/45  在售450金@杂货铺·商店制造@铁匠铺·同名异码价随码·身体(名推断)"
        in re_run
    )
    assert "奖池乙 [I0P2]  30/45  600金@杂货铺/黑店·可合成" in re_run
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


def test_query_drop_script_direct_death_drop(pack):
    from w3xtool.pack_query_cli import _query_drop

    item_tsv = pack / "对象ID" / "物品.tsv"
    item_tsv.write_text(
        item_tsv.read_text(encoding="utf-8")
        + "物品\tI0P3\t3\tI0P3\t直落木剑\t是\t说明\n"
        + "物品\tI0P4\t4\tI0P4\t运势木剑\t是\t说明\n",
        encoding="utf-8",
    )
    # I0P3: 死亡位置直落, 本语句之前无掷骰; 动作体内层 if 判定死亡单位 nbld
    unit_tsv = pack / "对象ID" / "单位.tsv"
    unit_tsv.write_text(
        unit_tsv.read_text(encoding="utf-8")
        + "单位\tnbld\t4\tnbld\t炎石小怪\n",
        encoding="utf-8",
    )
    text = "\n".join(_query_drop(pack, "I0P3", 10))
    assert "直落木剑 [I0P3]  ⚠ 脚本死亡位置直落 (关系表无此掉落记录):" in text
    assert (
        "死亡触发 Trig_boss -> 死亡直落语句: call CreateItemLoc('I0P3',udg_WPP[3])"
        in text
    )
    assert "死亡单位判定: 炎石小怪 [nbld]" in text
    assert "同函数掷骰: 无(本语句之前)" in text
    assert "死亡条件 Trig_bossConditions: return((GetOwningPlayer(GetDyingUnit())==Player(10)))" in text
    # I0P4: 同函数掷骰门槛如实列出, 不写保底配方
    gate = "\n".join(_query_drop(pack, "I0P4", 10))
    assert "运势木剑 [I0P4]  ⚠ 脚本死亡位置直落" in gate
    assert "CreateItemLoc('I0P4',udg_WPP[4])" in gate
    assert "同函数掷骰: GetRandomReal(1.00,1.70) (门槛是否套用本物品以函数体为准)" in gate


def test_query_drop_relation_row_without_drop_kind_gets_script_evidence(pack):
    # I01F 事故形态: 关系表有"脚本/触发奖励"行 (来源为空), 兜底原本不触发,
    # 防呆横幅误称"无死亡掉落记录"——现在缺掉落类型也跑死亡扫描并附证据
    from w3xtool.pack_query_cli import _query_drop

    (pack / "掉落与获取关系.tsv").write_text(
        "对象\t名称\t关系类型\t对象ID\t装备名称\t来源类型\t来源名称\n"
        + "物品\tI0P3\t脚本/触发奖励\tI0P3\t直落木剑\t脚本\t\n"
        + "物品\tI0BB\t脚本/触发奖励\tI0BB\t冰晶\t脚本\t\n",
        encoding="utf-8",
    )
    item_tsv = pack / "对象ID" / "物品.tsv"
    item_tsv.write_text(
        item_tsv.read_text(encoding="utf-8")
        + "物品\tI0P3\t3\tI0P3\t直落木剑\t是\t说明\n",
        encoding="utf-8",
    )
    hit = "\n".join(_query_drop(pack, "I0P3", 10))
    assert "直落木剑 [I0P3]  脚本/触发奖励" in hit
    assert "关系表无 Boss/单位死亡掉落行, 但脚本死亡触发有直发证据" in hit
    assert "⚠ 脚本死亡位置直落" in hit
    assert "CreateItemLoc('I0P3',udg_WPP[3])" in hit
    # 无死亡触发证据 → 保留旧防呆措辞 (不得断言打怪掉落)
    miss = "\n".join(_query_drop(pack, "I0BB", 10))
    assert "冰晶 [I0BB]  脚本/触发奖励" in miss
    assert "不得断言打怪掉落" in miss
    assert "脚本死亡位置直落" not in miss


def test_query_drop_item_name_resolves_death_evidence(pack):
    # I01F 按名查询事故: 单位名无匹配时回退到物品名解析再扫死亡触发
    from w3xtool.pack_query_cli import _query_drop

    item_tsv = pack / "对象ID" / "物品.tsv"
    item_tsv.write_text(
        item_tsv.read_text(encoding="utf-8")
        + "物品\tI0P3\t3\tI0P3\t直落木剑\t是\t说明\n",
        encoding="utf-8",
    )
    text = "\n".join(_query_drop(pack, "直落木剑", 10))
    assert "⚠ 脚本死亡位置直落" in text
    assert "CreateItemLoc('I0P3',udg_WPP[3])" in text
    # 完全未知名 → 依旧两行负输出
    assert _query_drop(pack, "zz不存在", 10) == ["未找到获取途径: zz不存在"]


def test_query_where_falls_back_to_relation_rows(pack):
    # I01F 事故形态: 任务物品无预放置点, 关系行存在却被 where 跳过,
    # 文案兜底按描述子串错配到别的物品——现在补查关系表
    from w3xtool.pack_query_cli import _query_where

    (pack / "掉落与获取关系.tsv").write_text(
        "对象\t名称\t关系类型\t对象ID\t装备名称\t来源类型\t来源名称\n"
        + "物品\tI0P3\t脚本/触发奖励\tI0P3\t直落木剑\t脚本\t死亡触发\n",
        encoding="utf-8",
    )
    item_tsv = pack / "对象ID" / "物品.tsv"
    item_tsv.write_text(
        item_tsv.read_text(encoding="utf-8")
        + "物品\tI0P3\t3\tI0P3\t直落木剑\t是\t说明\n",
        encoding="utf-8",
    )
    text = "\n".join(_query_where(pack, "直落木剑", 10))
    assert "直落木剑 [I0P3]  脚本/触发奖励 <- 脚本 死亡触发" in text
    # 文案兜底不再抢跑 (关系行命中后不出现文案线索头)
    assert "文案级来源线索" not in text
    # 四码直查同样命中关系行
    by_code = "\n".join(_query_where(pack, "I0P3", 10))
    assert "直落木剑 [I0P3]  脚本/触发奖励" in by_code
    # 既有预放置又有关系行 → 两类证据都给 (满量, 不静默吞)
    (pack / "掉落与获取关系.tsv").write_text(
        "对象\t名称\t关系类型\t对象ID\t装备名称\t来源类型\t来源名称\n"
        + "物品\tI0P3\t脚本/触发奖励\tI0P3\t雪妖皮草\t脚本\t死亡触发\n",
        encoding="utf-8",
    )
    both = "\n".join(_query_where(pack, "雪妖", 10))
    assert "[u0AA] 雪妖 (单位) -> (-6144, 24320)" in both
    assert "雪妖皮草 [I0P3]  脚本/触发奖励" in both


def test_query_drop_unit_name_reverse_lists_direct_drops(pack):
    # 「打 X 掉什么」按单位名问: 物品维度直落扫描匹配 CreateItemLoc
    # 物品参数, 反不进去——需按单位码反查死亡触发, 满量列直落清单
    from w3xtool.pack_query_cli import _query_drop

    unit_tsv = pack / "对象ID" / "单位.tsv"
    unit_tsv.write_text(
        unit_tsv.read_text(encoding="utf-8")
        + "单位\tnbld\t4\tnbld\t炎石小怪\n",
        encoding="utf-8",
    )
    item_tsv = pack / "对象ID" / "物品.tsv"
    item_tsv.write_text(
        item_tsv.read_text(encoding="utf-8")
        + "物品\tI0P3\t3\tI0P3\t直落木剑\t是\t说明\n"
        + "物品\tI0P4\t4\tI0P4\t运势木剑\t是\t说明\n",
        encoding="utf-8",
    )
    text = "\n".join(_query_drop(pack, "炎石小怪", 10))
    assert "炎石小怪 [nbld]  ⚠ 按单位反查死亡直落 (该单位死亡触发创建的物品):" in text
    assert "死亡条件 Trig_bossConditions: return((GetOwningPlayer(GetDyingUnit())==Player(10)))" in text
    assert "直落: 直落木剑 [I0P3]" in text
    assert "直落: 运势木剑 [I0P4]" in text
    assert "同函数掷骰: 无(本语句之前)" in text
    assert "同函数掷骰: GetRandomReal(1.00,1.70)" in text
    # 直接敲单位四码走 ASCII 候选路径, 同样按单位表归属触发反查
    by_code = "\n".join(_query_drop(pack, "nbld", 10))
    assert "按单位反查死亡直落" in by_code
    assert "直落: 直落木剑 [I0P3]" in by_code


def test_query_fallbacks_route_unit_queries(pack):
    # 单位查询两层全空时路由指引, 不再吃物品文案兜底
    # (邪恶陨石人的任务文本曾被端出来当「炎石守卫」的来源线索);
    # 用无触发器引用的单位——nbld 会被反查清单优先命中, 轮不到路由
    from w3xtool.pack_query_cli import _query_drop, _query_where

    unit_tsv = pack / "对象ID" / "单位.tsv"
    unit_tsv.write_text(
        unit_tsv.read_text(encoding="utf-8")
        + "单位\tnrte\t4\tnrte\t路由怪\n",
        encoding="utf-8",
    )
    where_text = "\n".join(_query_where(pack, "路由怪", 10))
    assert "未找到 [nrte] 路由怪 的预放置/关系表记录。" in where_text
    assert "单位掉落查询用 drop <单位名或码>" in where_text
    assert "文案级来源线索" not in where_text
    drop_text = "\n".join(_query_drop(pack, "路由怪", 10))
    assert "无死亡触发直落/奖池证据" in drop_text
    assert "位置/获取查询用 where <词>" in drop_text
    assert "文案级" not in drop_text


def test_query_drop_hex_and_handle_death_codes(pack):
    # YDWE 把四码编成整数 ($6e303138 = 'n018'), 死亡判定也常走句柄比较
    # (GetDyingUnit()==udg_X 或 gg_unit_码_序号==GetDyingUnit())——
    # 四码归一与句柄解析让三类写法都进扫描族。
    from w3xtool.pack_query_cli import _query_drop

    hex_text = "\n".join(_query_drop(pack, "n018", 20))
    assert "炎石守卫 [n018]" in hex_text
    assert "钻石" in hex_text
    var_text = "\n".join(_query_drop(pack, "u00B", 20))
    assert "样本怪 [u00B]" in var_text
    assert "猎刃" in var_text
    ggu_text = "\n".join(_query_drop(pack, "nen0", 20))
    assert "样本图腾 [nen0]" in ggu_text
    assert "图腾石" in ggu_text


def test_query_drop_random_stock_evidence(pack):
    # 死亡触发不产固定物品、只给商店随机补货时, 报机制而不是「无证据」
    # (迷失国度 drs 死亡触发 ChooseRandomItemExBJ 随机上架即此类)。
    from w3xtool.pack_query_cli import _query_drop

    text = "\n".join(_query_drop(pack, "nstk", 20))
    assert "补货兽 [nstk]  ⚠ 按单位反查死亡触发 (无固定掉落, 见运行时随机):" in text
    assert "随机补货: ChooseRandomItemExBJ(6, ITEM_TYPE_ANY)" in text


def test_query_drop_createitem_and_stock_evidence(pack):
    # 死亡直落的第三种写法 CreateItem(码,x,y) 与「指定物品上架商店」
    # 都是真数据结构 (hxsj Trig_ZZ2 的 CreateItem('I07H',..) 曾被扫空)。
    from w3xtool.pack_query_cli import _query_drop

    ctm = "\n".join(_query_drop(pack, "nctm", 20))
    assert "坐标怪 [nctm]" in ctm
    assert "掉落石 [I0CT]" in ctm
    assert "call CreateItem('I0CT',100.0,200.0)" in ctm
    shp = "\n".join(_query_drop(pack, "nshp", 20))
    assert "上架怪 [nshp]" in shp
    assert "上架商店: 上架货 [I0SH]" in shp


def test_query_drop_action_only_death_handler(pack):
    # 无独立 Conditions 函数的死亡处理 (判定写在 action 里) 也要被扫到
    # ——hxsj Trig_____________ZZ2Actions 即此形态, CreateItem 曾被整类漏扫。
    from w3xtool.pack_query_cli import _query_drop

    text = "\n".join(_query_drop(pack, "nonl", 20))
    assert "独行怪 [nonl]" in text
    assert "独行石 [I0OL]" in text
    assert "死亡处理函数 Trig_onlyActions (动作体内判定)" in text


def test_query_where_use_item_array_pool(pack):
    # 使用物品触发的数组池随机产出 (宝箱开箱): 数组内容静态全解,
    # 迷失国度 wbc 系统 45/10/10/27 件四池即此法首次全量浮出。
    from w3xtool.pack_query_cli import _query_where

    text = "\n".join(_query_where(pack, "I0CK", 50))
    assert "使用触发随机产出" in text
    assert "从数组池 udg_ZBS[1..2] 随机抽件, 共 2 件" in text
    assert "宝物甲(I0A1)" in text
    assert "宝物乙(I0A2)" in text


def test_query_where_pickup_grant_evidence(pack):
    # 拾取凭证/宝箱触发的直接发放 (hxsj 世界商人/铜宝箱系统):
    # 条件 GetManipulatedItem 命中 + 事件为 PICKUP_ITEM → 产出与掷骰门槛
    from w3xtool.pack_query_cli import _query_where

    text = "\n".join(_query_where(pack, "I0TK", 50))
    assert "拾取触发产出" in text
    assert "获取 奖品(I0PG) (GetRandomInt(1,300))" in text


def test_query_source_side_relation_rows(pack):
    # 查询词本身是「来源」(可破坏物/商人) 时, 关系表装备列不匹配也要给
    # 来源侧行——路障 B007 掉三件, 两个命令曾都答「未找到」
    from w3xtool.pack_query_cli import _query_drop, _query_where

    drop_text = "\n".join(_query_drop(pack, "路障", 20))
    assert "路障[B007] 可破坏物掉落 -> 图腾石 [I0G1]" in drop_text
    where_text = "\n".join(_query_where(pack, "路障", 20))
    assert "来源 路障[B007]: 可破坏物掉落 -> 图腾石 [I0G1]" in where_text


def test_query_near_annotates_source_drops(pack):
    # 脚底/附近的可破坏物带掉落清单 (来源侧关系行): 路障 B007 掉图腾石
    from w3xtool.pack_query_cli import _query_near

    text = "\n".join(_query_near(pack, "12 18 500", 10))
    assert "装饰群: 路障 [B007]" in text
    assert "掉: 图腾石[I0G1]" in text


def test_script_use_item_loot_scopes_local_vars():
    # wbc 类使用触发: 同一初始化函数里 t 复用, 条件必须配自己的动作体
    # (全脚本按变量名配对会把末个动作体当产出——与死亡模板同源事故)
    from w3xtool.pack_query_cli import _script_use_item_loot

    script = (
        "function Trig_AA_Conditions takes nothing returns boolean\n"
        "return GetItemTypeId(GetManipulatedItem())=='I0PA'\n"
        "endfunction\n"
        "function Trig_AA_Actions takes nothing returns nothing\n"
        "call ItemPoolAddItemType(null, udg_PoolA[GetRandomInt(1,1)], 1)\n"
        "endfunction\n"
        "function Trig_BB_Conditions takes nothing returns boolean\n"
        "return GetItemTypeId(GetManipulatedItem())=='I0PB'\n"
        "endfunction\n"
        "function Trig_BB_Actions takes nothing returns nothing\n"
        "call ItemPoolAddItemType(null, udg_PoolB[GetRandomInt(1,1)], 1)\n"
        "endfunction\n"
        "function Init takes nothing returns nothing\n"
        "local trigger t=CreateTrigger()\n"
        "call TriggerAddCondition(t, Condition(function Trig_AA_Conditions))\n"
        "call TriggerAddAction(t, function Trig_AA_Actions)\n"
        "set t=CreateTrigger()\n"
        "call TriggerAddCondition(t, Condition(function Trig_BB_Conditions))\n"
        "call TriggerAddAction(t, function Trig_BB_Actions)\n"
        "endfunction\n"
        "set udg_PoolA[1]='I0XA'\n"
        "set udg_PoolB[1]='I0XB'\n"
    )
    text = "\n".join(_script_use_item_loot(script, "I0PA", {}))
    assert "udg_PoolA" in text and "I0XA" in text
    assert "udg_PoolB" not in text


def test_item_trigger_blocks_pair_by_position_in_giant_init(pack):
    # 同一初始化函数里 t 被反复复用: 条件必须配「其后最近」的 action,
    # 事件取各自注册窗口——旧实现按 (作用域,变量) 会把末个 action 配给所有条件
    from w3xtool.pack_query_cli import _item_trigger_blocks, load_script

    blocks = {b[1][0]: b for b in _item_trigger_blocks(load_script(pack))}
    a = blocks["I0MA"]
    assert "I0MA" in a[2] and "I0MB" not in a[2]
    assert "EVENT_PLAYER_UNIT_USE_ITEM" in a[3]
    b = blocks["I0MB"]
    assert "I0MB" in b[2] and "I0MA" not in b[2]
    assert "EVENT_PLAYER_UNIT_PICKUP_ITEM" in b[3]


def test_query_near_annotates_script_random_drops(pack):
    # near 注解同源: YDWE 每单位死亡随机掉落 (关系表无行) 也进「掉:」清单
    from w3xtool.pack_query_cli import _query_near

    text = "\n".join(_query_near(pack, "500 500 200", 10))
    assert "坐标怪 [nctm]" in text
    assert "死亡随机甲[I0YD]" in text


def test_query_shop_includes_craft_shops(pack):
    # 「商店制造」是独立通道: 制造商店没有 usei 货架, 只靠 stock 扫描
    # 会答「未找到商店」(迷失国度 奇迹古树/神秘藏宝室 即此类)。
    from w3xtool.pack_query_cli import _query_shop

    text = "\n".join(_query_shop(pack, "铁匠铺", 20))
    assert "== 铁匠铺 [h0ZZ]  (商店制造)" in text
    assert "制造 奖池甲 [I0P1]" in text
    # 关系表出售行 (货架字段缺失时的另一证据源: 容器商店只有关系行)
    sell_text = "\n".join(_query_shop(pack, "银月配方商", 20))
    assert "== 银月配方商 [h0YM]  (关系表出售)" in sell_text
    assert "宝物甲 [I0A1]" in sell_text


def test_query_recipe_from_relation_rows(pack):
    # 关系表「合成」行与脚本公式索引是两套证据 (迷失国度 0 公式但有
    # 秘法瓶/万灵药完整合成行) —— 按成品名或材料名都能查
    from w3xtool.pack_query_cli import _query_recipe

    text = "\n".join(_query_recipe(pack, "图腾石", 20))
    assert "[I0G1] 图腾石  <-  凭证×1;宝物甲×2" in text
    by_mat = "\n".join(_query_recipe(pack, "凭证", 20))
    assert "图腾石  <-  凭证×1;宝物甲×2" in by_mat


def test_run_cli_campaign_submap_aggregation(tmp_path, capsys):
    # 战役容器包 (子地图/*/) 自动逐关查询并分段标注——根目录无对象表,
    # 旧版对容器直接答「未找到」(永歌余烬 17 关数据全在子地图包里)
    root = tmp_path / "campaign"
    root.mkdir()
    sub = root / "子地图" / "001_x"
    sub.mkdir(parents=True)
    (sub / "掉落与获取关系.tsv").write_text(
        "关系ID\t地图子图\t关系类型\t装备ID\t装备名称\t来源分类\t来源ID\t来源名称\t实例序号\t玩家\tX\tY\tZ\t掉落组\t组内序号\t概率\t槽位\t合成材料ID\t合成材料名称与数量\t证据文件\n"
        "h1\t测试图\t脚本/触发奖励\tI0A1\t宝物甲\t单位\tu0AA\t雪妖\t\t\t\t\t\t\t\t\t\t\t\tw3x\n",
        encoding="utf-8",
    )
    rc = run_pack_query_cli(parse_pack_query_cli_options([str(root), "where", "宝物甲"]))
    out = capsys.readouterr().out
    assert rc == 0
    assert "== 子地图 001_x ==" in out
    assert "宝物甲 [I0A1]" in out


def test_query_locate_feature_code_intersection(pack):
    # 战役任务关识别第④步机械化: 全部特征码都出现才算命中
    from w3xtool.pack_query_cli import _query_locate

    text = "\n".join(_query_locate(pack, "IZYY;IZZZ", 20))
    assert "命中全部 2 个特征码: IZYY、IZZZ" in text
    assert "IZYY: 2 处引用" in text
    assert "IZZZ: 2 处引用" in text
    miss = "\n".join(_query_locate(pack, "IZYY;NOPE", 20))
    assert "缺少 NOPE" in miss


def test_parse_ok():
    o = parse_pack_query_cli_options(["pack", "item", "冰晶"])
    assert (o.command, o.query, o.limit) == ("item", "冰晶", 0)  # 默认全量
    o = parse_pack_query_cli_options(["pack", "text", "x", "--limit", "3"])
    assert o.limit == 3
    o = parse_pack_query_cli_options(["pack", "text", "x", "--limit", "0"])
    assert o.limit == 0  # 显式 0 = 不限量


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
        parse_pack_query_cli_options(
            ["pack", "item", "x", "--limit", "-1"]
        )  # 负数仍拒绝


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
