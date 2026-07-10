"""Bounded parser for Warcraft III ``war3campaign.w3f`` metadata."""

from __future__ import annotations

import struct
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from .war3_encoding import decode_warcraft_string
from .wts import resolve

_MAX_MAP_ENTRIES = 10_000
_MIN_MAP_BUTTON_BYTES = 7
_MIN_MAP_ORDER_BYTES = 2


class W3fDiagnostic(StrEnum):
    """Recoverable W3F parse conditions exposed to callers."""

    TRUNCATED = "truncated"


@dataclass(frozen=True, slots=True)
class CampaignMapEntry:
    """A campaign map with optional button metadata."""

    path: str
    display_name: str
    chapter_name: str
    initially_visible: bool


@dataclass  # noqa: MUTABLE_OK  # noqa: SLOTS_OK - mutable map-list compatibility model.
class W3fInfo:
    """Campaign metadata with a mutable compatibility list of map entries."""

    version: int = 0
    campaign_version: int = 0
    editor_version: int = 0
    name: str = ""
    difficulty: str = ""
    author: str = ""
    description: str = ""
    campaign_flags: int = 0
    background_index: int = 0
    background_path: str = ""
    minimap_path: str = ""
    ambient_index: int = 0
    ambient_path: str = ""
    fog_style: int = 0
    fog_start_z: float = 0.0
    fog_end_z: float = 0.0
    fog_density: float = 0.0
    fog_color: tuple[int, int, int, int] = (0, 0, 0, 0)
    race: int = 0
    background_version: int | None = None
    maps: list[CampaignMapEntry] = field(default_factory=list)
    diagnostic: W3fDiagnostic | None = None


class _TruncatedRead(Exception):
    """Raised when a bounded W3F reader cannot confirm the next field."""


@dataclass(slots=True)  # noqa: MUTABLE_OK - mutable bounded-reader cursor.
class _Reader:
    data: bytes
    position: int = 0

    @property
    def remaining(self) -> int:
        return len(self.data) - self.position

    def i32(self) -> int:
        return self._unpack("<i")

    def f32(self) -> float:
        return self._unpack("<f")

    def bytes(self, size: int) -> bytes:
        if self.remaining < size:
            raise _TruncatedRead
        value = self.data[self.position:self.position + size]
        self.position += size
        return value

    def cstr(self) -> str:
        end = self.data.find(b"\x00", self.position)
        if end < 0:
            raise _TruncatedRead
        raw = self.data[self.position:end]
        self.position = end + 1
        return decode_warcraft_string(raw)

    def count(self, minimum_entry_size: int) -> int:
        value = self.i32()
        maximum = min(_MAX_MAP_ENTRIES, self.remaining // minimum_entry_size)
        if value < 0 or value > maximum:
            raise _TruncatedRead
        return value

    def _unpack(self, format_string: str) -> int | float:
        size = struct.calcsize(format_string)
        if self.remaining < size:
            raise _TruncatedRead
        value = struct.unpack_from(format_string, self.data, self.position)[0]
        self.position += size
        return value


def parse_w3f(data: bytes, wts: Mapping[int, str] | None = None) -> W3fInfo | None:
    """Parse a campaign header and as much bounded map metadata as is present."""
    reader = _Reader(data)
    strings = wts or {}
    try:
        info = W3fInfo(
            version=reader.i32(),
            campaign_version=reader.i32(),
            editor_version=reader.i32(),
            name=_display(reader, strings),
            difficulty=_display(reader, strings),
            author=_display(reader, strings),
            description=_display(reader, strings),
        )
    except _TruncatedRead:
        return None

    try:
        _parse_campaign_metadata(reader, info)
    except _TruncatedRead:
        info.diagnostic = W3fDiagnostic.TRUNCATED
        return info

    _parse_map_entries(reader, info, strings)
    return info


def _parse_campaign_metadata(reader: _Reader, info: W3fInfo) -> None:
    info.campaign_flags = reader.i32()
    info.background_index = reader.i32()
    info.background_path = reader.cstr()
    info.minimap_path = reader.cstr()
    info.ambient_index = reader.i32()
    info.ambient_path = reader.cstr()
    info.fog_style = reader.i32()
    info.fog_start_z = reader.f32()
    info.fog_end_z = reader.f32()
    info.fog_density = reader.f32()
    info.fog_color = tuple(reader.bytes(4))
    info.race = reader.i32()
    if info.version >= 2:
        info.background_version = reader.i32()


def _parse_map_entries(
    reader: _Reader,
    info: W3fInfo,
    strings: Mapping[int, str],
) -> None:
    buttons: list[CampaignMapEntry] = []
    orders: list[str] = []
    try:
        button_count = reader.count(_MIN_MAP_BUTTON_BYTES)
        for _ in range(button_count):
            initially_visible = reader.i32() != 0
            chapter_name = _display(reader, strings)
            display_name = _display(reader, strings)
            path = reader.cstr()
            buttons.append(CampaignMapEntry(
                path=path,
                display_name=display_name,
                chapter_name=chapter_name,
                initially_visible=initially_visible,
            ))
    except _TruncatedRead:
        info.maps[:] = buttons
        info.diagnostic = W3fDiagnostic.TRUNCATED
        return

    info.maps[:] = buttons
    try:
        order_count = reader.count(_MIN_MAP_ORDER_BYTES)
        for _ in range(order_count):
            reader.cstr()
            orders.append(reader.cstr())
    except _TruncatedRead:
        info.maps[:] = _combine_map_entries(buttons, orders)
        info.diagnostic = W3fDiagnostic.TRUNCATED
        return

    info.maps[:] = _combine_map_entries(buttons, orders)


def _display(reader: _Reader, strings: Mapping[int, str]) -> str:
    return _display_value(reader.cstr(), strings)


def _display_value(value: str, strings: Mapping[int, str]) -> str:
    return str(resolve(value, strings))


def _combine_map_entries(
    buttons: list[CampaignMapEntry],
    orders: list[str],
) -> list[CampaignMapEntry]:
    by_path = {_path_key(entry.path): entry for entry in buttons}
    combined: list[CampaignMapEntry] = []
    used: set[str] = set()
    for path in orders:
        key = _path_key(path)
        if key in used:
            continue
        used.add(key)
        button = by_path.get(key)
        if button is None:
            combined.append(CampaignMapEntry(path, path, "", True))
        else:
            combined.append(CampaignMapEntry(
                path=path,
                display_name=button.display_name,
                chapter_name=button.chapter_name,
                initially_visible=button.initially_visible,
            ))
    for button in buttons:
        key = _path_key(button.path)
        if key not in used:
            combined.append(button)
            used.add(key)
    return combined


def _path_key(path: str) -> str:
    return path.replace("/", "\\").casefold()
