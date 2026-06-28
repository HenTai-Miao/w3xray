"""war3map.mmp minimap preview icon parser."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import struct

_MAX_ICONS = 100_000
_TYPE_LABELS = {
    0: "金矿",
    1: "中立建筑",
    2: "玩家出生点",
}


@dataclass(frozen=True, slots=True)
class PreviewIcon:
    icon_type: int
    x: int
    y: int
    color_rgb: tuple[int, int, int]
    alpha: int

    @property
    def type_label(self) -> str:
        return _TYPE_LABELS.get(self.icon_type, f"未知标记({self.icon_type})")


@dataclass(frozen=True, slots=True)
class PreviewIconSummary:
    version: int
    icons: tuple[PreviewIcon, ...]

    @property
    def icon_count(self) -> int:
        return len(self.icons)

    @property
    def player_start_count(self) -> int:
        return self.count_by_type.get(2, 0)

    @property
    def gold_mine_count(self) -> int:
        return self.count_by_type.get(0, 0)

    @property
    def neutral_building_count(self) -> int:
        return self.count_by_type.get(1, 0)

    @property
    def count_by_type(self) -> Counter:
        return Counter(icon.icon_type for icon in self.icons)


class _Reader:
    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    def i32(self) -> int:
        if self._pos + 4 > len(self._data):
            raise IndexError("i32 越界")
        value = struct.unpack_from("<i", self._data, self._pos)[0]
        self._pos += 4
        return value

    def color_bgra(self) -> tuple[tuple[int, int, int], int]:
        if self._pos + 4 > len(self._data):
            raise IndexError("color 越界")
        blue, green, red, alpha = self._data[self._pos:self._pos + 4]
        self._pos += 4
        return (red, green, blue), alpha


def parse_preview_icons(data: bytes) -> PreviewIconSummary:
    """Parse minimap preview icons from war3map.mmp."""
    try:
        reader = _Reader(data)
        version = reader.i32()
        count = _bounded(reader.i32())
        icons = tuple(_read_icon(reader) for _ in range(count))
        return PreviewIconSummary(version=version, icons=icons)
    except (struct.error, IndexError) as exc:
        raise ValueError("truncated war3map.mmp") from exc


def _read_icon(reader: _Reader) -> PreviewIcon:
    icon_type = reader.i32()
    x = reader.i32()
    y = reader.i32()
    color, alpha = reader.color_bgra()
    return PreviewIcon(icon_type, x, y, color, alpha)


def _bounded(value: int) -> int:
    if value < 0 or value > _MAX_ICONS:
        raise ValueError(f"invalid war3map.mmp icon count: {value}")
    return value
