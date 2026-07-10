"""Static identity facts for a readable map archive file."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from mmap import mmap
import os
import struct
import zlib
from typing import TYPE_CHECKING, Final

from .campaign_sources import open_map_source

if TYPE_CHECKING:
    from .map_data import MapData

_CHUNK_SIZE: Final = 1024 * 1024


@dataclass(frozen=True, slots=True)
class MapIdentity:
    readable: bool
    size: int = 0
    crc32: str = ""
    sha1: str = ""


def build_map_identity(source: str | MapData) -> MapIdentity:
    """Return stable file identity hashes for a path or retained map source."""
    if isinstance(source, str):
        return _build_path_identity(source)
    if source.archive_source is None:
        return _build_path_identity(source.path)
    try:
        with open_map_source(source) as archive:
            return _build_buffer_identity(archive._data)
    except (OSError, ValueError, struct.error):
        return MapIdentity(readable=False)


def _build_path_identity(path: str) -> MapIdentity:
    """Hash a readable on-disk map exactly as previous path calls did."""
    if not path or not os.path.isfile(path):
        return MapIdentity(readable=False)
    sha1 = hashlib.sha1()
    crc = 0
    size = 0
    try:
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(_CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                crc = zlib.crc32(chunk, crc)
                sha1.update(chunk)
    except OSError:
        return MapIdentity(readable=False)
    return MapIdentity(
        readable=True,
        size=size,
        crc32=f"{crc & 0xFFFFFFFF:08x}",
        sha1=sha1.hexdigest(),
    )


def _build_buffer_identity(data: bytes | mmap) -> MapIdentity:
    """Hash raw archive bytes without reading or decompressing archive members."""
    sha1 = hashlib.sha1()
    crc = 0
    size = 0
    for start in range(0, len(data), _CHUNK_SIZE):
        chunk = data[start:start + _CHUNK_SIZE]
        size += len(chunk)
        crc = zlib.crc32(chunk, crc)
        sha1.update(chunk)
    return MapIdentity(
        readable=True,
        size=size,
        crc32=f"{crc & 0xFFFFFFFF:08x}",
        sha1=sha1.hexdigest(),
    )
