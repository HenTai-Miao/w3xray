"""Real WTG fixture coverage for schema-driven ECA parsing."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import struct

from w3xtool.trigger_schema import (
    TriggerFunctionKind,
    TriggerFunctionSchema,
    TriggerSchema,
    parse_trigger_schema,
)
from w3xtool.api import MapData
from w3xtool.load_context import MapLoadContext
from w3xtool.map_extras import add_trigger_summary
from w3xtool.wtg import TriggerEcaFunction, parse_wtg

FIXTURE_ROOT = Path(__file__).with_name("fixtures")
CLASSIC_FIXTURE = FIXTURE_ROOT / "wtg" / "classic-wc3libs-war3map.wtg"
REFORGED_FIXTURE = FIXTURE_ROOT / "wtg" / "reforged-war3net-map-script-builder.wtg"


def test_wc3libs_real_wtg_never_silently_accepts_bad_parameter_values() -> None:
    # Given: a real classic WTG whose first KillUnit action has one unit parameter.
    raw = CLASSIC_FIXTURE.read_bytes()
    schema = _load_fixture_schema()

    # When: the WTG file is parsed with real TriggerData signatures.
    summary = parse_wtg(raw, schema)

    # Then: parameters are schema-counted and never shifted into string bytes.
    assert not summary.parse_failures
    assert not summary.missing_schema_functions
    assert summary.eca_functions
    assert all(0 <= param.parameter_type <= 3 for node in _walk_eca(summary.eca_functions) for param in node.parameters)
    first = summary.eca_functions[0]
    assert first.name == "KillUnit"
    assert first.parameters[0].value == "gg_unit_uKoM_0115"


def test_wtg_without_schema_keeps_headers_and_reports_missing_schema() -> None:
    # Given: a real Reforged WTG and no TriggerData schema.
    raw = REFORGED_FIXTURE.read_bytes()

    # When: only header/tree metadata can be safely read.
    summary = parse_wtg(raw)

    # Then: the parser fails closed instead of guessing parameter bytes.
    assert summary.triggers
    assert summary.eca_functions == ()
    assert summary.missing_schema_functions
    assert summary.missing_schema_functions[0].trigger_name == "Test"
    assert summary.missing_schema_functions[0].function_name == "CommentString"
    assert not summary.parse_failures


def test_war3net_reforged_real_wtg_parses_nested_functions_children_and_variables() -> None:
    # Given: a real Reforged WTG with variables, code/bool params, and child groups.
    raw = REFORGED_FIXTURE.read_bytes()
    schema = _load_fixture_schema()

    # When: the WTG file is parsed with real TriggerData signatures.
    summary = parse_wtg(raw, schema)

    # Then: Reforged object-tree metadata and ECA structure are preserved.
    assert not summary.parse_failures
    assert not summary.missing_schema_functions
    assert summary.is_reforged
    assert summary.variable_count == 9
    assert summary.variables[0].name == "Untitled_Variable_001"
    assert summary.variables[0].type_name == "string"
    assert summary.variables[0].array_size == 1
    assert summary.variables[5].type_name == "integer"
    assert summary.variables[5].array_size == 0
    assert [trigger.name for trigger in summary.triggers] == ["Test"]
    names = [node.name for node in _walk_eca(summary.eca_functions)]
    assert len(summary.eca_functions) == 10
    assert "IfThenElse" in names
    assert "GetBooleanAnd" in names
    assert "WaitForCondition" in names
    grouped = _find(summary.eca_functions, "IfThenElseMultiple")
    assert grouped.children
    assert {child.branch for child in grouped.children} >= {1, 2}


def test_array_indexer_parameter_reads_recursive_index_parameter() -> None:
    # Given: a minimal spec-shaped WTG parameter with haveArrayIndexer=1.
    schema = _schema_for_action("UseArray", ("integer",))
    raw = _classic_wtg_with_action(
        "UseArray",
        _i(1) + _z("Numbers") + _i(0) + _i(1) + _i(0) + _z("3") + _i(0) + _i(0) + _i(0),
    )

    # When: the action parameter is parsed.
    summary = parse_wtg(raw, schema)

    # Then: the array index is attached to the variable parameter without shifting.
    assert not summary.parse_failures
    param = summary.eca_functions[0].parameters[0]
    assert param.parameter_type == 1
    assert param.have_array_indexer == 1
    assert param.array_indexer is not None
    assert param.array_indexer.value == "3"


def test_invalid_parameter_type_records_parse_failure_with_trigger_function_and_offset() -> None:
    # Given: a schema-known function whose parameter type is outside the WTG enum.
    schema = _schema_for_action("BadParam", ("integer",))
    raw = _classic_wtg_with_action("BadParam", _i(999) + _z("bad") + _i(0) + _i(0) + _i(0))

    # When: the malformed function is parsed.
    summary = parse_wtg(raw, schema)

    # Then: parsing stops with a structured diagnostic instead of guessing ahead.
    assert summary.eca_functions == ()
    assert len(summary.parse_failures) == 1
    failure = summary.parse_failures[0]
    assert failure.trigger_name == "Test"
    assert failure.function_name == "BadParam"
    assert failure.reason == "invalid parameter type 999"
    assert failure.offset > 0


def test_add_trigger_summary_uses_load_context_trigger_schema() -> None:
    # Given: a map load context carrying the selected TriggerData schema.
    md = MapData(path="x.w3x", name="x")
    archive = _Archive({"war3map.wtg": CLASSIC_FIXTURE.read_bytes()})
    context = MapLoadContext(trigger_schema=_load_fixture_schema())

    # When: optional map extras load the WTG summary.
    add_trigger_summary(md, archive, context)

    # Then: the summary contains expanded ECA functions, not header-only diagnostics.
    assert md.trigger_summary is not None
    assert md.trigger_summary.eca_functions
    assert not md.trigger_summary.missing_schema_functions


def _load_fixture_schema() -> TriggerSchema:
    trigger_dir = FIXTURE_ROOT / "trigger"
    return parse_trigger_schema(
        (trigger_dir / "TriggerData.txt").read_text(encoding="utf-8"),
        (trigger_dir / "TriggerStrings.txt").read_text(encoding="utf-8"),
    )


def _walk_eca(nodes: tuple[TriggerEcaFunction, ...]) -> Iterator[TriggerEcaFunction]:
    for node in nodes:
        yield node
        for parameter in node.parameters:
            if parameter.nested_function is not None:
                yield from _walk_eca((parameter.nested_function,))
        yield from _walk_eca(node.children)


def _find(nodes: tuple[TriggerEcaFunction, ...], name: str) -> TriggerEcaFunction:
    for node in _walk_eca(nodes):
        if node.name == name:
            return node
    raise AssertionError(name)


def _schema_for_action(name: str, parameters: tuple[str, ...]) -> TriggerSchema:
    return TriggerSchema({
        (TriggerFunctionKind.ACTION, name.lower()): TriggerFunctionSchema(
            kind=TriggerFunctionKind.ACTION,
            name=name,
            category="",
            return_type=None,
            parameter_types=parameters,
            display_name=name,
            template=None,
        ),
    })


def _classic_wtg_with_action(name: str, parameter: bytes) -> bytes:
    return (
        b"WTG!" + _i(7)
        + _i(1) + _i(42) + _z("System") + _i(0)
        + _i(0)
        + _i(0)
        + _i(1)
        + _z("Test") + _z("") + _i(0) + _i(1) + _i(0) + _i(0) + _i(0) + _i(42) + _i(1)
        + _i(2) + _z(name) + _i(1) + parameter
    )


def _i(value: int) -> bytes:
    return struct.pack("<i", value)


def _z(value: str) -> bytes:
    return value.encode("utf-8") + b"\x00"


class _Archive:
    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files

    def has_file(self, name: str) -> bool:
        return name in self._files

    def read_file(self, name: str) -> bytes:
        return self._files[name]
