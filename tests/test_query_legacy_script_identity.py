"""Legacy JASS clue adapters retain lexical and case-sensitive identities."""

from pathlib import Path

import pytest

from gametool import pack_query_cli as queries


def _death(code: str = "n001", item: str = "I001", extra: str = "") -> str:
    return (
        "function Trig_BossConditions takes nothing returns boolean\n"
        f"return GetUnitTypeId(GetDyingUnit())=='{code}'\n"
        "endfunction\n"
        "function Trig_BossActions takes nothing returns nothing\n"
        + extra
        + f"call CreateItem('{item}',1,2)\nendfunction\n"
    )


def test_direct_death_item_and_unit_lookups_are_case_sensitive() -> None:
    script = _death()
    assert queries._script_direct_death_drops(script, "I001", {}, {})
    assert not queries._script_direct_death_drops(script, "i001", {}, {})
    assert queries._script_unit_direct_drops(script, "n001", {}, {})
    assert not queries._script_unit_direct_drops(script, "N001", {}, {})


@pytest.mark.parametrize(
    "decoy",
    [
        "// call CreateItem('I002',3,4)\n",
        "call BJDebugMsg(\"CreateItem('I002',3,4)\")\n",
    ],
)
def test_direct_death_comments_and_text_are_not_drop_evidence(decoy: str) -> None:
    script = _death(extra=decoy)
    assert not queries._script_direct_death_drops(script, "I002", {}, {})
    assert "I002" not in "\n".join(
        queries.script_death_drop_lines(script, lambda code: code)
    )
    assert "I001" in "\n".join(
        queries.script_death_drop_lines(script, lambda code: code)
    )


def test_commented_function_is_not_a_death_block() -> None:
    script = "\n".join("// " + line for line in _death().splitlines())
    assert not queries._death_blocks(script)
    assert not queries.script_death_drop_lines(script, lambda code: code)


def test_death_condition_raw_source_is_preserved() -> None:
    script = _death().replace("return GetUnit", "// exact source\n  return GetUnit")
    text = "\n".join(queries._script_unit_direct_drops(script, "n001", {}, {}))
    assert "// exact source\n  return GetUnit" in text


def test_call_boundaries_ignore_parentheses_in_string_literals() -> None:
    body = "call CreateItem('I001', StringLength(\")\"),2)\ncall Other()"
    assert queries._balanced_call(body, 0) == body.splitlines()[0]


def test_item_use_identity_is_case_sensitive_and_ignores_commented_grants() -> None:
    script = (
        "function UseActions takes nothing returns nothing\n"
        "if GetItemTypeId(GetManipulatedItem())=='I001' then\n"
        "// call CreateItem('I003',3,4)\n"
        "call CreateItem('I002',1,2)\nendif\nendfunction\n"
        "function Init takes nothing returns nothing\n"
        "local trigger t=CreateTrigger()\n"
        "call TriggerAddAction(t,function UseActions)\nendfunction\n"
    )

    def name_of(code):
        return code

    text = "\n".join(queries._item_trigger_grant_lines(script, ["I001"], name_of))
    assert "I002" in text and "I003" not in text
    assert not queries._item_trigger_grant_lines(script, ["i001"], name_of)


def test_pool_unit_condition_uses_exact_identity(tmp_path: Path) -> None:
    script = (
        "call ItemPoolAddItemType(udg_Pool[1],'I001',1)\n"
        + _death(extra="call PlaceRandomItem(udg_Pool[1],1,2)\n")
        + "function Init takes nothing returns nothing\n"
        "local trigger t=CreateTrigger()\n"
        "call TriggerAddCondition(t,Condition(function Trig_BossConditions))\n"
        "call TriggerAddAction(t,function Trig_BossActions)\nendfunction\n"
    )
    assert queries._script_pool_drops(tmp_path, "n001", script=script)
    assert not queries._script_pool_drops(tmp_path, "N001", script=script)


def test_hex_rawcodes_retain_latin1_identity() -> None:
    assert queries._fourcc("", "C4303031") == "Ä001"
