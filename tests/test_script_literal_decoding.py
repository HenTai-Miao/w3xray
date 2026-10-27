"""Shared Lua byte-string decoding, with explicit unknown encoding evidence."""

from __future__ import annotations

import pytest

from gametool.script_literal_decoding import (
    decode_script_literal,
    decode_script_literal_sequence,
)


@pytest.mark.parametrize("raw", (r'"-load \xC3\xA9ABC"', r'"-load \195\169ABC"'))
def test_utf8_byte_escapes_are_decoded_as_one_byte_buffer(raw: str) -> None:
    result = decode_script_literal(raw, lua=True, encoding="utf-8")
    assert result.complete and result.value == "-load éABC"
    assert result.raw_bytes == "-load éABC".encode()
    assert result.encoding == result.source_encoding == "utf-8"


def test_byte_escape_stream_can_cross_static_literal_boundaries() -> None:
    result = decode_script_literal_sequence(
        (r'"-load \xC3"', r'"\xA9ABC"'), lua=True, encoding="utf-8"
    )
    assert result.complete and result.value == "-load éABC"
    assert result.raw_bytes == b"-load \xc3\xa9ABC"


def test_invalid_utf8_keeps_known_bytes_and_does_not_claim_text() -> None:
    result = decode_script_literal(r'"-load \xFFABC"', lua=True, encoding="utf-8")
    assert not result.complete and result.value is None
    assert result.raw_bytes == b"-load \xffABC"
    assert result.diagnostics and "utf-8" in result.diagnostics[0]


def test_unknown_source_encoding_keeps_nonascii_bytes_unknown() -> None:
    result = decode_script_literal(r'"-load \195\169ABC"', lua=True)
    assert not result.complete and result.value is None
    assert result.raw_bytes == b"-load \xc3\xa9ABC"
    assert result.encoding == result.source_encoding == ""


def test_source_proved_gb18030_byte_escapes_decode_without_utf8_guess() -> None:
    result = decode_script_literal(r'"-load \xD6\xD0ABC"', lua=True, encoding="gb18030")
    assert result.complete and result.value == "-load 中ABC"
    assert result.raw_bytes == b"-load \xd6\xd0ABC"


def test_unicode_escapes_prove_utf8_without_guessing_the_source_encoding() -> None:
    result = decode_script_literal(r'"-load \u{E9}ABC"', lua=True)
    assert result.complete and result.value == "-load éABC"
    assert result.raw_bytes == b"-load \xc3\xa9ABC"
    assert result.encoding == "utf-8" and result.source_encoding == ""


def test_lua_unicode_escape_emits_utf8_independently_of_source_transport() -> None:
    result = decode_script_literal(r'"-load \u{E9}ABC"', lua=True, encoding="gb18030")
    assert result.complete and result.value == "-load éABC"
    assert result.raw_bytes == b"-load \xc3\xa9ABC"
    assert result.encoding == "utf-8" and result.source_encoding == "gb18030"
    mixed = decode_script_literal(r'"-load 中\u{E9}ABC"', lua=True, encoding="gb18030")
    assert not mixed.complete and mixed.value is None and mixed.raw_bytes is not None
    assert mixed.diagnostics


def test_jass_resource_path_and_text_modes_keep_their_existing_roles() -> None:
    literal = r'"Textures\new.blp"'
    resource = decode_script_literal(literal, lua=False)
    assert resource.complete and resource.value == r"Textures\new.blp"
    text = decode_script_literal(literal, lua=False, jass_text_escapes=True)
    assert text.complete and text.value == "Textures\new.blp"


def test_long_lua_source_preserves_known_text_with_unknown_original_bytes() -> None:
    result = decode_script_literal("[=[\r\n中文\r\nsecond]=]", lua=True)
    assert result.complete and result.value == "中文\nsecond"
    assert result.raw_bytes is None and result.source_encoding == ""
