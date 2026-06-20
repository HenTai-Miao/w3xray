"""war3map.w3e 地形元数据解析。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
from typing import Final

W3E_FILE: Final = "war3map.w3e"
_MAGIC: Final = b"W3E!"
_ID_SIZE: Final = 4
_MAX_TILE_IDS: Final = 256


@dataclass(frozen=True, slots=True)
class TerrainInfo:
    version: int
    base_tileset: str
    custom_tilesets: bool
    ground_tiles: tuple[str, ...]
    cliff_tiles: tuple[str, ...]
    width: int
    height: int


def parse_w3e_header(data: bytes) -> TerrainInfo | None:
    """解析 W3E 头部里的地形集和网格尺寸；失败返回 None。"""
    try:
        return _parse_w3e_header(data)
    except ValueError:
        return None


def terrain_info_from_map_path(path: str) -> TerrainInfo | None:
    """从地图 MPQ 中读取 war3map.w3e 并返回地形摘要；失败时静默降级。"""
    from .mpq import MPQArchive

    if not Path(path).is_file():
        return None
    try:
        with MPQArchive(path) as archive:
            if not archive.has_file(W3E_FILE):
                return None
            return parse_w3e_header(archive.read_file(W3E_FILE))
    except (OSError, ValueError, KeyError):
        return None


def _parse_w3e_header(data: bytes) -> TerrainInfo:
    if data[:4] != _MAGIC:
        raise ValueError("不是 W3E 地形文件")
    version, offset = _read_i32(data, 4)
    base_tileset = _read_tileset(data, offset)
    offset += 1
    custom_tileset_flag, offset = _read_i32(data, offset)
    ground_count, offset = _read_i32(data, offset)
    ground_tiles, offset = _read_tile_ids(data, offset, ground_count)
    cliff_count, offset = _read_i32(data, offset)
    cliff_tiles, offset = _read_tile_ids(data, offset, cliff_count)
    width, height = _read_size(data, offset)
    return TerrainInfo(
        version=version,
        base_tileset=base_tileset,
        custom_tilesets=bool(custom_tileset_flag),
        ground_tiles=ground_tiles,
        cliff_tiles=cliff_tiles,
        width=width,
        height=height,
    )


def _read_i32(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 4 > len(data):
        raise ValueError("W3E 头部被截断")
    return struct.unpack_from("<i", data, offset)[0], offset + 4


def _read_tileset(data: bytes, offset: int) -> str:
    if offset >= len(data):
        raise ValueError("W3E 缺少基础地形集")
    value = data[offset:offset + 1].decode("ascii", errors="replace")
    return value or "?"


def _read_tile_ids(data: bytes, offset: int, count: int) -> tuple[tuple[str, ...], int]:
    if count < 0 or count > _MAX_TILE_IDS:
        raise ValueError("W3E 纹理数量异常")
    end = offset + count * _ID_SIZE
    if end > len(data):
        raise ValueError("W3E 纹理表被截断")
    ids = tuple(_decode_id(data[i:i + _ID_SIZE]) for i in range(offset, end, _ID_SIZE))
    return ids, end


def _read_size(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 8 > len(data):
        raise ValueError("W3E 缺少网格尺寸")
    width, height = struct.unpack_from("<ii", data, offset)
    if width <= 0 or height <= 0:
        raise ValueError("W3E 网格尺寸异常")
    return width, height


def _decode_id(raw: bytes) -> str:
    return raw.decode("ascii", errors="replace").rstrip("\x00") or "?"
