"""Schema parsing tests for real TriggerData/TriggerStrings fixtures."""

from __future__ import annotations

from collections.abc import Mapping
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from unittest.mock import patch

from w3xtool.trigger_schema import (
    TriggerFunctionKind,
    parse_trigger_schema,
)
from w3xtool.triggerdata import load_trigger_schema_from_source


_MINIMAL_TRIGGER_DATA: Final = b"[TriggerActions]\nDisplayTextToForce=0,force,StringExt\n"
_MINIMAL_TRIGGER_STRINGS: Final = (
    b"[TriggerActionStrings]\n"
    b'DisplayTextToForce="Text Message (Auto-Timed)"\n'
    b'DisplayTextToForce="Display to ",~Player Group," the text: ",~Text\n'
)


@dataclass(frozen=True, slots=True)
class _Source:
    files: Mapping[str, bytes]
    failing_reads: frozenset[str] = frozenset()

    def has_file(self, name: str) -> bool:
        return name in self.files

    def read_file(self, name: str) -> bytes:
        if name in self.failing_reads:
            raise OSError(name)
        return self.files[name]


def _fixture(name: str) -> str:
    return Path(__file__).with_name("fixtures").joinpath("trigger", name).read_text(encoding="utf-8")


def test_real_trigger_data_signature_and_trigger_strings_template() -> None:
    data = _fixture("TriggerData.txt")
    strings = _fixture("TriggerStrings.txt")

    schema = parse_trigger_schema(data, strings)

    action = schema.require(TriggerFunctionKind.ACTION, "DisplayTextToForce")
    assert action.parameter_types == ("force", "StringExt")
    assert action.display_name == "Text Message (Auto-Timed)"
    assert action.template == "Display to %1 the text: %2"


def test_real_nothing_signatures_and_trigger_call_offsets() -> None:
    schema = parse_trigger_schema(_fixture("TriggerData.txt"), _fixture("TriggerStrings.txt"))

    event = schema.require(TriggerFunctionKind.EVENT, "MapInitializationEvent")
    action = schema.require(TriggerFunctionKind.ACTION, "IfThenElseMultiple")
    call = schema.require(TriggerFunctionKind.CALL, "IsDestructableAliveBJ")

    assert event.parameter_types == ()
    assert action.parameter_types == ()
    assert call.return_type == "boolean"
    assert call.parameter_types == ("destructable",)


def test_missing_trigger_strings_keeps_signature_without_fake_template() -> None:
    schema = parse_trigger_schema("[TriggerActions]\nDisplayTextToForce=0,force,StringExt\n", "")

    action = schema.require(TriggerFunctionKind.ACTION, "DisplayTextToForce")
    assert action.parameter_types == ("force", "StringExt")
    assert action.template is None


def test_source_loading_keeps_signature_when_trigger_strings_is_missing() -> None:
    schema = load_trigger_schema_from_source(_Source({"TriggerData.txt": _MINIMAL_TRIGGER_DATA}))

    assert schema is not None
    action = schema.require(TriggerFunctionKind.ACTION, "DisplayTextToForce")
    assert action.parameter_types == ("force", "StringExt")
    assert action.template is None


def test_source_loading_keeps_signature_when_trigger_strings_read_fails() -> None:
    source = _Source(
        {
            "TriggerData.txt": _MINIMAL_TRIGGER_DATA,
            "TriggerStrings.txt": _MINIMAL_TRIGGER_STRINGS,
        },
        frozenset({"TriggerStrings.txt"}),
    )

    schema = load_trigger_schema_from_source(source)

    assert schema is not None
    action = schema.require(TriggerFunctionKind.ACTION, "DisplayTextToForce")
    assert action.parameter_types == ("force", "StringExt")
    assert action.template is None


def test_source_loading_returns_none_when_trigger_data_is_missing() -> None:
    assert load_trigger_schema_from_source(_Source({})) is None


def test_source_loading_returns_none_when_trigger_data_read_fails() -> None:
    source = _Source(
        {"TriggerData.txt": _MINIMAL_TRIGGER_DATA},
        frozenset({"TriggerData.txt"}),
    )

    assert load_trigger_schema_from_source(source) is None


def test_source_loading_returns_none_for_empty_trigger_signature() -> None:
    source = _Source({"TriggerData.txt": b"[TriggerActions]\nDisplayTextToForce=\n"})

    assert load_trigger_schema_from_source(source) is None


def test_source_loading_returns_none_for_unicode_decode_failure() -> None:
    source = _Source({"TriggerData.txt": _MINIMAL_TRIGGER_DATA})

    with patch(
        "w3xtool.triggerdata.decode_warcraft_string",
        side_effect=UnicodeError("invalid trigger metadata encoding"),
    ):
        assert load_trigger_schema_from_source(source) is None


def test_source_loading_returns_none_for_value_parse_failure() -> None:
    source = _Source({"TriggerData.txt": _MINIMAL_TRIGGER_DATA})

    with patch(
        "w3xtool.triggerdata.parse_trigger_schema",
        side_effect=ValueError("invalid trigger metadata value"),
    ):
        assert load_trigger_schema_from_source(source) is None


def test_source_loading_returns_none_for_csv_parse_failure() -> None:
    source = _Source({"TriggerData.txt": _MINIMAL_TRIGGER_DATA})

    with patch(
        "w3xtool.triggerdata.parse_trigger_schema",
        side_effect=csv.Error("invalid trigger metadata CSV"),
    ):
        assert load_trigger_schema_from_source(source) is None
