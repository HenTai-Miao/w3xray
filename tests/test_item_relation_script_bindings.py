"""Reward evidence preserves native bindings and all four-byte literal identities."""

import pytest
from dataclasses import replace

from gametool import item_relation_scripts
from gametool.item_relation_models import RelationCompleteness, RelationConfidence
from gametool.item_relation_endpoints import resolve_relation_object
from gametool.item_relation_scripts import build_script_call_item_relations
from gametool.map_data import GameObject, MapData
from gametool.script_call_argument_index import (
    ScriptCallArgumentIndex,
    build_script_call_argument_index,
)


def _map(script: str, *, code: str = "I001", lua: bool = True) -> MapData:
    md = MapData(path="synthetic.w3x", name="源码奖励绑定")
    md.scripts = {"war3map.lua" if lua else "war3map.j": script}
    item = GameObject("物品", "w3t", code, code, "源码物品", True)
    md.objects = {"物品": [item]}
    md.obj_index = {code: item}
    return md


@pytest.mark.parametrize(
    "script",
    [
        "local CreateItem=OtherFunction CreateItem(FourCC('I001'),12,34)",
        "function CreateItem(a,x,y) end CreateItem(FourCC('I001'),12,34)",
        "local _ENV=private CreateItem(FourCC('I001'),12,34)",
        "local _G=private _G.CreateItem(FourCC('I001'),12,34)",
        "local FourCC=OtherFunction CreateItem(FourCC('I001'),12,34)",
        "function FourCC(text) return 12 end CreateItem(FourCC('I001'),12,34)",
    ],
)
def test_shadowed_reward_or_code_builder_retains_clue_without_confirmed_position(
    script: str,
) -> None:
    (row,) = build_script_call_item_relations(_map(script))
    assert row.item.object_id == "I001"
    assert row.confidence is RelationConfidence.CLUE
    assert row.completeness is RelationCompleteness.PARTIAL
    assert row.x is None and row.y is None
    assert "绑定" in row.unresolved_reason
    assert "绑定诊断" in row.evidence.raw
    assert "CreateItem(FourCC('I001'),12,34)" in row.evidence.raw


@pytest.mark.parametrize("name", ["CreateItem", "FourCC"])
def test_other_script_global_binding_is_preserved_in_reward_diagnostics(
    name: str,
) -> None:
    md = _map("CreateItem(FourCC('I001'),12,34)")
    md.scripts["custom.lua"] = f"function {name}(value,x,y) return value end"
    (row,) = build_script_call_item_relations(md)
    assert row.confidence is RelationConfidence.CLUE
    assert "custom.lua" in row.evidence.raw
    assert "加载顺序" in row.unresolved_reason


@pytest.mark.parametrize("code", ["I-01", "é001", "I 01", "0001", "(x),"])
@pytest.mark.parametrize("lua", [True, False])
def test_complete_four_byte_literals_are_confirmed_without_whitespace_rewriting(
    code: str, lua: bool
) -> None:
    literal = f"FourCC('{code}')" if lua else f"'{code}'"
    (row,) = build_script_call_item_relations(
        _map(f"CreateItem(({literal}),12,34)", code=code, lua=lua)
    )
    assert row.item.object_id == code
    assert row.confidence is RelationConfidence.CONFIRMED
    assert row.completeness is RelationCompleteness.COMPLETE
    assert (row.x, row.y) == (12, 34)


def test_captured_native_alias_retains_original_call_and_confirmed_reward() -> None:
    script = (
        "local spawn=CreateItem function CreateItem() end spawn(FourCC('I001'),12,34)"
    )
    (row,) = build_script_call_item_relations(_map(script))
    assert row.confidence is RelationConfidence.CONFIRMED
    assert row.evidence.raw == "spawn(FourCC('I001'),12,34)"
    assert row.evidence.offset == script.index("spawn(FourCC")


def test_unknown_language_keeps_candidate_without_standard_function_claim() -> None:
    md = _map("CreateItem('I001',12,34)", lua=False)
    md.scripts = {"unknown.txt": md.scripts["war3map.j"]}
    (row,) = build_script_call_item_relations(md)
    assert row.confidence is RelationConfidence.CLUE
    assert "语言未知" in row.unresolved_reason


def test_lua_raw_string_is_not_promoted_to_integer_item_code() -> None:
    assert not build_script_call_item_relations(_map("CreateItem(('I001'),12,34)"))


def test_explicit_item_does_not_borrow_an_unrelated_unit_base_category() -> None:
    md = _map("CreateItem('hpea',0,0)", code="hpea", lua=False)
    endpoint, resolved = resolve_relation_object(md, "hpea", "物品")
    assert resolved and endpoint.name == "源码物品"
    assert endpoint.fine_category == ""


def test_legacy_argument_offset_recovery_keeps_ambiguous_sources_as_clues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "CreateItem(FourCC('I001'),1,2); CreateItem(FourCC('I001'),1,2)"
    md = _map(text)
    index = build_script_call_argument_index(md)
    legacy = ScriptCallArgumentIndex(
        tuple(replace(row, call_offset=None, summary=text) for row in index.arguments)
    )
    monkeypatch.setattr(
        item_relation_scripts, "build_script_call_argument_index", lambda _md: legacy
    )
    rows = build_script_call_item_relations(md)
    assert len(rows) == 2
    assert all(row.confidence is RelationConfidence.CLUE for row in rows)
    assert all(row.x is None and row.y is None for row in rows)
    assert all(row.evidence.raw.startswith(text) for row in rows)
