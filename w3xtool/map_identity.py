"""Static identity facts for a readable map archive file."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import zlib
from typing import Final

_CHUNK_SIZE: Final = 1024 * 1024


@dataclass(frozen=True, slots=True)
class MapIdentity:
    readable: bool
    size: int = 0
    crc32: str = ""
    sha1: str = ""


def build_map_identity(path: str) -> MapIdentity:
    """Return stable file identity hashes when ``path`` is a readable file."""
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
