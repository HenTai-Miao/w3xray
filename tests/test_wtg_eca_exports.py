"""WTG ECA function-body parsing and knowledge-pack export tests."""

from __future__ import annotations

import os
import struct
import tempfile
import unittest

from w3xtool.api import MapData
from w3xtool.knowledge_pack import write_knowledge_pack
from w3xtool.trigger_exports import format_trigger_eca_tsv
from w3xtool.wtg import parse_wtg


def _i(value: int) -> bytes:
    return struct.pack("<i", value)


def _z(text: str) -> bytes:
    return text.encode("utf-8") + b"\x00"


def _param(parameter_type: int, value: str, nested: bytes = b"") -> bytes:
    return (
        _i(parameter_type)
        + _z(value)
        + _i(1 if nested else 0)
        + nested
        + _i(1 if nested else 0)
    )


def _eca(
    function_type: int,
    name: str,
    enabled: int,
    params: tuple[bytes, ...],
    children: tuple[bytes, ...] = (),
) -> bytes:
    return (
        _i(function_type)
        + _z(name)
        + _i(enabled)
        + _i(len(params))
        + b"".join(params)
        + _i(len(children))
        + b"".join(children)
    )


def _trigger_header(name: str, eca_count: int) -> bytes:
    return (
        _z(name)
        + _z("说明")
        + _i(0)
        + _i(1)
        + _i(0)
        + _i(0)
        + _i(1)
        + _i(42)
        + _i(eca_count)
    )


def _classic_wtg_with_eca() -> bytes:
    nested_call = _eca(3, "OperatorCompareInteger", 1, (_param(0, "1"), _param(0, "2")))
    action = _eca(
        2,
        "CreateNUnitsAtLoc",
        1,
        (
            _param(0, "1"),
            _param(0, "hfoo"),
            _param(2, "比较", nested_call),
        ),
        (_eca(2, "DisplayTextToForce", 0, (_param(0, "TRIGSTR_001"),)),),
    )
    return (
        b"WTG!"
        + _i(7)
        + _i(1)
        + _i(42)
        + _z("系统")
        + _i(0)
        + _i(0)
        + _i(0)
        + _i(1)
        + _trigger_header("初始化", 1)
        + action
    )


class WtgEcaExportTest(unittest.TestCase):
    def test_parse_classic_wtg_expands_eca_function_tree(self) -> None:
        # Given: a classic WTG trigger whose action has parameters, a nested call,
        # and a child action.
        data = _classic_wtg_with_eca()

        # When: the WTG file is parsed.
        summary = parse_wtg(data)

        # Then: raw ECA function bodies are available without relying on JASS.
        self.assertFalse(summary.has_unexpanded_functions)
        self.assertEqual(len(summary.eca_functions), 1)
        action = summary.eca_functions[0]
        self.assertEqual(action.trigger_name, "初始化")
        self.assertEqual(action.name, "CreateNUnitsAtLoc")
        self.assertEqual(action.function_type, 2)
        self.assertTrue(action.is_enabled)
        self.assertEqual([param.value for param in action.parameters], ["1", "hfoo", "比较"])
        self.assertEqual(action.parameters[2].nested_function.name, "OperatorCompareInteger")
        self.assertEqual(action.children[0].name, "DisplayTextToForce")
        self.assertFalse(action.children[0].is_enabled)

    def test_trigger_eca_tsv_exports_functions_parameters_and_children(self) -> None:
        # Given: parsed WTG ECA functions.
        summary = parse_wtg(_classic_wtg_with_eca())

        # When: the ECA report is formatted.
        text = format_trigger_eca_tsv(summary)

        # Then: the report shows function rows, parameter rows and hierarchy depth.
        self.assertIn("触发器\t深度\t行类型\t函数类型\t函数名\t启用\t参数序号\t参数类型\t参数值", text)
        self.assertIn("初始化\t0\t函数\t动作\tCreateNUnitsAtLoc\t是", text)
        self.assertIn("初始化\t0\t参数\t动作\tCreateNUnitsAtLoc\t是\t2\t函数\t比较", text)
        self.assertIn("初始化\t1\t函数\t调用\tOperatorCompareInteger\t是", text)
        self.assertIn("初始化\t1\t函数\t动作\tDisplayTextToForce\t否", text)

    def test_knowledge_pack_writes_trigger_eca_table(self) -> None:
        # Given: a map with parsed WTG ECA metadata.
        md = MapData(path="x.w3x", name="ECA图")
        md.trigger_summary = parse_wtg(_classic_wtg_with_eca())

        # When: the knowledge pack is written.
        with tempfile.TemporaryDirectory() as out:
            write_knowledge_pack(md, out)

            # Then: WTG action/condition/call bodies have their own TSV artifact.
            eca_path = os.path.join(out, "触发器ECA.tsv")
            self.assertTrue(os.path.exists(eca_path))
            with open(eca_path, encoding="utf-8") as handle:
                text = handle.read()
            self.assertIn("CreateNUnitsAtLoc", text)
            self.assertIn("OperatorCompareInteger", text)


if __name__ == "__main__":
    unittest.main()
