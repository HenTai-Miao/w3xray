"""guide 攻略速查报告：脚本扫描、英雄阵容与物品关系的纯派生组装。"""

import pytest

from w3xtool.base_names import BASE_CATEGORIES, BASE_NAMES
from w3xtool.doo import Unit
from w3xtool.guide_cli import GuideCliOptionError, parse_guide_cli_options
from w3xtool.guide_report import format_guide_report
from w3xtool.item_relation_models import (
    ItemRelation,
    ItemRelationIndex,
    ItemRelationKind,
    RelationCompleteness,
    RelationConfidence,
    RelationEvidence,
    RelationIngredient,
    RelationObject,
)
from w3xtool.map_data import GameObject, MapData
from w3xtool.w3i import Player, W3iInfo

_SCRIPT = """
function Trig_huicheng_Actions takes nothing returns nothing
    call DisplayTextToForce(GetPlayersAll(), "游戏中输入b可以回城。")
endfunction
function InitTrig_huicheng takes nothing returns nothing
    call TriggerRegisterPlayerChatEvent(gg_trg_huicheng, Player(0), "b", true)
endfunction
function Trig_renwu_Actions takes nothing returns nothing
    call CreateQuestBJ(bj_QUESTTYPE_REQ_DISCOVERED, "地图简介", "|c0000CC00守卫|r哭泣之泉35波", "Icons.blp")
endfunction
function Trig_boss_Actions takes nothing returns nothing
    call CreateTimerDialogBJ(udg_Timer9, "基尔加丹")
    call DisplayTextToForce(GetPlayersAll(), "第10波出现boss！！！可前往挑战！！！")
endfunction
function Trig_xdropConditions takes nothing returns boolean
    return GetOwningPlayer(GetDyingUnit())==Player(10) and GetUnitTypeId(GetDyingUnit())=='n018'
endfunction
function Trig_xdropActions takes nothing returns nothing
    call CreateItemLoc('I01O',GetUnitLoc(GetDyingUnit()))
    if(GetRandomInt(1,100)<=40)then
        call UnitAddItemByIdSwapped('I0A9',GetKillingUnitBJ())
    endif
endfunction
function Trig_pdropConditions takes nothing returns boolean
    return GetUnitTypeId(GetDyingUnit())=='nbos'
endfunction
function Trig_pdropActions takes nothing returns nothing
    call ItemPoolAddItemType(udg_PD[3],'I0P2',100.0)
    call YDWEPlaceRandomItem(udg_PD[3],0.0,0.0)
endfunction
function Trig_useConditions takes nothing returns boolean
    return GetItemTypeId(GetManipulatedItem())=='I0CK'
endfunction
function Trig_useActions takes nothing returns nothing
    call ItemPoolAddItemType(LoadItemPoolHandle(YDLOC,GetHandleId(GetTriggeringTrigger()),$1290C38A),udg_ZBS[GetRandomInt(1,2)],1)
endfunction
function InitTrig_use takes nothing returns nothing
    set gg_trg_use=CreateTrigger()
    call TriggerAddCondition(gg_trg_use, Condition(function Trig_useConditions))
    call TriggerAddAction(gg_trg_use, function Trig_useActions)
endfunction
set udg_ZBS[1]='I0A1'
set udg_ZBS[2]='I0A2'
"""


def _relation(
    kind: ItemRelationKind, item_id: str, item_name: str, line: int = 42
) -> ItemRelation:
    source = (
        RelationObject("单位", "nwwd", "恐怖霜狼")
        if kind == ItemRelationKind.SHOP_SELL
        else RelationObject("单位", "nrwm", "雷暴元素")
    )
    return ItemRelation(
        kind=kind,
        item=RelationObject("物品", item_id, item_name),
        source=source,
        chance=100 if kind == ItemRelationKind.UNIT_DROP else None,
        evidence=RelationEvidence(
            source="war3map.j", line=line, trigger="Trig_xUPActions"
        ),
        confidence=RelationConfidence.CONFIRMED,
        completeness=RelationCompleteness.COMPLETE,
    )


def _recipe_relation() -> ItemRelation:
    return ItemRelation(
        kind=ItemRelationKind.RECIPE,
        item=RelationObject("物品", "I009", "混沌天痕"),
        ingredients=(RelationIngredient(RelationObject("物品", "oli2", "光之灵"), 1),),
        evidence=RelationEvidence(
            source="war3map.j", line=6736, trigger="Trig_xianzhiUPActions"
        ),
        confidence=RelationConfidence.CONFIRMED,
        completeness=RelationCompleteness.COMPLETE,
    )


def _map_data(monkeypatch: pytest.MonkeyPatch) -> MapData:
    monkeypatch.setitem(BASE_CATEGORIES, "Zh0", ("英雄", "Hero"))
    monkeypatch.setitem(BASE_CATEGORIES, "hpea", ("单位", "Peasant"))
    monkeypatch.setitem(BASE_NAMES, "Zh0", "测试英雄")
    return MapData(
        path="t.w3x",
        name="测试图",
        scripts={"war3map.j": _SCRIPT},
        obj_index={
            "Xh01": GameObject(
                category="单位",
                ext="w3u",
                obj_id="Xh01",
                base_id="Hpal",
                name="自定义圣骑士",
                is_custom=True,
            ),
            "Xp01": GameObject(
                category="单位",
                ext="w3u",
                obj_id="Xp01",
                base_id="hpea",
                name="自定义农民",
                is_custom=True,
            ),
            "n018": GameObject(
                category="单位",
                ext="w3u",
                obj_id="n018",
                base_id="",
                name="炎石守卫",
                is_custom=False,
            ),
            "nbos": GameObject(
                category="单位",
                ext="w3u",
                obj_id="nbos",
                base_id="",
                name="奖池怪",
                is_custom=False,
            ),
            "I01O": GameObject(
                category="物品",
                ext="w3t",
                obj_id="I01O",
                base_id="",
                name="钻石",
                is_custom=False,
            ),
            "I0A9": GameObject(
                category="物品",
                ext="w3t",
                obj_id="I0A9",
                base_id="",
                name="猎刃",
                is_custom=False,
            ),
            "I0P2": GameObject(
                category="物品",
                ext="w3t",
                obj_id="I0P2",
                base_id="",
                name="奖池物品",
                is_custom=False,
            ),
            "I0CK": GameObject(
                category="物品",
                ext="w3t",
                obj_id="I0CK",
                base_id="",
                name="宝箱",
                is_custom=False,
            ),
            "I0A1": GameObject(
                category="物品",
                ext="w3t",
                obj_id="I0A1",
                base_id="",
                name="宝物甲",
                is_custom=False,
            ),
            "I0A2": GameObject(
                category="物品",
                ext="w3t",
                obj_id="I0A2",
                base_id="",
                name="宝物乙",
                is_custom=False,
            ),
        },
        units=[
            Unit(type_id="Zh0", variation=0, x=1.0, y=2.0, z=0.0, angle=0.0, player=15),
            Unit(
                type_id="hpea", variation=0, x=3.0, y=4.0, z=0.0, angle=0.0, player=15
            ),
            Unit(
                type_id="Xh01", variation=0, x=5.0, y=6.0, z=0.0, angle=0.0, player=15
            ),
            Unit(
                type_id="Xp01", variation=0, x=7.0, y=8.0, z=0.0, angle=0.0, player=15
            ),
        ],
        w3i=W3iInfo(
            map_name="测试图",
            author="作者甲",
            description="|c00FF0000守住|r基地",
            recommended_players="任何",
            width=64,
            height=64,
            players=[Player(id=1, type=1, race=1, fixed_start=0, name="玩家1")],
        ),
        item_relations=ItemRelationIndex.build(
            (
                _recipe_relation(),
                _relation(ItemRelationKind.SHOP_SELL, "tret", "经验之书"),
                _relation(ItemRelationKind.UNIT_DROP, "I03L", "召唤卷轴"),
                # 同一商店第二出售槽（证据行号不同）：同名物品应折叠为一条。
                _relation(ItemRelationKind.SHOP_SELL, "tret", "经验之书", line=99),
            )
        ),
    )


def test_full_report_covers_player_facing_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 一张带脚本、英雄、任务与物品关系的地图。
    md = _map_data(monkeypatch)

    # When: 渲染完整攻略速查。
    report = format_guide_report(md)

    # Then: 每类玩家问题都有对应段落，颜色码被清理。
    assert "作者：作者甲" in report
    assert "简介：守住基地" in report
    assert "输入 b（精确匹配） — 游戏中输入b可以回城。" in report
    assert "◆ 地图简介" in report
    assert "守卫哭泣之泉35波" in report
    assert "测试英雄(Zh0) — 预放置 ×1" in report
    # 自定义码英雄经 base_id 兜底命中；自定义码小兵不误报。
    assert "自定义圣骑士(Xh01) — 预放置 ×1" in report
    assert "Xp01" not in report
    assert "hpea" not in report
    assert (
        "混沌天痕(I009) = 光之灵×1 〔war3map.j:6736 Trig_xianzhiUPActions〕" in report
    )
    assert "恐怖霜狼(nwwd)：经验之书" in report
    assert report.count("经验之书") == 1
    assert "雷暴元素(nrwm)：召唤卷轴 100%" in report
    assert "计时器标签：基尔加丹" in report
    assert "播报：第10波出现boss！！！可前往挑战！！！" in report
    # drops 段并入脚本死亡触发证据 (直落掷骰门槛/奖池 N选1)。
    assert (
        "炎石守卫(n018)  ⚠ 脚本死亡掉落 (Trig_xdrop, 关系表外证据): "
        "直落 钻石(I01O) 掷骰:无掷骰；猎刃(I0A9) 掷骰:GetRandomInt(1,100)"
    ) in report
    assert (
        "奖池怪(nbos)  ⚠ 脚本死亡掉落 (Trig_pdrop, 关系表外证据): "
        "池 udg_PD[3] 共1件N选1: 奖池物品(I0P2) 100/100"
    ) in report
    # 开箱与随机产出段: 使用触发数组池 (与 where 同源)。
    assert "【开箱与兑换产出】" in report
    assert (
        "使用 宝箱(I0CK) 随机产出: 从数组池 udg_ZBS[1..2] 随机抽件, "
        "共 2 件: 宝物甲(I0A1)、宝物乙(I0A2)"
    ) in report


def test_drops_section_includes_script_death_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 同一张地图 (关系表掉落 + 脚本死亡直落/奖池并存)。
    md = _map_data(monkeypatch)

    # When: 只请求掉落段。
    report = format_guide_report(md, "drops")

    # Then: 关系表行与脚本死亡证据并列满量。
    assert "雷暴元素(nrwm)：召唤卷轴 100%" in report
    assert "脚本死亡掉落" in report
    assert "直落 钻石(I01O)" in report
    assert "池 udg_PD[3] 共1件N选1" in report


def test_section_filter_returns_single_section(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: 同一张地图。
    md = _map_data(monkeypatch)

    # When: 只请求合成段。
    report = format_guide_report(md, "recipes")

    # Then: 只有合成段，其余段落不出现。
    assert "【合成配方】" in report
    assert "混沌天痕" in report
    assert "【任务说明】" not in report
    assert "【英雄阵容】" not in report


def test_unknown_section_raises_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: 任意地图与未知段落键。
    md = _map_data(monkeypatch)

    # When/Then: 明确报错并列出可选段落。
    with pytest.raises(ValueError, match="未知攻略段落"):
        format_guide_report(md, "nonsense")


def test_empty_evidence_keeps_only_basic_section() -> None:
    # Given: 无脚本、无预放置单位、无关系的空地图。
    md = MapData(path="t.w3x", name="空图")

    # When: 渲染攻略速查。
    report = format_guide_report(md)

    # Then: 只剩基本信息段，其余段落省略。
    assert "【基本信息】" in report
    assert "【聊天指令】" not in report
    assert "【任务说明】" not in report
    assert "【英雄阵容】" not in report
    assert "【合成配方】" not in report


def test_parse_guide_cli_options_accepts_section() -> None:
    # Given: 地图路径 + 段落参数。
    options = parse_guide_cli_options(("t.w3x", "--section", "recipes"))

    # Then: 参数被完整保留。
    assert options.map_path == "t.w3x"
    assert options.section == "recipes"


def test_parse_guide_cli_options_rejects_bad_input() -> None:
    # When/Then: 缺路径、未知段落、重复段落各自报错。
    with pytest.raises(GuideCliOptionError, match="缺少地图路径"):
        parse_guide_cli_options(("--section", "recipes"))
    with pytest.raises(GuideCliOptionError, match="未知段落"):
        parse_guide_cli_options(("t.w3x", "--section", "nonsense"))
    with pytest.raises(GuideCliOptionError, match="不能重复"):
        parse_guide_cli_options(("t.w3x", "--section", "recipes", "--section", "shops"))
