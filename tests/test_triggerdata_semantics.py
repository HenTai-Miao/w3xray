"""TriggerData.txt semantic rendering for WTG ECA exports."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
import unittest

from w3xtool.api import MapData
from w3xtool.knowledge_pack import write_knowledge_pack
from w3xtool.trigger_schema import TriggerSchema, parse_trigger_schema
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


def _trigger_fixture(name: str) -> str:
    return Path(__file__).with_name("fixtures").joinpath("trigger", name).read_text(encoding="utf-8")


def _duplicate_name_schema() -> TriggerSchema:
    return parse_trigger_schema(
        """
        [TriggerConditions]
        SharedFunction=0,integer

        [TriggerCalls]
        SharedFunction=0,0,integer,integer
        """,
        """
        [TriggerConditionStrings]
        SharedFunction="Shared Condition"
        SharedFunction="condition ",~Value

        [TriggerCallStrings]
        SharedFunction="Shared Call"
        SharedFunction="call ",~Value
        """,
    )


class TriggerDataSemanticTest(unittest.TestCase):
    def test_semantic_fallback_resolves_wts_and_preserves_named_object_id(self) -> None:
        # Given: a schema-free action referring to map text and a named object code.
        action = _function(
            "ShowMessage",
            (TriggerEcaParameter(0, "TRIGSTR_001"), TriggerEcaParameter(0, "H001")),
        )

        # When: map-local display context is used by the semantic renderer.
        text = render_eca_semantic(
            action, None, wts={1: "开始游戏"}, object_names={"H001": "圣骑士"},
        )

        # Then: readable values remain traceable to their raw object ID.
        self.assertEqual(text, "ShowMessage(开始游戏, 圣骑士(H001))")

    def test_semantic_fallback_recurses_through_array_indexers(self) -> None:
        # Given: one array parameter whose index is another recursively indexed array.
        final_index = TriggerEcaParameter(0, "3")
        nested_index = TriggerEcaParameter(
            1, "Indexes", have_array_indexer=1, array_indexer=final_index,
        )
        array = TriggerEcaParameter(
            1, "Numbers", have_array_indexer=1, array_indexer=nested_index,
        )

        # When: the schema-free semantic fallback renders the action.
        text = render_eca_semantic(_function("UseValue", (array,)), None)

        # Then: no recursive array-index value is dropped.
        self.assertEqual(text, "UseValue(Numbers[Indexes[3]])")

    def test_render_eca_semantic_uses_real_trigger_strings_and_nested_calls(self) -> None:
        # Given: complete real TriggerData/TriggerStrings fixtures and a WTG action
        # containing a nested condition call.
        trigger_data = parse_trigger_schema(
            _trigger_fixture("TriggerData.txt"),
            _trigger_fixture("TriggerStrings.txt"),
        )
        nested = _function(
            "OperatorCompareInteger",
            (
                TriggerEcaParameter(0, "1"),
                TriggerEcaParameter(0, "=="),
                TriggerEcaParameter(0, "2"),
            ),
            function_type=1,
        )
        action = _function(
            "CreateNUnitsAtLoc",
            (
                TriggerEcaParameter(0, "1"),
                TriggerEcaParameter(0, "hfoo"),
                TriggerEcaParameter(0, "Player 1"),
                TriggerEcaParameter(2, "比较", nested),
                TriggerEcaParameter(0, "270.00"),
            ),
        )

        # When: the ECA action is rendered through TriggerData.
        text = render_eca_semantic(action, trigger_data)

        # Then: the output is an editor-style sentence instead of the raw signature.
        self.assertEqual(text, "Create 1 hfoo for Player 1 at 1 == 2 facing 270.00 degrees")

    def test_schema_lookup_prefers_an_exact_kind_match(self) -> None:
        # Given: two real-format schema entries with one shared function name.
        schema = _duplicate_name_schema()
        function = _function(
            "SharedFunction",
            (TriggerEcaParameter(0, "value"),),
            function_type=1,
        )

        # When: the condition-kind function is rendered.
        text = render_eca_semantic(function, schema)

        # Then: the exact condition schema wins despite the duplicate call name.
        self.assertEqual(text, "condition value")

    def test_schema_lookup_falls_back_only_for_a_unique_name(self) -> None:
        # Given: one condition schema and mismatched event metadata.
        schema = parse_trigger_schema(
            "[TriggerConditions]\nUniqueFunction=0,integer\n",
            (
                "[TriggerConditionStrings]\n"
                'UniqueFunction="Unique Condition"\n'
                'UniqueFunction="condition ",~Value\n'
            ),
        )
        function = _function(
            "UniqueFunction",
            (TriggerEcaParameter(0, "value"),),
            function_type=0,
        )

        # When: the mismatched function is rendered.
        text = render_eca_semantic(function, schema)

        # Then: the sole same-name schema supplies the semantic template.
        self.assertEqual(text, "condition value")

    def test_schema_lookup_rejects_an_ambiguous_cross_kind_name(self) -> None:
        # Given: condition and call schemas share a name, but WTG metadata says event.
        schema = _duplicate_name_schema()
        function = _function(
            "SharedFunction",
            (TriggerEcaParameter(0, "value"),),
            function_type=0,
        )

        # When: the function is rendered without an exact-kind schema.
        text = render_eca_semantic(function, schema)

        # Then: no enum-order-dependent cross-kind template is selected.
        self.assertEqual(text, "SharedFunction(value)")

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

    def test_knowledge_pack_ignores_a_malformed_optional_trigger_schema(self) -> None:
        # Given: a map with ECA data and an invalid optional TriggerData signature.
        md = MapData(path="/missing/map.w3x", name="触发器图")
        md.trigger_summary = _Summary(
            (_function("DisplayTextToForce", (TriggerEcaParameter(0, "所有玩家"),)),)
        )
        with tempfile.TemporaryDirectory() as game_data, tempfile.TemporaryDirectory() as out:
            ui_dir = os.path.join(game_data, "war3.w3mod", "UI")
            os.makedirs(ui_dir)
            with open(os.path.join(ui_dir, "TriggerData.txt"), "w", encoding="utf-8") as handle:
                handle.write("[TriggerActions]\nDisplayTextToForce=\n")

            # When: the knowledge pack is written with malformed optional metadata.
            write_knowledge_pack(md, out, game_data_path=game_data)

            # Then: export succeeds and retains the original function row.
            with open(os.path.join(out, "触发器ECA.tsv"), encoding="utf-8") as handle:
                text = handle.read()
            self.assertIn("DisplayTextToForce", text)


if __name__ == "__main__":
    unittest.main()
