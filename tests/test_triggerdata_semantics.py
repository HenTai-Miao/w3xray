"""TriggerData.txt semantic rendering for WTG ECA exports."""

from __future__ import annotations

from dataclasses import dataclass
import os
import tempfile
import unittest

from w3xtool.api import MapData
from w3xtool.knowledge_pack import write_knowledge_pack
from w3xtool.trigger_schema import parse_trigger_schema
from w3xtool.trigger_exports import format_trigger_eca_tsv
from w3xtool.triggerdata import render_eca_semantic
from w3xtool.wtg_eca import TriggerEcaFunction, TriggerEcaParameter


@dataclass(frozen=True, slots=True)
class _Summary:
    eca_functions: tuple[TriggerEcaFunction, ...]
    has_unexpanded_functions: bool = False
    is_reforged: bool = False
    version: int = 7
    trigger_count: int = 1
    variable_count: int = 0
    category_count: int = 0
    comment_count: int = 0
    script_count: int = 0
    categories: tuple = ()
    variables: tuple = ()
    triggers: tuple = ()


def _function(
    name: str,
    params: tuple[TriggerEcaParameter, ...],
    *,
    function_type: int = 2,
) -> TriggerEcaFunction:
    return TriggerEcaFunction(
        trigger_name="初始化",
        function_type=function_type,
        name=name,
        is_enabled=True,
        parameters=params,
        children=(),
    )


class TriggerDataSemanticTest(unittest.TestCase):
    def test_render_eca_semantic_uses_real_trigger_strings_and_nested_calls(self) -> None:
        # Given: real-format TriggerData/TriggerStrings entries and a WTG action
        # containing a nested condition call.
        trigger_data = parse_trigger_schema(
            """
            [TriggerActions]
            CreateNUnitsAtLoc=0,integer,unitcode,location,real
            _CreateNUnitsAtLoc_Category=TC_UNIT

            [TriggerConditions]
            OperatorCompareInteger=0,integer,EqualNotEqualOperator,integer
            _OperatorCompareInteger_Category=TC_CONDITION
            """,
            """
            [TriggerActionStrings]
            CreateNUnitsAtLoc="Create Units At Point"
            CreateNUnitsAtLoc="Create ",~Count," units of type ",~Unit," at ",~Point
            CreateNUnitsAtLocHint=

            [TriggerConditionStrings]
            OperatorCompareInteger="Integer Comparison"
            OperatorCompareInteger=~Value," ",~Operator," ",~Value
            OperatorCompareIntegerHint=
            """,
        )
        nested = _function(
            "OperatorCompareInteger",
            (
                TriggerEcaParameter(0, "1"),
                TriggerEcaParameter(0, "=="),
                TriggerEcaParameter(0, "2"),
            ),
            function_type=3,
        )
        action = _function(
            "CreateNUnitsAtLoc",
            (
                TriggerEcaParameter(0, "1"),
                TriggerEcaParameter(0, "hfoo"),
                TriggerEcaParameter(2, "比较", nested),
            ),
        )

        # When: the ECA action is rendered through TriggerData.
        text = render_eca_semantic(action, trigger_data)

        # Then: the output is an editor-style sentence instead of the raw signature.
        self.assertEqual(text, "Create 1 units of type hfoo at 1 == 2")

    def test_trigger_eca_tsv_includes_semantic_text_column(self) -> None:
        # Given: a parsed action and matching real-format trigger schema.
        trigger_data = parse_trigger_schema(
            """
            [TriggerActions]
            DisplayTextToForce=0,force,StringExt
            _DisplayTextToForce_Category=TC_GAME
            """,
            """
            [TriggerActionStrings]
            DisplayTextToForce="Text Message (Auto-Timed)"
            DisplayTextToForce="Display to ",~Player Group," the text: ",~Text
            DisplayTextToForceHint=
            """,
        )
        summary = _Summary(
            (
                _function(
                    "DisplayTextToForce",
                    (
                        TriggerEcaParameter(0, "欢迎"),
                        TriggerEcaParameter(0, "所有玩家"),
                    ),
                ),
            )
        )

        # When: the ECA report is formatted with TriggerData.
        text = format_trigger_eca_tsv(summary, trigger_data=trigger_data)

        # Then: raw rows remain, with a semantic sentence attached to the function row.
        self.assertIn("触发器\t深度\t行类型\t函数类型\t函数名\t启用\t参数序号\t参数类型\t参数值\t语义文本", text)
        self.assertIn("DisplayTextToForce\t是\t\t\t\tDisplay to 欢迎 the text: 所有玩家", text)

    def test_real_schema_keeps_function_names_that_end_with_name(self) -> None:
        # Given: a real-format action whose function key itself ends with "Name".
        trigger_data = parse_trigger_schema(
            """
            [TriggerActions]
            SetPlayerName=1,player,StringExt
            _SetPlayerName_Category=TC_PLAYER
            """,
            """
            [TriggerActionStrings]
            SetPlayerName="Set Name"
            SetPlayerName="Set name of ",~Player," to ",~Name
            SetPlayerNameHint=
            """,
        )
        action = _function(
            "SetPlayerName",
            (TriggerEcaParameter(0, "英雄"), TriggerEcaParameter(0, "阿尔萨斯")),
        )

        # When: the action is rendered.
        text = render_eca_semantic(action, trigger_data)

        # Then: the function key is not mistaken for schema metadata.
        self.assertEqual(text, "Set name of 英雄 to 阿尔萨斯")

    def test_knowledge_pack_uses_game_data_triggerdata_when_available(self) -> None:
        # Given: a map with WTG ECA and a selected game-data directory containing
        # real-format TriggerData.txt and TriggerStrings.txt.
        md = MapData(path="/missing/map.w3x", name="触发器图")
        md.trigger_summary = _Summary(
            (
                _function(
                    "DisplayTextToForce",
                    (
                        TriggerEcaParameter(0, "所有玩家"),
                        TriggerEcaParameter(0, "你好"),
                    ),
                ),
            )
        )
        with tempfile.TemporaryDirectory() as game_data, tempfile.TemporaryDirectory() as out:
            ui_dir = os.path.join(game_data, "war3.w3mod", "UI")
            os.makedirs(ui_dir)
            with open(os.path.join(ui_dir, "TriggerData.txt"), "w", encoding="utf-8") as handle:
                handle.write(
                    "[TriggerActions]\n"
                    "DisplayTextToForce=0,force,StringExt\n"
                    "_DisplayTextToForce_Category=TC_GAME\n"
                )
            with open(os.path.join(ui_dir, "TriggerStrings.txt"), "w", encoding="utf-8") as handle:
                handle.write(
                    "[TriggerActionStrings]\n"
                    'DisplayTextToForce="Text Message (Auto-Timed)"\n'
                    'DisplayTextToForce="Display to ",~Player Group," the text: ",~Text\n'
                    "DisplayTextToForceHint=\n"
                )

            # When: the knowledge pack is written with that game data source.
            write_knowledge_pack(md, out, game_data_path=game_data)

            # Then: the exported ECA table contains the semantic editor sentence.
            with open(os.path.join(out, "触发器ECA.tsv"), encoding="utf-8") as handle:
                text = handle.read()
            self.assertIn("Display to 所有玩家 the text: 你好", text)


if __name__ == "__main__":
    unittest.main()
