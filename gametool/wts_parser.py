"""Parse complete WTS byte evidence without guessing damaged block boundaries."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
import re
from types import MappingProxyType

from .script_string_references import trigstr_reference_id
from .war3_encoding import decode_warcraft_string, default_legacy_codecs
from .wts_models import (
    WtsDiagnostic,
    WtsRecord,
    WtsRecordState,
    WtsRegion,
    WtsReport,
)

_HEADER = re.compile(rb"[ \t]*STRING[ \t]+([0-9]+)([ \t]*(?://.*|\{.*)?)", re.I)
_DECLARATION = re.compile(rb"[ \t]*STRING(?=[ \t]|$)", re.I)
_DECIMAL_PREFIX = re.compile(rb"[ \t]*STRING[ \t]+([0-9]+)(?=[ \t{]|$)", re.I)


@dataclass(frozen=True, slots=True)
class _Line:
    start: int
    content_end: int
    end: int
    number: int
    content: bytes


@dataclass(frozen=True, slots=True)
class _Header:
    string_id: int | None
    id_text: str
    valid: bool
    inline_body: int | None = None
    has_comment: bool = False


@dataclass(frozen=True, slots=True)
class _Opening:
    """A body offset, or the next recoverable declaration when no body opened."""

    byte_offset: int | None
    next_line: int


@dataclass(frozen=True, slots=True)
class _Source:
    """ASCII structural view whose offsets map exactly to original bytes.

    UTF-16 is selected only by a file-leading BOM. Every code unit occupies
    one view byte; non-ASCII units cannot become punctuation or declarations.
    The view is never used as decoded text or published source evidence.
    """

    raw: bytes
    view: bytes
    width: int = 1
    codec: str | None = None

    def offset(self, position: int) -> int:
        return min(position * self.width, len(self.raw))

    def slice(self, start: int, end: int) -> bytes:
        return self.raw[self.offset(start) : self.offset(end)]

    def text(self, raw: bytes) -> str:
        return (
            raw.decode(self.codec, errors="replace")
            if self.codec is not None
            else decode_warcraft_string(raw)
        )


def _source(data: bytes) -> tuple[_Source, int]:
    for bom, codec in (
        (b"\xff\xfe", "utf-16-le"),
        (b"\xfe\xff", "utf-16-be"),
    ):
        if data.startswith(bom):
            view = bytearray()
            for index in range(0, len(data), 2):
                raw = data[index : index + 2]
                unit = int.from_bytes(raw, "little" if codec == "utf-16-le" else "big")
                view.append(unit if len(raw) == 2 and unit < 128 else 128)
            return _Source(data, bytes(view), 2, codec), 1
    return _Source(data, data), 3 if data.startswith(b"\xef\xbb\xbf") else 0


def parse_wts_evidence(data: bytes, *, source: str = "war3map.wts") -> WtsReport:
    """Retain all bytes and declarations; expose only unambiguous string IDs.

    Once a body opens, every line up to the first structural close is literal
    text, including STRING/opening shapes. Before the opening, a // comment
    starts a continuation that may contain ordinary lines without // prefixes.
    """
    records: list[WtsRecord] = []
    regions: list[WtsRegion] = []
    diagnostics: list[WtsDiagnostic] = []
    original, start = _source(data)
    data = original.view
    if start:
        regions.append(
            WtsRegion(
                "bom",
                0,
                original.offset(start),
                1,
                1,
                original.slice(0, start),
                "\ufeff",
            )
        )
    lines = _lines(data, start)
    headers = [_header(line) for line in lines]
    next_header = _next_indices([header is not None for header in headers])
    next_content = _next_indices([bool(line.content.strip(b" \t")) for line in lines])
    next_open = _next_indices(
        [
            line.content.startswith(b"{") and not line.content[1:].strip(b" \t")
            for line in lines
        ]
    )
    next_close = _next_indices([_closing(line.content) for line in lines])
    index = 0
    while index < len(lines):
        header = headers[index]
        if header is None:
            end = index + 1
            kind = "trivia" if _trivia(lines[index].content) else "unparsed"
            while (
                end < len(lines)
                and headers[end] is None
                and ("trivia" if _trivia(lines[end].content) else "unparsed") == kind
            ):
                end += 1
            region = _region(original, lines, index, end, kind)
            regions.append(region)
            if kind == "unparsed":
                diagnostics.append(
                    WtsDiagnostic(
                        kind,
                        "unparsed WTS bytes outside a STRING block",
                        (),
                        region.byte_start,
                        region.byte_end,
                        region.line_start,
                        region.line_end,
                    )
                )
            index = end
            continue

        opening = _opening(lines, index, header, next_content, next_open, next_header)
        if opening.byte_offset is None:
            end = opening.next_line
            state = (
                WtsRecordState.INCOMPLETE if header.valid else WtsRecordState.INVALID
            )
            record = _record(
                original, lines, index, end, header, len(records) + 1, state
            )
            records.append(record)
            message = (
                _incomplete_message(header)
                if header.valid
                else "invalid WTS STRING header"
            )
            diagnostics.append(_diagnostic(state.value, message, (record,)))
            index = end
            continue

        body_start = opening.byte_offset
        closing = next_close[opening.next_line]
        end = closing + 1 if closing < len(lines) else len(lines)
        state = (
            WtsRecordState.INVALID
            if not header.valid
            else WtsRecordState.INCOMPLETE
            if closing == len(lines)
            else WtsRecordState.CONFIRMED
        )
        body_end = (
            _body_end(data, body_start, lines[closing].start)
            if closing < len(lines)
            else len(data)
        )
        row = _record(
            original,
            lines,
            index,
            end,
            header,
            len(records) + 1,
            state,
            body_start,
            body_end,
        )
        if state == WtsRecordState.CONFIRMED and not _lossless(
            row.body_bytes or b"", original.codec
        ):
            row = replace(row, state=WtsRecordState.INVALID)
            diagnostics.append(
                _diagnostic("decode", "WTS body requires replacement decoding", (row,))
            )
        elif state != WtsRecordState.CONFIRMED:
            message = (
                _incomplete_message(header)
                if state == WtsRecordState.INCOMPLETE
                else "invalid WTS STRING header"
            )
            diagnostics.append(_diagnostic(state.value, message, (row,)))
        records.append(row)
        index = end

    table = _confirmed_values(records, diagnostics)
    return WtsReport(
        source,
        original.raw,
        MappingProxyType(table),
        tuple(records),
        tuple(regions),
        tuple(diagnostics),
    )


def _confirmed_values(
    records: list[WtsRecord], diagnostics: list[WtsDiagnostic]
) -> dict[int, str]:
    groups: dict[int, list[int]] = {}
    for index, row in enumerate(records):
        if row.string_id is not None:
            groups.setdefault(row.string_id, []).append(index)
    table: dict[int, str] = {}
    for sid, indices in groups.items():
        group = tuple(records[index] for index in indices)
        valid = tuple(row for row in group if row.state == WtsRecordState.CONFIRMED)
        values = {row.text for row in valid}
        if len(values) > 1:
            state = WtsRecordState.CONFLICT
            message = f"conflicting WTS values: STRING {Decimal(sid)}"
        elif len(valid) != len(group):
            if not valid:
                continue
            state = WtsRecordState.AMBIGUOUS
            message = f"unresolved WTS declaration: STRING {Decimal(sid)}"
        else:
            value = valid[0].text
            assert value is not None
            table[sid] = value
            if len(group) == 1:
                continue
            state = WtsRecordState.DUPLICATE
            message = f"identical repeated WTS value: STRING {Decimal(sid)}"
        for index in indices:
            # Keep the precise malformed state; complete siblings cannot resolve it.
            if records[index].state == WtsRecordState.CONFIRMED:
                records[index] = replace(records[index], state=state)
        diagnostics.append(
            _diagnostic(
                state.value, message, group, blocking=state != WtsRecordState.DUPLICATE
            )
        )
    return table


def _header(line: _Line) -> _Header | None:
    match = _HEADER.fullmatch(line.content)
    if match is not None:
        digits = match.group(1).decode("ascii")
        tail = match.group(2)
        inline = tail.lstrip(b" \t").startswith(b"{")
        body = line.start + match.start(2) + tail.index(b"{") + 1 if inline else None
        if body == line.content_end:
            body = line.end
        return _Header(
            trigstr_reference_id(digits),
            digits,
            True,
            body,
            tail.lstrip(b" \t").startswith(b"//"),
        )
    if _DECLARATION.match(line.content) is None:
        return None
    prefix = _DECIMAL_PREFIX.match(line.content)
    digits = prefix.group(1).decode("ascii") if prefix is not None else ""
    return _Header(trigstr_reference_id(digits) if digits else None, digits, False)


def _opening(
    lines: list[_Line],
    index: int,
    header: _Header,
    next_content: list[int],
    next_open: list[int],
    next_header: list[int],
) -> _Opening:
    if header.inline_body is not None:
        return _Opening(header.inline_body, index + 1)
    following = next_content[index + 1]
    has_comment = header.has_comment or (
        following < len(lines)
        and lines[following].content.lstrip(b" \t").startswith(b"//")
    )
    if has_comment:
        # WTS writes // once for the entire comment. Subsequent ordinary lines,
        # even STRING-shaped lines, belong to that comment until the opening.
        following = next_open[following]
    if following == len(lines) or not lines[following].content.startswith(b"{"):
        return _Opening(None, len(lines) if has_comment else next_header[index + 1])
    line = lines[following]
    if not line.content[1:].strip(b" \t"):
        return _Opening(line.end, following + 1)
    # Retain the existing inline-opening compatibility, while closing braces
    # must still occupy their own physical line.
    return _Opening(line.start + 1, following + 1)


def _record(
    data: _Source,
    lines: list[_Line],
    begin: int,
    end: int,
    header: _Header,
    ordinal: int,
    state: WtsRecordState,
    body_start: int | None = None,
    body_end: int | None = None,
) -> WtsRecord:
    start = lines[begin].start
    finish = lines[end - 1].end
    raw = data.slice(start, finish)
    body = (
        data.slice(body_start, body_end)
        if body_start is not None and body_end is not None
        else None
    )
    return WtsRecord(
        ordinal,
        header.string_id,
        header.id_text,
        state,
        data.offset(start),
        data.offset(finish),
        lines[begin].number,
        lines[end - 1].number,
        raw,
        data.text(raw),
        data.offset(body_start) if body_start is not None else None,
        data.offset(body_end) if body_end is not None else None,
        body,
        data.text(body) if body is not None else None,
    )


def _region(
    data: _Source, lines: list[_Line], begin: int, end: int, kind: str
) -> WtsRegion:
    raw = data.slice(lines[begin].start, lines[end - 1].end)
    return WtsRegion(
        kind,
        data.offset(lines[begin].start),
        data.offset(lines[end - 1].end),
        lines[begin].number,
        lines[end - 1].number,
        raw,
        data.text(raw),
    )


def _diagnostic(
    kind: str,
    message: str,
    records: tuple[WtsRecord, ...],
    *,
    blocking: bool = True,
) -> WtsDiagnostic:
    return WtsDiagnostic(
        kind,
        message,
        tuple(row.ordinal for row in records),
        records[0].byte_start,
        records[-1].byte_end,
        records[0].line_start,
        records[-1].line_end,
        blocking,
    )


def _incomplete_message(header: _Header) -> str:
    return f"incomplete WTS block: STRING {Decimal(header.string_id or 0)}"


def _next_indices(selected: list[bool]) -> list[int]:
    result = [len(selected)] * (len(selected) + 1)
    following = len(selected)
    for index in range(len(selected) - 1, -1, -1):
        if selected[index]:
            following = index
        result[index] = following
    return result


def _trivia(content: bytes) -> bool:
    return not content.strip(b" \t") or content.lstrip(b" \t").startswith(b"//")


def _closing(content: bytes) -> bool:
    return content.startswith(b"}") and not content[1:].strip(b" \t")


def _body_end(data: bytes, lower_bound: int, end: int) -> int:
    if end - 2 >= lower_bound and data[end - 2 : end] == b"\r\n":
        return end - 2
    if end - 1 >= lower_bound and data[end - 1 : end] in {b"\r", b"\n"}:
        return end - 1
    return end


def _lossless(raw: bytes, codec: str | None = None) -> bool:
    if codec is not None:
        try:
            raw.decode(codec)
            return True
        except UnicodeDecodeError:
            return False
    try:
        raw.decode("utf-8")
        return True
    except UnicodeDecodeError:
        pass
    for codec in default_legacy_codecs():
        try:
            raw.decode(codec)
            return True
        except LookupError, UnicodeDecodeError:
            continue
    return False


def _lines(data: bytes, start: int) -> list[_Line]:
    result: list[_Line] = []
    position = start
    while position < len(data):
        content_end = position
        while content_end < len(data) and data[content_end] not in {10, 13}:
            content_end += 1
        end = content_end
        if data[end : end + 2] == b"\r\n":
            end += 2
        elif end < len(data):
            end += 1
        result.append(
            _Line(
                position, content_end, end, len(result) + 1, data[position:content_end]
            )
        )
        position = end
    return result
