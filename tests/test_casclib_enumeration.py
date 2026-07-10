"""CascLib full-root enumeration contracts."""

from __future__ import annotations

from dataclasses import dataclass
import ctypes

import w3xtool.casclib_source as casclib_source
from tests.test_casclib_api import FakeNativeLibrary, NativeFunction
from w3xtool.casclib_api import CtypesCascLibApi
from w3xtool.casclib_enumeration import CascFindData, CascNameType


@dataclass
class FakeEnumerationApi:  # noqa: MUTABLE_OK - records native resource ownership in tests.
    """In-memory CascLib API fake with explicit search-handle tracking."""

    entries: tuple
    closed_searches: list[int]
    next_index: int = 0

    def open_storage(self, _path: str) -> int:
        return 101

    def close_storage(self, _handle: int) -> None:
        return None

    def open_file(self, _storage: int, _name: str) -> int:
        return 202

    def file_size(self, _handle: int) -> int:
        return 0

    def read_file(self, _handle: int, _size: int) -> bytes:
        return b""

    def close_file(self, _handle: int) -> None:
        return None

    def find_first(self, _storage: int, _mask: str, _listfile: str | None):
        self.next_index = 1
        return 303, self.entries[0]

    def find_next(self, _search: int):
        if self.next_index >= len(self.entries):
            return None
        entry = self.entries[self.next_index]
        self.next_index += 1
        return entry

    def close_find(self, search: int) -> None:
        self.closed_searches.append(search)


def test_full_root_enumeration_keeps_unknown_entries_and_closes_search() -> None:
    # Given: CascLib reports one resolved path and one nameless FileDataID entry.
    entry_type = getattr(casclib_source, "CascEntry")
    entries = (
        entry_type(
            name="UI\\TriggerData.txt",
            name_type=CascNameType.FULL,
            file_data_id=None,
            ckey="01" * 16,
            ekey="02" * 16,
            size=10,
            is_local=True,
            locale_flags=0,
            content_flags=0,
        ),
        entry_type(
            name="FILE0000007B.dat",
            name_type=CascNameType.FILE_DATA_ID,
            file_data_id=123,
            ckey="03" * 16,
            ekey="04" * 16,
            size=20,
            is_local=True,
            locale_flags=0,
            content_flags=0,
        ),
    )
    api = FakeEnumerationApi(entries=entries, closed_searches=[])

    # When: the caller stops after consuming the full streaming inventory.
    with casclib_source.CascLibDataSource("C:/Warcraft III", api=api) as source:
        result = tuple(source.iter_entries())

    # Then: unknown paths remain addressable and the native search handle is closed.
    assert result == entries
    assert result[1].read_name == "FILE0000007B.dat"
    assert api.closed_searches == [303]


def test_pinned_x64_find_data_layout_matches_casclib_header() -> None:
    # Given/When: ctypes lays out the pinned CascLib 3.0 search structure.
    size = ctypes.sizeof(CascFindData)

    # Then: pointer and DWORD alignment match the x64 C ABI used by the packaged DLL.
    assert size == 344
    assert CascFindData.szPlainName.offset == 312
    assert CascFindData.NameType.offset == 340


def test_ctypes_enumeration_converts_unknown_file_data_id_entry() -> None:
    # Given: a native DLL returns one nameless Root entry with a stable FileDataID.
    dll = FakeNativeLibrary()
    captured: list[tuple[bytes, str | None]] = []

    def find_first(_storage, mask, data_pointer, listfile):
        data = data_pointer._obj
        data.szFileName = b"FILE0000004D.dat"
        data.CKey[:] = bytes.fromhex("01" * 16)
        data.EKey[:] = bytes.fromhex("02" * 16)
        data.FileSize = 123
        data.dwFileDataId = 77
        data.dwLocaleFlags = 0xFFFFFFFF
        data.dwContentFlags = 4
        data.bFileAvailable = 1
        data.NameType = CascNameType.FILE_DATA_ID
        captured.append((mask, listfile))
        return 303

    dll.CascFindFirstFile = NativeFunction(find_first)
    api = CtypesCascLibApi(library=dll)

    # When: the Python ABI boundary starts full-root enumeration.
    result = api.find_first(101, "*", "C:/listfile.csv")

    # Then: all stable identity fields survive and Unicode listfile uses the wide ABI.
    assert result is not None
    search, entry = result
    assert search == 303
    assert entry.name == "FILE0000004D.dat"
    assert entry.file_data_id == 77
    assert entry.locale_flags is None
    assert entry.content_flags == 4
    assert entry.name_type is CascNameType.FILE_DATA_ID
    assert captured == [(b"*\0", "C:/listfile.csv")]
