"""Warcraft III .wgc game configuration parser."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct

_MAX_PLAYERS = 32
_RACE_NAMES = {
    0x01: "人族",
    0x02: "兽族",
    0x04: "暗夜精灵",
    0x08: "亡灵",
    0x20: "随机",
}
_COLOR_NAMES = (
    "红", "蓝", "青", "紫", "黄", "橙", "绿", "粉",
    "灰", "浅蓝", "深绿", "棕", "栗", "海军蓝", "绿松石", "紫罗兰",
    "小麦", "桃", "薄荷", "薰衣草", "煤黑", "雪白", "祖母绿", "花生",
)
_AI_DIFFICULTY = {0: "简单", 1: "普通", 2: "困难"}


@dataclass(frozen=True, slots=True)
class GameConfigPlayer:
    slot_id: int
    team: int
    race: int
    color: int
    handicap: int
    flags: int
    ai_difficulty: int
    custom_ai_path: str

    @property
    def is_user(self) -> bool:
        return bool(self.flags & 0x01)

    @property
    def is_observer(self) -> bool:
        return bool(self.flags & 0x02)

    @property
    def load_custom_ai(self) -> bool:
        return bool(self.flags & 0x04)

    @property
    def ai_path_is_absolute(self) -> bool:
        return bool(self.flags & 0x08)

    @property
    def kind_label(self) -> str:
        if self.is_observer:
            return "观察者"
        return "玩家" if self.is_user else "电脑"

    @property
    def race_label(self) -> str:
        return _RACE_NAMES.get(self.race, f"未知种族({self.race})")

    @property
    def color_label(self) -> str:
        if 0 <= self.color < len(_COLOR_NAMES):
            return _COLOR_NAMES[self.color]
        return f"颜色{self.color}"

    @property
    def ai_difficulty_label(self) -> str:
        return _AI_DIFFICULTY.get(self.ai_difficulty, f"未知AI({self.ai_difficulty})")


@dataclass(frozen=True, slots=True)
class GameConfiguration:
    format_version: int
    flags: int
    base_speed: int
    map_path: str
    players: tuple[GameConfigPlayer, ...]

    @property
    def fog_of_war_disabled(self) -> bool:
        return bool(self.flags & 0x01)

    @property
    def victory_defeat_disabled(self) -> bool:
        return bool(self.flags & 0x02)

    @property
    def speed_label(self) -> str:
        if self.base_speed == 0:
            return "暂停"
        return f"{self.base_speed * 100}%"

    @property
    def human_count(self) -> int:
        return sum(1 for player in self.players if player.is_user and not player.is_observer)

    @property
    def computer_count(self) -> int:
        return sum(1 for player in self.players if not player.is_user and not player.is_observer)

    @property
    def observer_count(self) -> int:
        return sum(1 for player in self.players if player.is_observer)


@dataclass(frozen=True, slots=True)
class NamedGameConfiguration:
    source: str
    config: GameConfiguration


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

    def cstr(self) -> str:
        end = self._data.find(b"\x00", self._pos)
        if end < 0:
            raise IndexError("cstr 缺少终止符")
        raw = self._data[self._pos:end]
        self._pos = end + 1
        return _decode_string(raw)


def parse_game_configuration(data: bytes) -> GameConfiguration:
    """Parse a .wgc game configuration.

    Raises ValueError for malformed or unsupported payloads. Callers that load
    maps should catch it and treat the configuration as absent.
    """
    try:
        reader = _Reader(data)
        version = reader.i32()
        if version <= 0 or version > 10:
            raise ValueError(f"unsupported .wgc version: {version}")
        flags = reader.i32()
        base_speed = reader.i32()
        map_path = reader.cstr()
        count = reader.i32()
        if count < 0 or count > _MAX_PLAYERS:
            raise ValueError(f"invalid .wgc player count: {count}")
        players = tuple(_read_player(reader) for _ in range(count))
        return GameConfiguration(version, flags, base_speed, map_path, players)
    except (struct.error, IndexError) as exc:
        raise ValueError("truncated .wgc game configuration") from exc


def read_game_configuration_file(path: str | Path) -> GameConfiguration:
    return parse_game_configuration(Path(path).read_bytes())


def find_internal_game_config_names(names: list[str]) -> tuple[str, ...]:
    """Return unique .wgc names from an archive list, preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        lowered = name.lower()
        if not lowered.endswith(".wgc") or lowered in seen:
            continue
        seen.add(lowered)
        result.append(name)
    return tuple(result)


def _read_player(reader: _Reader) -> GameConfigPlayer:
    return GameConfigPlayer(
        slot_id=reader.i32(),
        team=reader.i32(),
        race=reader.i32(),
        color=reader.i32(),
        handicap=reader.i32(),
        flags=reader.i32(),
        ai_difficulty=reader.i32(),
        custom_ai_path=reader.cstr(),
    )


def _decode_string(raw: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")
