"""脚本触发注册索引：整理事件、动作、条件和计时器入口。"""

import importlib
import importlib.util
import unittest

from w3xtool.api import MapData


def _format_registrations(md: MapData) -> str:
    spec = importlib.util.find_spec("w3xtool.script_trigger_registration_index")
    if spec is None:
        raise AssertionError("w3xtool.script_trigger_registration_index module is missing")
    module = importlib.import_module("w3xtool.script_trigger_registration_index")
    index = module.build_script_trigger_registration_index(md)
    return module.format_script_trigger_registration_index_tsv(index)


class ScriptTriggerRegistrationIndexTest(unittest.TestCase):
    def test_indexes_events_actions_conditions_and_timers(self):
        # Given: script initialization wires triggers, events, handlers and a timer callback.
        md = MapData(path="x.w3x", name="触发注册图")
        md.scripts = {
            "war3map.j": "\n".join((
                "function InitTrig_Save takes nothing returns nothing",
                "    set gg_trg_Save = CreateTrigger()",
                "    call TriggerRegisterPlayerEvent(gg_trg_Save, Player(0), EVENT_PLAYER_LEAVE)",
                "    call TriggerRegisterPlayerChatEvent(gg_trg_Save, Player(0), \"-save\", true)",
                "    call TriggerAddCondition(gg_trg_Save, Condition(function Trig_Save_Conditions))",
                "    call TriggerAddAction(gg_trg_Save, function Trig_Save_Actions)",
                "endfunction",
                "function InitTimer takes nothing returns nothing",
                "    call TimerStart(udg_SaveTimer, 5.00, true, function SaveTick)",
                "endfunction",
            )),
        }

        # When: the trigger registration index is built.
        text = _format_registrations(md)

        # Then: control-flow entry points are visible with function context.
        self.assertIn("来源\t行号\t函数\t注册类型\t句柄\tAPI\t目标\t字符串参数\t摘要", text)
        self.assertIn(
            "war3map.j\t3\tInitTrig_Save\t事件\tgg_trg_Save\tTriggerRegisterPlayerEvent\tEVENT_PLAYER_LEAVE",
            text,
        )
        self.assertIn(
            "war3map.j\t4\tInitTrig_Save\t聊天事件\tgg_trg_Save\tTriggerRegisterPlayerChatEvent\t-save\t-save",
            text,
        )
        self.assertIn(
            "war3map.j\t5\tInitTrig_Save\t条件\tgg_trg_Save\tTriggerAddCondition\tTrig_Save_Conditions",
            text,
        )
        self.assertIn(
            "war3map.j\t6\tInitTrig_Save\t动作\tgg_trg_Save\tTriggerAddAction\tTrig_Save_Actions",
            text,
        )
        self.assertIn(
            "war3map.j\t9\tInitTimer\t计时器\tudg_SaveTimer\tTimerStart\tSaveTick",
            text,
        )

    def test_ignores_registration_like_text_inside_comments_and_strings(self):
        # Given: comments and player-facing strings contain registration-like text.
        md = MapData(path="x.w3x", name="触发注册去噪图")
        md.scripts = {
            "war3map.j": "\n".join((
                "function Init takes nothing returns nothing",
                "    // call TriggerAddAction(gg_trg_Fake, function Bad_Actions)",
                '    call BJDebugMsg("TriggerRegisterPlayerEvent(gg_trg_Fake, Player(0), EVENT_PLAYER_LEAVE)")',
                "    call TriggerAddAction(gg_trg_Real, function Real_Actions)",
                "endfunction",
            )),
        }

        # When: the trigger registration index is built.
        text = _format_registrations(md)

        # Then: only executable registration calls are indexed.
        self.assertIn("gg_trg_Real\tTriggerAddAction\tReal_Actions", text)
        self.assertNotIn("gg_trg_Fake", text)
        self.assertNotIn("Bad_Actions", text)


if __name__ == "__main__":
    unittest.main()
