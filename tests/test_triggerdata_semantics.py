"""TriggerData.txt semantic rendering for WTG ECA exports."""

from __future__ import annotations

from dataclasses import dataclass
import os
import tempfile
import unittest

from w3xtool.api import MapData
from w3xtool.knowledge_pack import write_knowledge_pack
from w3xtool.trigger_exports import format_trigger_eca_tsv
from w3xtool.triggerdata import parse_trigger_data, render_eca_semantic
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
    def test_render_eca_semantic_uses_named_template_and_nested_calls(self) -> None:
        # Given: TriggerData entries with argument names and a WTG action containing
        # a nested function parameter.
        trigger_data = parse_trigger_data(
            """
            [CreateNUnitsAtLoc]
            Name=单位 - 创建单位
            Template=单位 - 创建 {count} 个 {unit} 于 {location}
            Args=count,unit,location

            [OperatorCompareInteger]
            Template=({left} {op} {right})
            Args=left,op,right
            """
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

        # Then: the output is an editor-style sentence instead of raw parameter indexes.
        self.assertEqual(text, "单位 - 创建 1 个 hfoo 于 (1 == 2)")

    def test_trigger_eca_tsv_includes_semantic_text_column(self) -> None:
        # Given: a parsed action and matching TriggerData table.
        trigger_data = parse_trigger_data(
            """
            [TriggerActions]
            DisplayTextToForce=游戏 - 显示 {message} 给 {force}
            DisplayTextToForceArgs=message,force
            """
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
        self.assertIn("DisplayTextToForce\t是\t\t\t\t游戏 - 显示 欢迎 给 所有玩家", text)

    def test_flat_triggerdata_keeps_function_names_that_end_with_name(self) -> None:
        # Given: flat TriggerData where the function name itself ends with "Name".
        trigger_data = parse_trigger_data(
            """
            [TriggerActions]
            SetUnitName=单位 - 设置 {unit} 名称为 {name}
            SetUnitNameArgs=unit,name
            """
        )
        action = _function(
            "SetUnitName",
            (TriggerEcaParameter(0, "英雄"), TriggerEcaParameter(0, "阿尔萨斯")),
        )

        # When: the action is rendered.
        text = render_eca_semantic(action, trigger_data)

        # Then: the function key is not mistaken for a metadata suffix.
        self.assertEqual(text, "单位 - 设置 英雄 名称为 阿尔萨斯")

    def test_knowledge_pack_uses_game_data_triggerdata_when_available(self) -> None:
        # Given: a map with WTG ECA and a selected game-data directory containing TriggerData.txt.
        md = MapData(path="/missing/map.w3x", name="触发器图")
        md.trigger_summary = _Summary(
            (
                _function("DisplayTextToForce", (TriggerEcaParameter(0, "你好"),)),
            )
        )
        with tempfile.TemporaryDirectory() as game_data, tempfile.TemporaryDirectory() as out:
            ui_dir = os.path.join(game_data, "war3.w3mod", "UI")
            os.makedirs(ui_dir)
            with open(os.path.join(ui_dir, "TriggerData.txt"), "w", encoding="utf-8") as handle:
                handle.write(
                    "[DisplayTextToForce]\n"
                    "Template=游戏 - 显示 {message}\n"
                    "Args=message\n"
                )

            # When: the knowledge pack is written with that game data source.
            write_knowledge_pack(md, out, game_data_path=game_data)

            # Then: the exported ECA table contains the semantic editor sentence.
            with open(os.path.join(out, "触发器ECA.tsv"), encoding="utf-8") as handle:
                text = handle.read()
            self.assertIn("游戏 - 显示 你好", text)


if __name__ == "__main__":
    unittest.main()
