"""Lossless text-object parser contracts."""

from __future__ import annotations

from w3xtool.textobj import parse_text_objects


def test_text_object_rhs_preserves_leading_trailing_spaces_tabs_and_empty_value() -> (
    None
):
    # Given: object text contains significant RHS whitespace and one explicit empty field.
    source = "[I001]\r\nUbertip=  前导\t正文  \r\nDescription=\r\n"

    # When: the text object is parsed.
    records = parse_text_objects(source)

    # Then: only syntax is removed; value bytes decoded to characters remain intact.
    assert records == [
        ("I001", {"Ubertip": "  前导\t正文  ", "Description": ""}),
    ]


def test_text_object_uses_only_the_first_equals_as_separator() -> None:
    # Given / When: the value itself contains equals signs.
    records = parse_text_objects("[I001]\nUbertip=a=b=c\n")

    # Then: the complete RHS survives.
    assert records[0][1]["Ubertip"] == "a=b=c"
