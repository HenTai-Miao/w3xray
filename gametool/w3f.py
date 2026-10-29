"""Read verified W3F v1/v2/v3 layouts and retain every source byte.

Layout: War3Net CampaignInfo, CampaignMapButton and CampaignMap readers AND
writers at commit 5f6f7bac26ed7ce7d0db83ceb4fb9ce59f918ff8:
https://github.com/Drake53/War3Net/tree/5f6f7bac26ed7ce7d0db83ceb4fb9ce59f918ff8/src/War3Net.Build.Core/Serialization/Binary/Info
"""

from __future__ import annotations

import base64
import math
import struct
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from enum import StrEnum

from .war3_encoding import decode_warcraft_string
from .wts import resolve

_MIN_MAP_BUTTON_BYTES = 7
_MIN_MAP_ORDER_BYTES = 2
SUPPORTED_W3F_VERSIONS = frozenset((1, 2, 3))


class W3fDiagnostic(StrEnum):
    """Recoverable W3F parse conditions exposed to callers."""

    TRUNCATED = "truncated"
    UNSUPPORTED_VERSION = "unsupported_version"
    TRAILING_DATA = "trailing_data"
    INVALID_VALUE = "invalid_value"


@dataclass(frozen=True, slots=True)
class W3fIssue:
    code: W3fDiagnostic
    field: str
    offset: int
    message: str


@dataclass(frozen=True, slots=True)
class W3fField:
    name: str
    offset: int
    end_offset: int
    value: int | float | str | tuple[int, ...]
    raw_bytes: bytes


@dataclass(frozen=True, slots=True)
class CampaignMapEntry:
    """A campaign map with optional button metadata."""

    path: str
    display_name: str
    chapter_name: str
    initially_visible: bool


@dataclass  # MUTABLE_OK, SLOTS_OK: mutable map-list compatibility model.
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
    fog_color: tuple[int, ...] = (0, 0, 0, 0)
    # 定长4通道, reader.bytes(4) 动态长元组
    race: int = 0
    background_version: int | None = None
    maps: list[CampaignMapEntry] = field(default_factory=list)
    diagnostic: W3fDiagnostic | None = None
    fog_height_start: float | None = None
    fog_height_end: float | None = None
    fog_linear_start: float | None = None
    fog_linear_end: float | None = None
    fog_max_opacity: float | None = None
    fog_draw_over_sky: int | None = None
    map_buttons: list[CampaignMapEntry] = field(default_factory=list)
    map_order: list[tuple[str, str]] = field(default_factory=list)
    raw_bytes: bytes = b""
    consumed_bytes: int = 0
    unconsumed_data: bytes = b""
    header_complete: bool = False
    maps_complete: bool = False
    complete: bool = False
    byte_fields: tuple[W3fField, ...] = ()
    diagnostics: tuple[W3fIssue, ...] = ()


class _TruncatedRead(Exception):
    """Raised when a bounded W3F reader cannot confirm the next field."""


@dataclass(slots=True)  # MUTABLE_OK: mutable bounded-reader cursor.
class _Reader:
    data: bytes
    position: int = 0
    current_field: str = "version"
    byte_fields: list[W3fField] = field(default_factory=list)
    diagnostics: list[W3fIssue] = field(default_factory=list)

    @property
    def remaining(self) -> int:
        return len(self.data) - self.position

    def i32(self, name: str) -> int:
        return int(self._unpack("<i", name))

    def f32(self, name: str) -> float:
        value = self._unpack("<f", name)
        if not math.isfinite(value):
            self.problem(
                W3fDiagnostic.INVALID_VALUE,
                name,
                self.position - 4,
                "non-finite W3F float; exact bytes retained",
            )
        return value

    def bytes(self, size: int, name: str) -> bytes:
        start = self.position
        value = self._take(size, name)
        self._record(name, start, tuple(value))
        return value

    def cstr(self, name: str) -> str:
        self.current_field = name
        start = self.position
        end = self.data.find(b"\x00", self.position)
        if end < 0:
            raise _TruncatedRead
        raw = self.data[self.position : end]
        self.position = end + 1
        value = decode_warcraft_string(raw)
        self._record(name, start, value)
        return value

    def count(self, minimum_entry_size: int, name: str) -> int:
        value = self.i32(name)
        maximum = self.remaining // minimum_entry_size
        if value < 0 or value > maximum:
            raise _TruncatedRead
        return value

    def _unpack(self, format_string: str, name: str) -> int | float:
        size = struct.calcsize(format_string)
        start = self.position
        raw = self._take(size, name)
        value = struct.unpack(format_string, raw)[0]
        self._record(name, start, value)
        return value

    def _take(self, size: int, name: str) -> bytes:
        self.current_field = name
        if self.remaining < size:
            raise _TruncatedRead
        raw = self.data[self.position : self.position + size]
        self.position += size
        return raw

    def _record(
        self, name: str, start: int, value: int | float | str | tuple[int, ...]
    ) -> None:
        self.byte_fields.append(
            W3fField(
                name, start, self.position, value, self.data[start : self.position]
            )
        )

    def problem(
        self, code: W3fDiagnostic, name: str, offset: int, message: str
    ) -> None:
        self.diagnostics.append(W3fIssue(code, name, offset, message))


def parse_w3f(data: bytes, wts: Mapping[int, str] | None = None) -> W3fInfo | None:
    """Compatibility API: an incomplete title/header still returns ``None``."""
    info = parse_w3f_evidence(data, wts)
    return info if info.header_complete else None


def parse_w3f_evidence(data: bytes, wts: Mapping[int, str] | None = None) -> W3fInfo:
    """Keep confirmed metadata and complete raw evidence, even for bad headers."""
    reader = _Reader(data)
    strings = wts or {}
    info = W3fInfo(raw_bytes=data)
    try:
        info.version = reader.i32("version")
        if info.version not in SUPPORTED_W3F_VERSIONS:
            reader.problem(
                W3fDiagnostic.UNSUPPORTED_VERSION,
                "version",
                0,
                f"unverified W3F layout {info.version}; remaining bytes retained",
            )
        else:
            info.campaign_version = reader.i32("campaign_version")
            info.editor_version = reader.i32("editor_version")
            info.name = _display(reader, strings, "name")
            info.difficulty = _display(reader, strings, "difficulty")
            info.author = _display(reader, strings, "author")
            info.description = _display(reader, strings, "description")
            info.header_complete = True
            _parse_campaign_metadata(reader, info)
            _parse_map_entries(reader, info, strings)
            info.maps_complete = True
            if reader.remaining:
                reader.problem(
                    W3fDiagnostic.TRAILING_DATA,
                    "unconsumed_data",
                    reader.position,
                    f"{reader.remaining} bytes follow the verified W3F layout",
                )
    except _TruncatedRead:
        reader.problem(
            W3fDiagnostic.TRUNCATED,
            reader.current_field,
            reader.position,
            "incomplete W3F field or count exceeds the remaining encoded bytes",
        )
    info.consumed_bytes = reader.position
    info.unconsumed_data = data[reader.position :]
    info.byte_fields = tuple(reader.byte_fields)
    info.diagnostics = tuple(reader.diagnostics)
    info.diagnostic = info.diagnostics[0].code if info.diagnostics else None
    info.complete = info.maps_complete and not info.diagnostics
    return info


def _parse_campaign_metadata(reader: _Reader, info: W3fInfo) -> None:
    info.campaign_flags = reader.i32("campaign_flags")
    info.background_index = reader.i32("background_index")
    info.background_path = reader.cstr("background_path")
    info.minimap_path = reader.cstr("minimap_path")
    info.ambient_index = reader.i32("ambient_index")
    info.ambient_path = reader.cstr("ambient_path")
    info.fog_style = reader.i32("fog_style")
    info.fog_start_z = reader.f32("fog_start_z")
    info.fog_end_z = reader.f32("fog_end_z")
    info.fog_density = reader.f32("fog_density")
    info.fog_color = tuple(reader.bytes(4, "fog_color"))
    info.race = reader.i32("race")
    if info.version >= 3:
        info.fog_height_start = reader.f32("fog_height_start")
        info.fog_height_end = reader.f32("fog_height_end")
        info.fog_linear_start = reader.f32("fog_linear_start")
        info.fog_linear_end = reader.f32("fog_linear_end")
        info.fog_max_opacity = reader.f32("fog_max_opacity")
        info.fog_draw_over_sky = reader.i32("fog_draw_over_sky")
    if info.version >= 2:
        info.background_version = reader.i32("background_version")


def _parse_map_entries(
    reader: _Reader,
    info: W3fInfo,
    strings: Mapping[int, str],
) -> None:
    buttons = info.map_buttons
    orders = info.map_order
    try:
        button_count = reader.count(_MIN_MAP_BUTTON_BYTES, "map_button_count")
        for index in range(button_count):
            prefix = f"map_buttons[{index}]"
            initially_visible = reader.i32(prefix + ".initially_visible") != 0
            chapter_name = _display(reader, strings, prefix + ".chapter_name")
            display_name = _display(reader, strings, prefix + ".display_name")
            path = reader.cstr(prefix + ".path")
            buttons.append(
                CampaignMapEntry(
                    path=path,
                    display_name=display_name,
                    chapter_name=chapter_name,
                    initially_visible=initially_visible,
                )
            )
        order_count = reader.count(_MIN_MAP_ORDER_BYTES, "map_order_count")
        for index in range(order_count):
            prefix = f"map_order[{index}]"
            reserved = reader.cstr(prefix + ".reserved")
            path = reader.cstr(prefix + ".path")
            orders.append((reserved, path))
    finally:
        info.maps[:] = _combine_map_entries(buttons, [path for _, path in orders])


def _display(reader: _Reader, strings: Mapping[int, str], name: str) -> str:
    return _display_value(reader.cstr(name), strings)


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
            combined.append(
                CampaignMapEntry(
                    path=path,
                    display_name=button.display_name,
                    chapter_name=button.chapter_name,
                    initially_visible=button.initially_visible,
                )
            )
    for button in buttons:
        key = _path_key(button.path)
        if key not in used:
            combined.append(button)
            used.add(key)
    return combined


def _path_key(path: str) -> str:
    return path.replace("/", "\\").casefold()


def w3f_info_to_dict(info: W3fInfo) -> dict[str, object]:
    """JSON-safe complete metadata, raw bytes, ranges and failure boundaries."""
    values = asdict(info)
    values["raw_bytes_base64"] = base64.b64encode(info.raw_bytes).decode("ascii")
    values["unconsumed_data_base64"] = base64.b64encode(info.unconsumed_data).decode(
        "ascii"
    )
    del values["raw_bytes"], values["unconsumed_data"]
    values["byte_fields"] = [
        {
            "name": row.name,
            "offset": row.offset,
            "end_offset": row.end_offset,
            "value": _json_scalar(row.value),
            "raw_bytes_base64": base64.b64encode(row.raw_bytes).decode("ascii"),
        }
        for row in info.byte_fields
    ]
    return {name: _json_scalar(value) for name, value in values.items()}


def _json_scalar(value: object) -> object:
    return (
        str(value) if isinstance(value, float) and not math.isfinite(value) else value
    )
