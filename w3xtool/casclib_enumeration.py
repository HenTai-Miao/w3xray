"""Typed models and ctypes ABI for CascLib full-storage enumeration."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol, runtime_checkable

CASC_INVALID_ID = 0xFFFFFFFF
CASC_INVALID_SIZE64 = 0xFFFFFFFFFFFFFFFF
ERROR_NO_MORE_FILES = 18
MAX_PATH = 260
MD5_HASH_SIZE = 16


class CascNameType(IntEnum):
    """How CascLib identified an enumerated storage entry."""

    FULL = 0
    FILE_DATA_ID = 1
    CKEY = 2
    EKEY = 3


@dataclass(frozen=True, slots=True)
class CascEntry:
    """One addressable entry from the CASC root or encoding table."""

    name: str
    name_type: CascNameType
    file_data_id: int | None
    ckey: str
    ekey: str
    size: int | None
    is_local: bool
    locale_flags: int | None
    content_flags: int | None

    @property
    def read_name(self) -> str:
        """Return the CascLib-compatible path, ID, or key name."""
        return self.name

    @property
    def has_resolved_path(self) -> bool:
        """Return whether the root supplied a real logical path."""
        return self.name_type is CascNameType.FULL


@runtime_checkable
class CascLibEnumerationApi(Protocol):
    """Optional native operations required for streaming a CASC inventory."""

    def find_first(
        self,
        storage: int,
        mask: str,
        listfile: str | None,
    ) -> tuple[int, CascEntry] | None: ...

    def find_next(self, search: int) -> CascEntry | None: ...

    def close_find(self, search: int) -> None: ...


class CascFindData(ctypes.Structure):
    """Pinned x64 layout of CascLib 3.0 ``CASC_FIND_DATA``."""

    _fields_ = [
        ("szFileName", ctypes.c_char * MAX_PATH),
        ("CKey", ctypes.c_ubyte * MD5_HASH_SIZE),
        ("EKey", ctypes.c_ubyte * MD5_HASH_SIZE),
        ("TagBitMask", ctypes.c_uint64),
        ("FileSize", ctypes.c_uint64),
        ("szPlainName", ctypes.c_void_p),
        ("dwFileDataId", ctypes.c_uint32),
        ("dwLocaleFlags", ctypes.c_uint32),
        ("dwContentFlags", ctypes.c_uint32),
        ("dwSpanCount", ctypes.c_uint32),
        ("bFileAvailable", ctypes.c_uint32, 1),
        ("NameType", ctypes.c_int32),
    ]


def bind_enumeration_signatures(library: ctypes.CDLL) -> None:
    """Bind the pinned CascLib 3.0 search function signatures."""
    find_data_pointer = ctypes.POINTER(CascFindData)
    library.CascFindFirstFile.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        find_data_pointer,
        ctypes.c_wchar_p,
    ]
    library.CascFindFirstFile.restype = ctypes.c_void_p
    library.CascFindNextFile.argtypes = [ctypes.c_void_p, find_data_pointer]
    library.CascFindNextFile.restype = ctypes.c_bool
    library.CascFindClose.argtypes = [ctypes.c_void_p]
    library.CascFindClose.restype = ctypes.c_bool


def entry_from_find_data(data: CascFindData) -> CascEntry:
    """Convert the native search buffer to an immutable Python value."""
    name_bytes = bytes(data.szFileName).split(b"\0", 1)[0]
    return CascEntry(
        name=name_bytes.decode("utf-8", "replace"),
        name_type=CascNameType(data.NameType),
        file_data_id=_optional_uint32(data.dwFileDataId),
        ckey=bytes(data.CKey).hex(),
        ekey=bytes(data.EKey).hex(),
        size=None if data.FileSize == CASC_INVALID_SIZE64 else data.FileSize,
        is_local=bool(data.bFileAvailable),
        locale_flags=_optional_uint32(data.dwLocaleFlags),
        content_flags=_optional_uint32(data.dwContentFlags),
    )


def _optional_uint32(value: int) -> int | None:
    return None if value == CASC_INVALID_ID else value
