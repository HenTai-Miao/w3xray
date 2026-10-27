"""Static literal decoding with separate text, byte and source-encoding evidence.

Lua numeric/hex escapes append bytes; Unicode escapes append UTF-8. Decoding
each byte as a Unicode code point would turn UTF-8 C3 A9 into mojibake. Unknown
source encoding therefore never promotes non-ASCII byte escapes to text.
"""

from __future__ import annotations

from collections.abc import Sequence
import codecs
from dataclasses import dataclass
import re

_LONG = re.compile(r"\[(=*)\[")
_HEX = re.compile(r"[0-9a-fA-F]+")
_BASIC = {"\\": "\\", '"': '"', "'": "'"}
_TEXT = {**_BASIC, "n": "\n", "r": "\r", "t": "\t"}
_LUA = {**_TEXT, "a": "\a", "b": "\b", "f": "\f", "v": "\v"}


@dataclass(frozen=True, slots=True)
class ScriptLiteralValue:
    value: str | None
    raw_bytes: bytes | None
    complete: bool
    diagnostics: tuple[str, ...]
    encoding: str = ""
    source_encoding: str = ""


@dataclass(frozen=True, slots=True)
class _Part:
    text: str | None
    raw_bytes: bytes | None = None
    byte_escape: bool = False


def _parts(
    raw: str, lua: bool | None, jass_text_escapes: bool
) -> tuple[list[_Part], list[str]]:
    literal = raw.strip()
    opening = _LONG.match(literal) if lua is not False else None
    if opening is not None:
        close = "]" + opening.group(1) + "]"
        end = literal.find(close, opening.end())
        if end < 0 or end + len(close) != len(literal):
            return [], ["incomplete or non-literal long-bracket string"]
        body = literal[opening.end() : end]
        if body.startswith(("\r\n", "\n\r")):
            body = body[2:]
        elif body.startswith(("\r", "\n")):
            body = body[1:]
        if lua is True:
            body = re.sub(r"\r\n|\n\r|\r", "\n", body)
        return [_Part(body)], []
    if len(literal) < 2 or literal[0] not in {"'", '"'} or literal[-1] != literal[0]:
        return [], ["not a complete quoted string literal"]
    quote = literal[0]
    body = literal[1:-1]
    parts: list[_Part] = []
    diagnostics: list[str] = []
    cursor = plain_start = 0
    while cursor < len(body):
        char = body[cursor]
        if char == quote:
            return [], ["unescaped quote inside literal; expression is not one string"]
        if lua is True and char in {"\r", "\n"}:
            return [], ["unescaped newline in a Lua short string"]
        if char != "\\":
            cursor += 1
            continue
        if cursor > plain_start:
            parts.append(_Part(body[plain_start:cursor]))
        start = cursor
        cursor += 1
        if cursor >= len(body):
            return [], ["incomplete final string escape"]
        escape = body[cursor]
        cursor += 1
        escapes = _LUA if lua is True else _TEXT if jass_text_escapes else _BASIC
        if escape in escapes:
            value = escapes[escape]
            parts.append(_Part(value, value.encode("ascii")))
        elif lua is True and escape == "z":
            while cursor < len(body) and body[cursor] in " \f\n\r\t\v":
                cursor += 1
        elif lua is True and escape in {"\r", "\n"}:
            if (
                cursor < len(body)
                and body[cursor] in {"\r", "\n"}
                and body[cursor] != escape
            ):
                cursor += 1
            parts.append(_Part("\n", b"\n"))
        elif lua is True and "0" <= escape <= "9":
            while (
                cursor < len(body) and cursor < start + 4 and "0" <= body[cursor] <= "9"
            ):
                cursor += 1
            value = int(body[start + 1 : cursor])
            if value > 255:
                diagnostics.append(
                    f"invalid Lua byte escape at literal offset {start + 1}"
                )
            else:
                parts.append(_Part(None, bytes((value,)), True))
        elif lua is True and escape == "x":
            digits = body[cursor : cursor + 2]
            if len(digits) != 2 or _HEX.fullmatch(digits) is None:
                diagnostics.append(
                    f"invalid Lua hex escape at literal offset {start + 1}"
                )
            else:
                parts.append(_Part(None, bytes((int(digits, 16),)), True))
                cursor += 2
        elif lua is True and escape == "u" and body[cursor : cursor + 1] == "{":
            end = body.find("}", cursor + 1)
            digits = body[cursor + 1 : end] if end >= 0 else ""
            value = int(digits, 16) if _HEX.fullmatch(digits) is not None else -1
            if 0 <= value <= 0x10FFFF and not 0xD800 <= value <= 0xDFFF:
                text = chr(value)
                parts.append(_Part(text, text.encode("utf-8")))
                cursor = end + 1
            else:
                diagnostics.append(
                    f"unsupported Lua Unicode escape at literal offset {start + 1}"
                )
        elif lua is not True and not jass_text_escapes:
            # Preserve the project's existing JASS resource-path convention.
            parts.append(_Part(body[start:cursor]))
        else:
            diagnostics.append(
                f"unknown string escape at literal offset {start + 1}: {body[start:cursor]!r}"
            )
        plain_start = cursor
    if plain_start < len(body):
        parts.append(_Part(body[plain_start:]))
    return parts, diagnostics


def decode_script_literal_sequence(
    literals: Sequence[str],
    *,
    lua: bool | None,
    encoding: str = "",
    jass_text_escapes: bool = False,
) -> ScriptLiteralValue:
    """Decode one proved literal concatenation, preserving cross-literal bytes.

    encoding='' means source bytes are not known: ordinary decoded Unicode
    remains text evidence, ASCII escapes are invariant, and non-ASCII byte
    escapes retain bytes without selecting a charset. UTF-16 is a source-text
    transport; Lua's resulting byte string uses UTF-8 in that transport.
    """
    parts: list[_Part] = []
    diagnostics: list[str] = []
    for literal in literals:
        decoded, notes = _parts(literal, lua, jass_text_escapes)
        parts.extend(decoded)
        diagnostics.extend(notes)
    source_encoding = encoding
    try:
        codec = codecs.lookup(encoding).name if encoding else ""
    except LookupError as exc:
        return ScriptLiteralValue(None, None, False, (str(exc),), "", source_encoding)
    if codec.startswith("utf-16") or codec == "utf-8-sig":
        codec = "utf-8"
    if diagnostics:
        return ScriptLiteralValue(
            None, None, False, tuple(dict.fromkeys(diagnostics)), codec, source_encoding
        )
    if codec:
        payload: bytes | None = None
        try:
            payload = b"".join(
                part.raw_bytes
                if part.raw_bytes is not None
                else (part.text or "").encode(codec)
                for part in parts
            )
            unicode_bytes = any(
                part.text is not None
                and not part.text.isascii()
                and part.raw_bytes is not None
                for part in parts
            )
            nonascii_source_or_bytes = any(
                (
                    part.raw_bytes is None
                    and part.text is not None
                    and not part.text.isascii()
                )
                or (
                    part.text is None
                    and part.raw_bytes is not None
                    and not part.raw_bytes.isascii()
                )
                for part in parts
            )
            if lua is True and unicode_bytes and codec != "utf-8":
                if nonascii_source_or_bytes:
                    return ScriptLiteralValue(
                        None,
                        payload,
                        False,
                        (
                            "Lua Unicode escapes emit UTF-8 alongside non-ASCII bytes in another source encoding; text encoding is ambiguous",
                        ),
                        "",
                        source_encoding,
                    )
                codec = "utf-8"
            value = payload.decode(codec)
        except (UnicodeError, LookupError) as exc:
            return ScriptLiteralValue(
                None,
                payload,
                False,
                (f"literal byte string is not valid {codec}: {exc}",),
                codec,
                source_encoding,
            )
        return ScriptLiteralValue(value, payload, True, (), codec, source_encoding)
    known_bytes: list[bytes] = []
    logical: list[str] = []
    all_bytes_known = True
    nonascii_byte_escape = False
    for part in parts:
        if part.text is not None:
            logical.append(part.text)
        elif part.raw_bytes is not None:
            if part.raw_bytes.isascii():
                logical.append(part.raw_bytes.decode("ascii"))
            else:
                nonascii_byte_escape = True
        if part.raw_bytes is not None:
            known_bytes.append(part.raw_bytes)
        elif part.text is not None and part.text.isascii():
            known_bytes.append(part.text.encode("ascii"))
        else:
            all_bytes_known = False
    payload = b"".join(known_bytes) if all_bytes_known else None
    if nonascii_byte_escape:
        return ScriptLiteralValue(
            None,
            payload,
            False,
            (
                "non-ASCII byte escapes have unknown source/text encoding; raw bytes retained",
            ),
            "",
            source_encoding,
        )
    proved_codec = (
        "ascii"
        if payload is not None and payload.isascii()
        else "utf-8"
        if payload is not None
        else ""
    )
    return ScriptLiteralValue(
        "".join(logical), payload, True, (), proved_codec, source_encoding
    )


def decode_script_literal(
    raw: str,
    *,
    lua: bool | None,
    encoding: str = "",
    jass_text_escapes: bool = False,
) -> ScriptLiteralValue:
    """Decode exactly one source literal without execution or charset fallback."""
    return decode_script_literal_sequence(
        (raw,), lua=lua, encoding=encoding, jass_text_escapes=jass_text_escapes
    )
