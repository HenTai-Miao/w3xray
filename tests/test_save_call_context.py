"""Bounded argument parsing for large JASS and Lua scripts."""

from __future__ import annotations

from typing import SupportsIndex, assert_never

from w3xtool.save_call_context import extract_call_args


class _NoOpenEndedSlice(str):
    """Fail when a parser copies the entire remaining script suffix."""

    def __getitem__(
        self,
        key: SupportsIndex
        | slice[SupportsIndex | None, SupportsIndex | None, SupportsIndex | None],
        /,
    ) -> str:
        match key:
            case slice(stop=None):
                raise AssertionError(
                    "argument parsing copied the unrelated script tail"
                )
            case SupportsIndex() | slice():
                return super().__getitem__(key)
            case unreachable:
                assert_never(unreachable)


def test_extract_call_args_does_not_copy_unrelated_script_tail() -> None:
    # Given: one short call is followed by a large unrelated script tail.
    script = _NoOpenEndedSlice("first, nested(second))" + "x" * 100_000)

    # When: the current call arguments are parsed.
    arguments = extract_call_args(script, 0)

    # Then: parsing stops at the call boundary without slicing the whole suffix.
    assert arguments == ("first", "nested(second)")
