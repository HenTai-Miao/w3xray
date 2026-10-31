"""Encoded WTG trees are bounded by bytes, not Python's recursion limit."""

from __future__ import annotations

import struct

import pytest

from gametool.trigger_schema import (
    TriggerFunctionKind,
    TriggerFunctionSchema,
    TriggerSchema,
)
from gametool.wtg import parse_wtg


def _i(value: int) -> bytes:
    return struct.pack("<i", value)


def _z(text: str) -> bytes:
    return text.encode() + b"\0"


def _function(kind: int, name: str, *, branch: int | None = None) -> bytes:
    return _i(kind) + (b"" if branch is None else _i(branch)) + _z(name) + _i(1)


def _schema(parameter_types: tuple[str, ...]) -> TriggerSchema:
    return TriggerSchema(
        {
            (kind, name.lower()): TriggerFunctionSchema(
                kind, name, "", None, parameter_types, name, None
            )
            for kind, name in (
                (TriggerFunctionKind.ACTION, "Do"),
                (TriggerFunctionKind.CALL, "Read"),
            )
        }
    )


def _classic(body: bytes) -> bytes:
    trigger = _z("Deep") + _z("") + b"".join(_i(n) for n in (0, 1, 0, 0, 1, 0, 1))
    return b"WTG!" + _i(7) + _i(0) * 3 + _i(1) + trigger + body


def _reforged(body: bytes) -> bytes:
    counts = b"".join(
        _i(1 if kind == 8 else 0) + _i(0) for kind in (1, 2, 4, 8, 16, 32, 64, 128)
    )
    trigger = (
        _i(8) + _z("Deep") + _z("") + b"".join(_i(n) for n in (0, 1, 1, 0, 0, 1, 0, 1))
    )
    return (
        b"WTG!"
        + struct.pack("<I", 0x80000004)
        + _i(7)
        + counts
        + _i(0) * 2
        + _i(1)
        + trigger
        + body
    )


@pytest.mark.parametrize("reforged", (False, True))
@pytest.mark.parametrize("kind", ("children", "nested", "array"))
def test_wtg_preserves_every_encoded_level_beyond_python_recursion(
    kind: str, reforged: bool
) -> None:
    depth = 1201
    root = _function(2, "Do")
    scalar = _i(0) + _z("9") + _i(0) * 2
    if kind == "children":
        child = _function(2, "Do", branch=17)
        body = root + _i(1) + (child + _i(1)) * (depth - 1) + child + _i(0)
        schema = _schema(())
    elif kind == "nested":
        parameter = _i(2) + _z("nested") + _i(1)
        nested = _function(3, "Read")
        body = (
            root
            + parameter
            + (nested + parameter) * (depth - 1)
            + nested
            + scalar
            + _i(0)
            + (_i(0) * 2) * depth
        )
        schema = _schema(("integer",))
    else:
        parameter = _i(1) + _z("Values") + _i(0) + _i(1)
        body = root + parameter * depth + scalar + _i(0)
        schema = _schema(("integer",))

    wrap = _reforged if reforged else _classic
    summary = parse_wtg(wrap(body), schema)

    assert not summary.has_unexpanded_functions
    assert len(summary.eca_functions) == 1
    function = summary.eca_functions[0]
    if kind == "array":
        parameter = function.parameters[0]
        for _ in range(depth):
            assert parameter.value == "Values"
            assert parameter.array_indexer is not None
            assert parameter.array_indexer.source_offset > parameter.source_offset
            parameter = parameter.array_indexer
        assert parameter.value == "9"
        assert parameter.array_indexer is None
    else:
        for expected_depth in range(depth + 1):
            assert function.depth == expected_depth
            if expected_depth == depth:
                break
            if kind == "children":
                following = function.children[0]
                assert following.branch == 17
                assert following.ordinal == 1
            else:
                following = function.parameters[0].nested_function
                assert following is not None
                assert following.ordinal == 0
            assert following.source_offset > function.source_offset
            function = following
        assert not function.children

    incomplete = parse_wtg(wrap(body[:-1]), schema)
    assert incomplete.has_unexpanded_functions
    assert incomplete.parse_failures
    assert incomplete.parse_failures[0].offset <= len(wrap(body[:-1]))
