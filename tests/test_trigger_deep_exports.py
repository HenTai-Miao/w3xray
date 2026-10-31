"""Every parsed WTG level survives semantics, TSV and reward consumers."""

import pytest

from gametool.item_relation_models import RelationConfidence
from gametool.item_relation_wtg import build_wtg_item_relations
from gametool.map_data import GameObject, MapData
from gametool.trigger_exports import format_trigger_eca_tsv
from gametool.triggerdata import render_eca_semantic
from gametool.wtg_models import (
    TriggerEcaFunction,
    TriggerEcaParameter,
    TriggerTreeSummary,
)


def _function(
    name: str,
    *,
    parameters: tuple[TriggerEcaParameter, ...] = (),
    children: tuple[TriggerEcaFunction, ...] = (),
    ordinal: int = 0,
) -> TriggerEcaFunction:
    return TriggerEcaFunction(
        "完整深层触发",
        2,
        name,
        True,
        parameters,
        children,
        ordinal=ordinal,
        branch=2,
        source_offset=ordinal * 16,
    )


def _map(function: TriggerEcaFunction, code: str = "I001") -> MapData:
    md = MapData(path="synthetic.w3x", name="深层触发")
    md.trigger_summary = TriggerTreeSummary(
        7, False, 0, 0, 1, 0, 0, (), (), (), (function,)
    )
    item = GameObject("物品", "w3t", code, code, "末层奖励", True)
    md.objects = {"物品": [item]}
    md.obj_index = {code: item}
    return md


@pytest.mark.parametrize("kind", ["children", "nested", "array"])
def test_deep_tree_exports_every_level_and_retains_final_reward(kind: str) -> None:
    depth = 1201
    leaf = _function(
        "CreateItem",
        parameters=(
            TriggerEcaParameter(0, "I001", expected_type="itemcode"),
            TriggerEcaParameter(0, "0"),
            TriggerEcaParameter(0, "0"),
        ),
        ordinal=depth,
    )
    root = leaf
    expected = "CreateItem(I001, 0, 0)"
    if kind == "array":
        parameter = TriggerEcaParameter(2, "leaf", nested_function=leaf)
        for index in range(depth - 1, -1, -1):
            parameter = TriggerEcaParameter(1, f"a{index}", array_indexer=parameter)
            expected = f"a{index}[{expected}]"
        root = _function("UseValue", parameters=(parameter,))
        expected = f"UseValue({expected})"
    else:
        for index in range(depth - 1, -1, -1):
            root = _function(
                f"f{index}",
                parameters=(TriggerEcaParameter(2, "nested", nested_function=root),)
                if kind == "nested"
                else (),
                children=(root,) if kind == "children" else (),
                ordinal=index,
            )
            if kind == "nested":
                expected = f"f{index}({expected})"
        if kind == "children":
            expected = "f0"
    md = _map(root)
    assert render_eca_semantic(root, None) == expected
    rows = [
        line.split("\t")
        for line in format_trigger_eca_tsv(md.trigger_summary).splitlines()
    ]
    assert all(len(row) == 13 for row in rows)
    assert rows[1][9] == expected
    kind_rows = [row for row in rows[1:] if row[2] in {"顶层函数", "子ECA", "嵌套函数"}]
    assert len(kind_rows) == (2 if kind == "array" else depth + 1)
    assert kind_rows[-1][4] == "CreateItem"
    assert kind_rows[-1][10:12] == [str(depth), "2"]
    assert max(int(row[1]) for row in rows[1:]) == depth + (kind == "array")
    (reward,) = build_wtg_item_relations(md)
    assert reward.item.object_id == "I001"
    assert reward.evidence.offset == depth * 16
    assert reward.evidence.trigger == "完整深层触发"
    assert reward.confidence is RelationConfidence.CONFIRMED


@pytest.mark.parametrize("code", ["I-01", "é001", " I01", "I01 ", "0001", "(x),"])
def test_wtg_itemcode_preserves_exact_four_latin1_bytes(code: str) -> None:
    action = _function(
        "CreateItem",
        parameters=(TriggerEcaParameter(0, code, expected_type="itemcode"),),
    )
    (row,) = build_wtg_item_relations(_map(action, code))
    assert row.item.object_id == code
    assert row.confidence is RelationConfidence.CONFIRMED
