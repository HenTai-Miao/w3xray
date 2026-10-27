"""Complete static save-code text carriers; never execute Preload or scripts."""

from __future__ import annotations

import re
import codecs
import hashlib
from bisect import bisect_right
from dataclasses import dataclass, replace

from .script_lexing import script_literals, script_views
from .script_literal_decoding import (
    ScriptLiteralValue,
    decode_script_literal,
    decode_script_literal_sequence,
)

__all__ = (
    "SaveCode",
    "SaveTextCarrier",
    "decode_save_text",
    "extract_save_codes",
    "extract_save_codes_bytes",
    "extract_save_text_carriers",
    "extract_script_save_codes",
)

_PREFIX_RE = re.compile(r"(?<![\w-])[-!][A-Za-z][A-Za-z0-9_-]*")
_CALL_RE = re.compile(r"(?<![\w.:])(?:(?:_G\s*\.\s*)?)([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_CARRIER_ARGUMENTS = {
    "Preload": 0,
    "SetPlayerName": 1,
    "BlzSetAbilityTooltip": 1,
    "BlzSetAbilityExtendedTooltip": 1,
    "BlzSetAbilityActivatedTooltip": 1,
    "BlzSetAbilityActivatedExtendedTooltip": 1,
    "BlzSetAbilityResearchTooltip": 1,
    "BlzSetAbilityResearchExtendedTooltip": 1,
}


@dataclass(frozen=True, slots=True)
class SaveTextCarrier:
    source: str
    carrier: str
    line: int
    offset: int
    end: int
    call_offset: int
    raw: str
    text: str
    encoding: str = ""
    byte_offset: int | None = None
    byte_end: int | None = None
    state: str = "literal-text"
    raw_hex: str = ""
    source_sha256: str = ""
    diagnostics: tuple[str, ...] = ()
    literal_bytes_hex: str | None = None
    literal_encoding: str = ""
    literal_source_encoding: str = ""
    literal_complete: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "carrier": self.carrier,
            "line": self.line,
            "offset": self.offset,
            "end": self.end,
            "call_offset": self.call_offset,
            "raw": self.raw,
            "text": self.text,
            "encoding": self.encoding,
            "byte_offset": self.byte_offset,
            "byte_end": self.byte_end,
            "state": self.state,
            "raw_hex": self.raw_hex,
            "source_sha256": self.source_sha256,
            "diagnostics": list(self.diagnostics),
            "literal_bytes_hex": self.literal_bytes_hex,
            "literal_encoding": self.literal_encoding,
            "literal_source_encoding": self.literal_source_encoding,
            "literal_complete": self.literal_complete,
            "map_validation": "not_performed",
        }


@dataclass(frozen=True, slots=True)
class SaveCode:
    """A text candidate, not a verified password or a current hero state.

    offset/end identify the exact source literal/expression (character offsets).
    Byte offsets are present only when the actual source encoding is known.
    command_offset is an offset within the decoded carrier text.
    """

    code: str
    command: str
    source: str
    line: int
    carrier: str = ""
    offset: int = 0
    end: int = 0
    raw: str = ""
    encoding: str = ""
    byte_offset: int | None = None
    byte_end: int | None = None
    call_offset: int = 0
    command_offset: int = 0
    state: str = "text-candidate"
    raw_hex: str = ""
    source_sha256: str = ""
    diagnostics: tuple[str, ...] = ()
    literal_bytes_hex: str | None = None
    literal_encoding: str = ""
    literal_source_encoding: str = ""
    literal_complete: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "command": self.command,
            "source": self.source,
            "line": self.line,
            "carrier": self.carrier,
            "offset": self.offset,
            "end": self.end,
            "raw": self.raw,
            "encoding": self.encoding,
            "byte_offset": self.byte_offset,
            "byte_end": self.byte_end,
            "call_offset": self.call_offset,
            "command_offset": self.command_offset,
            "state": self.state,
            "raw_hex": self.raw_hex,
            "source_sha256": self.source_sha256,
            "diagnostics": list(self.diagnostics),
            "literal_bytes_hex": self.literal_bytes_hex,
            "literal_encoding": self.literal_encoding,
            "literal_source_encoding": self.literal_source_encoding,
            "literal_complete": self.literal_complete,
            "map_validation": "not_performed",
        }


def decode_save_text(payload: bytes) -> tuple[str, str, int] | None:
    """Strict text decoding, preserving the original byte offset of a BOM."""
    for marker, encoding in (
        (b"\xef\xbb\xbf", "utf-8"),
        (b"\xff\xfe", "utf-16-le"),
        (b"\xfe\xff", "utf-16-be"),
    ):
        if payload.startswith(marker):
            try:
                return payload[len(marker) :].decode(encoding), encoding, len(marker)
            except UnicodeDecodeError:
                return None
    if any(byte == 0 or byte < 9 or 13 < byte < 32 for byte in payload):
        return None
    for encoding in ("utf-8", "gb18030"):
        try:
            return payload.decode(encoding), encoding, 0
        except UnicodeDecodeError:
            pass
    return None


def _argument_spans(syntax: str) -> dict[int, tuple[tuple[int, int], ...]]:
    """Index all parenthesized arguments once; strings/comments are masked."""
    frames: list[tuple[int, int, list[tuple[int, int]]]] = []
    spans: dict[int, tuple[tuple[int, int], ...]] = {}
    for match in re.finditer(r"[(),{}\[\]]", syntax):
        token, index = match.group(), match.start()
        if token in "({[":
            frames.append((index, index + 1, []))
        elif token in ")}]":
            if not frames:
                continue
            opening, start, arguments = frames.pop()
            if syntax[opening] != {")": "(", "}": "{", "]": "["}[token]:
                continue
            if token == ")":
                spans[opening] = (*arguments, (start, index))
        elif token == "," and frames and syntax[frames[-1][0]] == "(":
            opening, start, arguments = frames[-1]
            arguments.append((start, index))
            frames[-1] = (opening, index + 1, arguments)
    return spans


def extract_save_text_carriers(
    text: str,
    source: str = "plain",
    *,
    lua: bool | None = None,
    encoding: str = "",
    bom_bytes: int = 0,
    include_plain_prefixes: bool = False,
    byte_source: bytes | None = None,
) -> list[SaveTextCarrier]:
    """Read every complete literal carrier with its unmodified source slice.

    Static literal concatenations are assembled; other expressions retain each
    literal fragment with an explicit expression state. Callee spelling is
    source evidence only and does not prove a native binding at runtime.
    """
    views = script_views(text, lua=lua)
    arguments = _argument_spans(views.syntax)
    literals = tuple(script_literals(text, lua=lua))
    starts = [literal.start for literal in literals]
    line_starts = [0, *(match.end() for match in re.finditer(r"\r\n|\r|\n", text))]

    def carrier(
        name: str,
        start: int,
        end: int,
        call: int,
        value: str,
        state: str,
        diagnostics: tuple[str, ...] = (),
        literal: ScriptLiteralValue | None = None,
    ) -> SaveTextCarrier:
        return SaveTextCarrier(
            source,
            name,
            bisect_right(line_starts, start),
            start,
            end,
            call,
            text[start:end],
            value,
            encoding,
            None,
            None,
            state,
            diagnostics=diagnostics,
            literal_bytes_hex=None
            if literal is None or literal.raw_bytes is None
            else literal.raw_bytes.hex(),
            literal_encoding="" if literal is None else literal.encoding,
            literal_source_encoding="" if literal is None else literal.source_encoding,
            literal_complete=True if literal is None else literal.complete,
        )

    out: list[SaveTextCarrier] = []
    for match in _CALL_RE.finditer(views.syntax):
        before = match.start() - 1
        while before >= 0 and views.syntax[before].isspace():
            before -= 1
        if before >= 0 and views.syntax[before] in {".", ":"}:
            continue
        name = match.group(1)
        selected = _CARRIER_ARGUMENTS.get(name)
        spans = arguments.get(match.end() - 1, ())
        if selected is None or selected >= len(spans):
            continue
        start, end = spans[selected]
        first = bisect_right(starts, start - 1)
        stop = bisect_right(starts, end - 1)
        enclosed = [
            literal
            for literal in literals[first:stop]
            if literal.end <= end and not literal.object_code
        ]
        if not enclosed:
            continue
        operators = {".."} if lua is True else {"+"} if lua is False else {"..", "+"}
        static = (
            not views.syntax[start : enclosed[0].start].strip()
            and not views.syntax[enclosed[-1].end : end].strip()
            and all(
                views.syntax[left.end : right.start].strip() in operators
                for left, right in zip(enclosed, enclosed[1:])
            )
        )
        if static:
            decoded = decode_script_literal_sequence(
                tuple(text[literal.start : literal.end] for literal in enclosed),
                lua=lua,
                encoding=encoding,
                jass_text_escapes=True,
            )
            out.append(
                carrier(
                    name,
                    enclosed[0].start,
                    enclosed[-1].end,
                    match.start(),
                    decoded.value
                    if decoded.value is not None
                    else "".join(literal.value for literal in enclosed),
                    "literal-text" if decoded.complete else "unknown-text",
                    decoded.diagnostics,
                    decoded,
                )
            )
        else:
            for literal in enclosed:
                decoded = decode_script_literal(
                    text[literal.start : literal.end],
                    lua=lua,
                    encoding=encoding,
                    jass_text_escapes=True,
                )
                out.append(
                    carrier(
                        name,
                        literal.start,
                        literal.end,
                        match.start(),
                        decoded.value if decoded.value is not None else literal.value,
                        "expression-fragment"
                        if decoded.complete
                        else "unknown-expression-fragment",
                        decoded.diagnostics,
                        decoded,
                    )
                )
    if include_plain_prefixes:
        cursor = 0
        for line in text.splitlines(keepends=True):
            stripped = line.strip()
            if _PREFIX_RE.match(stripped):
                start = cursor + len(line) - len(line.lstrip())
                end = cursor + len(line.rstrip())
                if (
                    views.arguments[start:end].strip() != stripped
                    or _PREFIX_RE.match(views.syntax, start) is None
                ):
                    cursor += len(line)
                    continue
                out.append(
                    carrier("command-line", start, end, start, stripped, "plain-text")
                )
            cursor += len(line)
    if encoding and out:
        selected = sorted(
            {value for entry in out for value in (entry.offset, entry.end)}
        )
        positions: dict[int, int] = {}
        previous, encoded = 0, bom_bytes
        for position in selected:
            encoded += len(text[previous:position].encode(encoding))
            positions[position] = encoded
            previous = position
        if byte_source is not None and text.encode(encoding) != byte_source[bom_bytes:]:
            # GB18030 has alternative byte spellings. Resolve actual decoder
            # boundaries only in that case; never substitute canonical bytes.
            decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
            positions = {0: bom_bytes} if 0 in selected else {}
            wanted = set(selected)
            chars = 0
            for index in range(bom_bytes, len(byte_source)):
                emitted = decoder.decode(byte_source[index : index + 1])
                chars += len(emitted)
                if emitted and chars in wanted:
                    positions[chars] = index + 1
        digest = (
            hashlib.sha256(byte_source).hexdigest() if byte_source is not None else ""
        )
        out = [
            replace(
                entry,
                byte_offset=positions[entry.offset],
                byte_end=positions[entry.end],
                raw_hex=byte_source[
                    positions[entry.offset] : positions[entry.end]
                ].hex()
                if byte_source is not None
                else "",
                source_sha256=digest,
            )
            for entry in out
        ]
    return sorted(out, key=lambda entry: (entry.offset, entry.call_offset))


def _codes(carriers: list[SaveTextCarrier]) -> list[SaveCode]:
    out: list[SaveCode] = []
    for carrier in carriers:
        prefixes = list(_PREFIX_RE.finditer(carrier.text))
        for index, match in enumerate(prefixes):
            stop = (
                prefixes[index + 1].start()
                if index + 1 < len(prefixes)
                else len(carrier.text)
            )
            code = carrier.text[match.start() : stop].strip()
            body = code[len(match.group()) :].strip()
            # Preserve the established candidate filter; every carrier,
            # including a short/empty template, is independently reportable.
            if len(code) < 8 or len(body) < 3:
                continue
            out.append(
                SaveCode(
                    code,
                    match.group(),
                    carrier.source,
                    carrier.line,
                    carrier.carrier,
                    carrier.offset,
                    carrier.end,
                    carrier.raw,
                    carrier.encoding,
                    carrier.byte_offset,
                    carrier.byte_end,
                    carrier.call_offset,
                    match.start(),
                    state="unknown-text-candidate"
                    if not carrier.literal_complete
                    else "text-fragment-candidate"
                    if carrier.state == "expression-fragment"
                    else "text-candidate",
                    raw_hex=carrier.raw_hex,
                    source_sha256=carrier.source_sha256,
                    diagnostics=carrier.diagnostics,
                    literal_bytes_hex=carrier.literal_bytes_hex,
                    literal_encoding=carrier.literal_encoding,
                    literal_source_encoding=carrier.literal_source_encoding,
                    literal_complete=carrier.literal_complete,
                )
            )
    return out


def extract_save_codes(
    text: str, source: str = "plain", *, lua: bool | None = None
) -> list[SaveCode]:
    return _codes(extract_save_text_carriers(text, source, lua=lua))


def extract_save_codes_bytes(
    payload: bytes,
    source: str = "file",
    *,
    lua: bool | None = None,
    include_plain_prefixes: bool = True,
) -> list[SaveCode]:
    decoded = decode_save_text(payload)
    if decoded is None:
        return []
    text, encoding, bom = decoded
    return _codes(
        extract_save_text_carriers(
            text,
            source,
            lua=lua,
            encoding=encoding,
            bom_bytes=bom,
            include_plain_prefixes=include_plain_prefixes,
            byte_source=payload,
        )
    )


def extract_script_save_codes(
    text: str, *, source: str = "script", lua: bool | None = None
) -> list[SaveCode]:
    return extract_save_codes(text, source, lua=lua)
