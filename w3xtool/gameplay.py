"""war3mapMisc.txt 游戏平衡常数解析。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .war3_encoding import decode_warcraft_string

MISC_FILE: Final = "war3mapMisc.txt"


@dataclass(frozen=True, slots=True)
class GameplayConstant:
    section: str
    key: str
    value: str


def parse_gameplay_constants(text: str) -> tuple[GameplayConstant, ...]:
    """解析 INI 风格的游戏平衡常数覆盖项。"""
    section = ""
    constants: list[GameplayConstant] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("//", "#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if not key:
            continue
        constants.append(GameplayConstant(section, key, value.strip()))
    return tuple(constants)


def gameplay_constants_from_map_path(path: str) -> tuple[GameplayConstant, ...]:
    """从地图 MPQ 中读取 war3mapMisc.txt；缺失或失败时返回空元组。"""
    from .mpq import MPQArchive

    if not Path(path).is_file():
        return ()
    try:
        with MPQArchive(path) as archive:
            if not archive.has_file(MISC_FILE):
                return ()
            return parse_gameplay_constants(_decode_text(archive.read_file(MISC_FILE)))
    except (OSError, ValueError, KeyError, UnicodeError):
        return ()


def _decode_text(data: bytes) -> str:
    return decode_warcraft_string(data)
