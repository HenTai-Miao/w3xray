"""Schema parsing tests for real TriggerData/TriggerStrings fixtures."""

from __future__ import annotations

from pathlib import Path

from w3xtool.trigger_schema import (
    TriggerFunctionKind,
    parse_trigger_schema,
)


def _fixture(name: str) -> str:
    return Path(__file__).with_name("fixtures").joinpath("trigger", name).read_text(encoding="utf-8")


def test_real_trigger_data_signature_and_trigger_strings_template() -> None:
    data = _fixture("TriggerData.txt")
    strings = _fixture("TriggerStrings.txt")

    schema = parse_trigger_schema(data, strings)

    action = schema.require(TriggerFunctionKind.ACTION, "DisplayTextToForce")
    assert action.parameter_types == ("force", "StringExt")
    assert action.display_name


def test_missing_trigger_strings_keeps_signature_without_fake_template() -> None:
    schema = parse_trigger_schema("[TriggerActions]\nDisplayTextToForce=0,force,StringExt\n", "")

    action = schema.require(TriggerFunctionKind.ACTION, "DisplayTextToForce")
    assert action.parameter_types == ("force", "StringExt")
    assert action.template is None
