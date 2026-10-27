"""Read-only game-cache records, with byte evidence and explicit layout ambiguity.

The raw cache has no proved magic/version word: its first u32 is reserved.
All numbers below are little endian. A cache contains named categories with
five counted tables (integer, real, boolean, unit, string), in that order.
The four unit shapes differ only in secondary skill IDs and two extension
lists. Shape names describe the encoded layout, not a proved game version.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, replace
from typing import Final, cast

_KINDS: Final = ("integer", "real", "boolean", "unit", "string")
_LAYOUTS: Final = ("classic", "modern_skills", "classic_extension", "reforged")
_EMBEDDED_NAME: Final = b"Campaigns.w3v\0"


@dataclass(frozen=True, slots=True)
class CacheByteField:
    """One actual encoded value, with an exclusive end in the source layer."""

    name: str
    value_type: str
    value: object
    offset: int
    end: int
    raw: bytes
    state: str = "confirmed"
    encoding: str = ""
    diagnostic: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "type": self.value_type,
            "value": self.value,
            "offset": self.offset,
            "end": self.end,
            "raw_hex": self.raw.hex(),
            "state": self.state,
            "encoding": self.encoding,
            "diagnostic": self.diagnostic,
        }


@dataclass(frozen=True, slots=True)
class GameCacheRecord:
    cache: str
    category: str
    key: str
    value_type: str
    value: object
    record_offset: int
    offset: int
    end: int
    raw: bytes
    fields: tuple[CacheByteField, ...] = ()
    state: str = "confirmed"
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "cache": self.cache,
            "category": self.category,
            "key": self.key,
            "type": self.value_type,
            "value": self.value,
            "record_offset": self.record_offset,
            "offset": self.offset,
            "end": self.end,
            "raw_hex": self.raw.hex(),
            "fields": [field.to_dict() for field in self.fields],
            "state": self.state,
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True, slots=True)
class CacheLayoutCandidate:
    layout: str
    fields: tuple[GameCacheRecord, ...]
    structure: tuple[CacheByteField, ...]
    consumed: int
    complete: bool
    diagnostics: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "layout": self.layout,
            "complete": self.complete,
            "consumed": self.consumed,
            "diagnostics": list(self.diagnostics),
            "fields": [record.to_dict() for record in self.fields],
            "structure": [field.to_dict() for field in self.structure],
        }


@dataclass(frozen=True, slots=True)
class GameCacheEvidence:
    source: str
    offset: int
    raw: bytes
    fields: tuple[GameCacheRecord, ...]
    structure: tuple[CacheByteField, ...]
    layouts: tuple[str, ...]
    complete: bool
    consumed: int
    diagnostics: tuple[str, ...]
    candidates: tuple[CacheLayoutCandidate, ...] = ()
    frame: tuple[CacheByteField, ...] = ()

    def to_dict(self) -> dict[str, object]:
        state = (
            "partial"
            if not self.complete
            else "conflict"
            if any(record.state == "conflict" for record in self.fields)
            else "invalid"
            if any(record.state == "invalid" for record in self.fields)
            or any(field.state == "invalid" for field in self.structure)
            else "confirmed"
        )
        return {
            "source": self.source,
            "source_kind": "saved_gamecache",
            "state": state,
            "offset": self.offset,
            "length": len(self.raw),
            "complete": self.complete,
            "consumed": self.consumed,
            "layouts": list(self.layouts),
            "fields": [record.to_dict() for record in self.fields],
            "structure": [field.to_dict() for field in self.structure],
            "frame": [field.to_dict() for field in self.frame],
            "tail_offset": self.offset + self.consumed,
            "tail_hex": self.raw[self.consumed :].hex(),
            "raw_hex": self.raw.hex(),
            "diagnostics": list(self.diagnostics),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


class _ShortRecord(ValueError):
    pass


class _Reader:
    def __init__(self, raw: bytes, base: int) -> None:
        self.raw = raw
        self.base = base
        self.pos = 0
        self.structure: list[CacheByteField] = []
        self.diagnostics: list[str] = []

    def take(self, size: int) -> bytes:
        if size > len(self.raw) - self.pos:
            raise _ShortRecord(
                f"offset {self.base + self.pos}: need {size} bytes, "
                f"have {len(self.raw) - self.pos}"
            )
        value = self.raw[self.pos : self.pos + size]
        self.pos += size
        return value

    def field(self, name: str, kind: str) -> CacheByteField:
        start = self.pos
        encoding = diagnostic = ""
        state = "confirmed"
        if kind == "string":
            stop = self.raw.find(b"\0", start)
            if stop < 0:
                raise _ShortRecord(f"offset {self.base + start}: unterminated {name}")
            raw = self.take(stop - start + 1)
            value, encoding = _decode_string(raw[:-1])
            if not encoding:
                state = "invalid"
                diagnostic = "unrecognized string encoding; raw bytes retained"
        else:
            raw = self.take(4)
            format_code = (
                "<f" if kind == "real" else "<i" if kind == "integer" else "<I"
            )
            numeric = struct.unpack(format_code, raw)[0]
            value = numeric
            if kind == "real" and not math.isfinite(numeric):
                value, state, diagnostic = None, "invalid", "non-finite f32"
            elif kind == "boolean":
                if numeric in (0, 1):
                    value = bool(numeric)
                else:
                    state, diagnostic = "invalid", "boolean must encode 0 or 1"
            elif kind == "rawcode":
                value = int(numeric).to_bytes(4, "big").decode("latin-1")
        field = CacheByteField(
            name,
            kind,
            value,
            self.base + start,
            self.base + self.pos,
            raw,
            state,
            encoding,
            diagnostic,
        )
        if diagnostic:
            self.diagnostics.append(f"offset {field.offset}: {name}: {diagnostic}")
        return field

    def header(self, name: str, kind: str = "u32") -> CacheByteField:
        field = self.field(name, kind)
        self.structure.append(field)
        return field

    def count(self, name: str, minimum: int) -> int:
        field = self.header(name)
        count = cast(int, field.value)  # u32, no string-int conversion quota
        if count > (len(self.raw) - self.pos) // minimum:
            self.diagnostics.append(
                f"offset {field.offset}: {name}={count} exceeds remaining encoded "
                f"bounds (minimum {minimum} bytes per record); retaining readable prefix"
            )
        return count


def _decode_string(raw: bytes) -> tuple[str, str]:
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            pass
    return raw.decode("latin-1"), ""


def _unit_fields(reader: _Reader, layout: str, fields: list[CacheByteField]) -> None:
    def take(name: str, kind: str = "u32") -> object:
        field = reader.field(name, kind)
        fields.append(field)
        return field.value

    take("unit_id", "rawcode")
    slots = cast(int, take("inventory_slots"))
    for index in range(slots):
        for key, kind in (("item", "rawcode"), ("charges", "u32"), ("flags", "u32")):
            take(f"inventory.{index + 1}.{key}", kind)
    for key in (
        "experience",
        "level_minus_one",
        "unspent_skill_points",
        "raw_name_indices",
        "strength",
    ):
        take(key)
        if key == "level_minus_one":
            encoded = fields[-1]
            fields.append(
                replace(
                    encoded,
                    name="level",
                    value=cast(int, encoded.value) + 1,
                    state="derived",
                    diagnostic="encoded level_minus_one + 1",
                )
            )
    take("strength_bonus", "real")
    take("agility")
    for key in ("agility_move_increment", "agility_attack_increment", "agility_bonus"):
        take(key, "real")
    take("intelligence")
    take("intelligence_bonus", "real")
    skill_count = cast(int, take("skill_count"))
    for index in range(skill_count):
        take(f"skills.{index + 1}.ability", "rawcode")
        if layout in {"modern_skills", "reforged"}:
            take(f"skills.{index + 1}.raw_secondary_id", "rawcode")
        take(f"skills.{index + 1}.level")
    tail_start = reader.pos
    for key in ("life_increment", "mana_increment", "sight_range"):
        take(key, "real")
    take("tail_reserved")
    take("attack_increment_1", "integer")
    take("attack_increment_2", "integer")
    take("armor_increment", "real")
    raw = reader.take(2)
    fields.append(
        CacheByteField(
            "tail_reserved_bytes",
            "bytes",
            raw.hex(),
            reader.base + reader.pos - 2,
            reader.base + reader.pos,
            raw,
        )
    )
    fields.append(
        CacheByteField(
            "raw_tail",
            "bytes",
            reader.raw[tail_start : reader.pos].hex(),
            reader.base + tail_start,
            reader.base + reader.pos,
            reader.raw[tail_start : reader.pos],
        )
    )
    if layout in {"classic_extension", "reforged"}:
        for list_index in range(2):
            count = cast(int, take(f"extensions.{list_index + 1}.count"))
            for index in range(count):
                for column in range(3):
                    take(f"extensions.{list_index + 1}.{index + 1}.{column + 1}")


def _candidate(raw: bytes, layout: str, base: int) -> CacheLayoutCandidate:
    reader = _Reader(raw, base)
    records: list[GameCacheRecord] = []
    ended = False
    try:
        reader.header("reserved")
        caches = reader.count("cache_count", 9)
        for cache_index in range(caches):
            cache = reader.header(f"cache.{cache_index + 1}.name", "string")
            reader.header(f"cache.{cache_index + 1}.reserved")
            categories = reader.count(f"cache.{cache_index + 1}.category_count", 41)
            for category_index in range(categories):
                prefix = f"cache.{cache_index + 1}.category.{category_index + 1}"
                category = reader.header(f"{prefix}.name", "string")
                start = reader.pos
                reserved = reader.take(20)
                reader.structure.append(
                    CacheByteField(
                        f"{prefix}.reserved_types",
                        "bytes",
                        reserved.hex(),
                        base + start,
                        base + reader.pos,
                        reserved,
                    )
                )
                for kind in _KINDS:
                    count = reader.count(
                        f"{prefix}.{kind}_count", 2 if kind == "string" else 5
                    )
                    for _ in range(count):
                        record_start = reader.pos
                        key = reader.header(f"{prefix}.{kind}.key", "string")
                        value_start = reader.pos
                        components: list[CacheByteField] = []
                        try:
                            if kind == "unit":
                                _unit_fields(reader, layout, components)
                                value = {
                                    field.name: field.value for field in components
                                }
                            else:
                                field = reader.field("value", kind)
                                components.append(field)
                                value = field.value
                        except _ShortRecord as exc:
                            records.append(
                                GameCacheRecord(
                                    str(cache.value),
                                    str(category.value),
                                    str(key.value),
                                    kind,
                                    {field.name: field.value for field in components},
                                    base + record_start,
                                    base + value_start,
                                    base + reader.pos,
                                    raw[record_start : reader.pos],
                                    tuple(components),
                                    "partial",
                                    (str(exc),),
                                )
                            )
                            raise
                        state = (
                            "invalid"
                            if any(
                                field.state == "invalid"
                                for field in (cache, category, key, *components)
                            )
                            else "confirmed"
                        )
                        records.append(
                            GameCacheRecord(
                                str(cache.value),
                                str(category.value),
                                str(key.value),
                                kind,
                                value,
                                base + record_start,
                                base + value_start,
                                base + reader.pos,
                                raw[record_start : reader.pos],
                                tuple(components),
                                state,
                            )
                        )
        ended = True
    except _ShortRecord as exc:
        reader.diagnostics.append(str(exc))
    if ended and reader.pos != len(raw):
        reader.diagnostics.append(
            f"offset {base + reader.pos}: {len(raw) - reader.pos} unrecognized trailing bytes"
        )
    complete = ended and reader.pos == len(raw)
    return CacheLayoutCandidate(
        layout,
        tuple(records),
        tuple(reader.structure),
        reader.pos,
        complete,
        tuple(dict.fromkeys(reader.diagnostics)),
    )


def _same_record(left: GameCacheRecord, right: GameCacheRecord) -> bool:
    return left == right


def _common_records(
    candidates: tuple[CacheLayoutCandidate, ...],
) -> tuple[GameCacheRecord, ...]:
    common: list[GameCacheRecord] = []
    by_offset = [
        {record.record_offset: record for record in candidate.fields}
        for candidate in candidates
    ]
    for first in candidates[0].fields:
        mirrors = [index.get(first.record_offset) for index in by_offset]
        if all(
            mirror is not None and _same_record(first, mirror) for mirror in mirrors
        ):
            common.append(first)
        elif first.value_type == "unit" and all(
            mirror is not None
            and mirror.value_type == "unit"
            and (mirror.cache, mirror.category, mirror.key, mirror.offset)
            == (first.cache, first.category, first.key, first.offset)
            for mirror in mirrors
        ):
            component_indexes = [
                {(field.name, field.offset): field for field in mirror.fields}
                for mirror in mirrors
                if mirror is not None
            ]
            fields = tuple(
                field
                for field in first.fields
                if all(
                    index.get((field.name, field.offset)) == field
                    for index in component_indexes
                )
            )
            end = max((field.end for field in fields), default=first.offset)
            raw = first.raw[: end - first.record_offset]
            common.append(
                replace(
                    first,
                    value={field.name: field.value for field in fields},
                    fields=fields,
                    end=end,
                    raw=raw,
                    state="partial",
                    diagnostics=(
                        "unit layout unresolved; only common byte fields confirmed",
                    ),
                )
            )
    return tuple(common)


def _conflicts(
    records: tuple[GameCacheRecord, ...],
) -> tuple[tuple[GameCacheRecord, ...], tuple[str, ...]]:
    groups: dict[tuple[str, str, str, str], list[GameCacheRecord]] = {}
    for record in records:
        groups.setdefault(
            (record.cache, record.category, record.key, record.value_type), []
        ).append(record)
    conflicting = {
        identity
        for identity, group in groups.items()
        if any(record.value != group[0].value for record in group[1:])
    }
    diagnostics = tuple(
        f"conflicting {kind} records: {cache}/{category}/{key}; every encoded record retained"
        for cache, category, key, kind in sorted(conflicting)
    )
    return tuple(
        replace(
            record,
            state="conflict",
            diagnostics=(
                *record.diagnostics,
                "same typed cache key has conflicting saved values",
            ),
        )
        if (record.cache, record.category, record.key, record.value_type) in conflicting
        else record
        for record in records
    ), diagnostics


def parse_gamecache(
    raw: bytes,
    *,
    source: str = "cache",
    offset: int = 0,
    unit_layout: str | None = None,
) -> GameCacheEvidence:
    """Parse only explicitly identified cache bytes, retaining every candidate.

    No allocation is based on an encoded count. Every iteration consumes a
    physical record or stops at the first missing boundary. Invalid scalar
    encodings stay records; unrecognized tails never become missing values.
    """
    if type(offset) is not int or offset < 0:
        raise ValueError("cache offset must be nonnegative")
    if unit_layout is not None and unit_layout not in _LAYOUTS:
        raise ValueError(f"unknown unit layout: {unit_layout}")
    layouts = (unit_layout,) if unit_layout is not None else _LAYOUTS
    attempts = tuple(_candidate(raw, layout, offset) for layout in layouts)
    full = tuple(candidate for candidate in attempts if candidate.complete)
    relevant = full or attempts
    records = _common_records(relevant)
    equivalent = all(
        candidate.fields == relevant[0].fields for candidate in relevant[1:]
    )
    structure_indexes = [
        {(field.name, field.offset): field for field in candidate.structure}
        for candidate in relevant[1:]
    ]
    structure = tuple(
        field
        for field in relevant[0].structure
        if all(
            index.get((field.name, field.offset)) == field
            for index in structure_indexes
        )
    )
    records, conflicts = _conflicts(records)
    diagnostics = list(
        dict.fromkeys(
            message for candidate in relevant for message in candidate.diagnostics
        )
    )
    complete = bool(full) and equivalent
    if not full:
        diagnostics.append(
            "no complete supported cache layout; confirmed prefix and exact raw tail retained"
        )
    elif not equivalent:
        diagnostics.append(
            "ambiguous unit layouts; candidate values are not confirmed saved hero fields"
        )
    diagnostics.extend(conflicts)
    consumed = min(candidate.consumed for candidate in relevant)
    return GameCacheEvidence(
        source,
        offset,
        raw,
        records,
        structure,
        tuple(candidate.layout for candidate in full),
        complete,
        consumed,
        tuple(diagnostics),
        attempts if not complete else (),
    )


def extract_embedded_gamecaches(
    raw: bytes, *, source: str = "save.raw"
) -> tuple[GameCacheEvidence, ...]:
    """Read every espi-framed Campaigns.w3v, never a bare matching filename.

    Frame: espi + u32 payload length + 32 opaque bytes + NUL filename + raw
    cache. The payload length includes the opaque bytes, filename and cache.
    Offsets refer to the decompressed source layer, not compressed file bytes.
    """
    caches: list[GameCacheEvidence] = []
    cursor = 0
    while (found := raw.find(_EMBEDDED_NAME, cursor)) >= 0:
        cursor = found + len(_EMBEDDED_NAME)
        if found < 40 or raw[found - 40 : found - 36] != b"espi":
            continue
        frame_start = found - 40
        payload_length = struct.unpack_from("<I", raw, frame_start + 4)[0]
        cache_length = payload_length - 32 - len(_EMBEDDED_NAME)
        diagnostics: tuple[str, ...] = ()
        if cache_length < 8:
            diagnostics = (
                f"offset {frame_start + 4}: embedded payload length {payload_length} cannot contain a cache header",
            )
        elif cache_length > len(raw) - cursor:
            diagnostics = (
                f"offset {cursor}: truncated embedded cache: declared {cache_length}, available {len(raw) - cursor}",
            )
        available = raw[cursor : cursor + max(0, cache_length)]
        evidence = parse_gamecache(available, source=source, offset=cursor)
        frame = (
            CacheByteField(
                "frame.magic", "bytes", "espi", frame_start, frame_start + 4, b"espi"
            ),
            CacheByteField(
                "frame.payload_length",
                "u32",
                payload_length,
                frame_start + 4,
                frame_start + 8,
                raw[frame_start + 4 : frame_start + 8],
            ),
            CacheByteField(
                "frame.opaque",
                "bytes",
                raw[frame_start + 8 : found].hex(),
                frame_start + 8,
                found,
                raw[frame_start + 8 : found],
            ),
            CacheByteField(
                "frame.name",
                "string",
                "Campaigns.w3v",
                found,
                cursor,
                _EMBEDDED_NAME,
                encoding="utf-8",
            ),
        )
        caches.append(
            replace(
                evidence,
                frame=frame,
                complete=evidence.complete and not diagnostics,
                diagnostics=(*diagnostics, *evidence.diagnostics),
            )
        )
    return tuple(caches)
