"""ctypes ABI and native error contract tests for CascLib."""

from __future__ import annotations

import ctypes

import pytest

from w3xtool.casclib_api import (
    MAX_CASC_FILE_SIZE,
    CascFileNotFoundError,
    CascFileTooLargeError,
    CascNativeError,
    CascPartialReadError,
    CtypesCascLibApi,
)


class NativeFunction:
    def __init__(self, callback):
        self.callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.callback(*args)


class FakeNativeLibrary:
    def __init__(self) -> None:
        self.error = 0
        self.storage_path = ""
        self.file_name = b""
        self.file_flags = -1
        self.read_calls = 0
        self.read_payload = b"data"
        self.open_storage_ok = True
        self.open_file_ok = True
        self.size_ok = True
        self.read_ok = True
        self.close_ok = True
        self.CascOpenStorage = NativeFunction(self._open_storage)
        self.CascCloseStorage = NativeFunction(lambda _handle: self.close_ok)
        self.CascOpenFile = NativeFunction(self._open_file)
        self.CascGetFileSize64 = NativeFunction(self._file_size)
        self.CascReadFile = NativeFunction(self._read_file)
        self.CascCloseFile = NativeFunction(lambda _handle: self.close_ok)
        self.CascFindFirstFile = NativeFunction(lambda _storage, _mask, _data, _listfile: -1)
        self.CascFindNextFile = NativeFunction(lambda _search, _data: False)
        self.CascFindClose = NativeFunction(lambda _search: self.close_ok)
        self.GetCascError = NativeFunction(lambda: self.error)

    def _open_storage(self, path, _locale, output) -> bool:
        self.storage_path = path
        output._obj.value = 101 if self.open_storage_ok else None
        return self.open_storage_ok

    def _open_file(self, _storage, name, _locale, flags, output) -> bool:
        self.file_name = name
        self.file_flags = flags
        output._obj.value = 202 if self.open_file_ok else None
        return self.open_file_ok

    def _file_size(self, _handle, output) -> bool:
        output._obj.value = len(self.read_payload)
        return self.size_ok

    def _read_file(self, _handle, buffer, size, bytes_read) -> bool:
        self.read_calls += 1
        assert bytes_read is not None
        count = min(size, len(self.read_payload))
        if count:
            ctypes.memmove(buffer, self.read_payload, count)
        bytes_read._obj.value = count
        return self.read_ok


def test_ctypes_api_binds_exact_unicode_and_narrow_abi() -> None:
    # Given: a fake DLL exporting all required CascLib symbols.
    dll = FakeNativeLibrary()

    # When: the ctypes adapter binds and calls storage/file open.
    api = CtypesCascLibApi(library=dll)
    storage = api.open_storage("C:/魔兽争霸 III")
    file_handle = api.open_file(storage, "UI/TriggerData.txt")

    # Then: every symbol has the pinned ABI and the internal name is NUL-terminated bytes.
    assert dll.CascOpenStorage.argtypes == [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    assert dll.CascOpenStorage.restype is ctypes.c_bool
    assert dll.CascCloseStorage.argtypes == [ctypes.c_void_p]
    assert dll.CascCloseStorage.restype is ctypes.c_bool
    assert dll.CascOpenFile.argtypes == [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    assert dll.CascOpenFile.restype is ctypes.c_bool
    assert dll.CascGetFileSize64.argtypes == [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint64),
    ]
    assert dll.CascGetFileSize64.restype is ctypes.c_bool
    assert dll.CascReadFile.argtypes == [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    assert dll.CascReadFile.restype is ctypes.c_bool
    assert dll.CascCloseFile.argtypes == [ctypes.c_void_p]
    assert dll.CascCloseFile.restype is ctypes.c_bool
    assert dll.GetCascError.argtypes == []
    assert dll.GetCascError.restype is ctypes.c_uint32
    assert dll.storage_path == "C:/魔兽争霸 III"
    assert dll.file_name == b"UI\\TriggerData.txt\0"
    assert dll.file_flags == 0
    assert file_handle == 202


def test_fake_names_returned_by_find_use_casc_open_by_name_contract() -> None:
    # Given: CascLib's documented synthetic FileDataID name from CASC_FIND_DATA.
    dll = FakeNativeLibrary()
    api = CtypesCascLibApi(library=dll)

    # When: the synthetic name is reopened exactly as returned by enumeration.
    _ = api.open_file(101, "FILE0000004D.dat")

    # Then: CascOpenFile receives the ASCII name with CASC_OPEN_BY_NAME (zero).
    assert dll.file_name == b"FILE0000004D.dat\0"
    assert dll.file_flags == 0


def test_open_file_encodes_non_ascii_logical_paths_as_utf8() -> None:
    # Given: a logical CASC path containing characters outside ASCII.
    dll = FakeNativeLibrary()
    api = CtypesCascLibApi(library=dll)

    # When: the path crosses CascLib's narrow-character API boundary.
    _ = api.open_file(101, "UI\\测试.txt")

    # Then: bytes use the same UTF-8 encoding accepted by enumeration.
    assert dll.file_name == "UI\\测试.txt".encode("utf-8") + b"\0"


def test_open_storage_failure_includes_native_error() -> None:
    # Given: CascOpenStorage fails with a native installation error.
    dll = FakeNativeLibrary()
    dll.open_storage_ok = False
    dll.error = 1006

    # When/Then: the adapter preserves operation and code.
    with pytest.raises(CascNativeError) as caught:
        CtypesCascLibApi(library=dll).open_storage("C:/Warcraft III")
    assert caught.value.operation == "CascOpenStorage"
    assert caught.value.native_error_code == 1006


@pytest.mark.parametrize(
    ("error_code", "error_type"),
    [(2, CascFileNotFoundError), (1005, CascNativeError)],
)
def test_open_file_distinguishes_missing_from_native_failure(error_code: int, error_type: type[OSError]) -> None:
    # Given: CascOpenFile rejects an internal path.
    dll = FakeNativeLibrary()
    dll.open_file_ok = False
    dll.error = error_code

    # When/Then: only ERROR_FILE_NOT_FOUND becomes a missing-path error.
    with pytest.raises(error_type) as caught:
        CtypesCascLibApi(library=dll).open_file(101, "UI/Missing.txt")
    assert caught.value.native_error_code == error_code


def test_zero_byte_read_passes_real_bytes_read_pointer() -> None:
    # Given: CascLib reports an empty file.
    dll = FakeNativeLibrary()
    dll.read_payload = b""
    api = CtypesCascLibApi(library=dll)

    # When: the adapter reads zero bytes.
    data = api.read_file(202, 0)

    # Then: the native call still ran with DWORD* and returned empty bytes.
    assert data == b""
    assert dll.read_calls == 1


def test_partial_read_is_not_silently_accepted() -> None:
    # Given: CascReadFile succeeds but returns fewer bytes than requested.
    dll = FakeNativeLibrary()
    dll.read_payload = b"ab"
    dll.error = 0

    # When/Then: the adapter reports expected, actual, and the native error state.
    with pytest.raises(CascPartialReadError) as caught:
        CtypesCascLibApi(library=dll).read_file(202, 4)
    assert (caught.value.expected, caught.value.actual) == (4, 2)
    assert caught.value.native_error_code == 0


def test_read_failure_and_oversize_are_distinct() -> None:
    # Given: a DLL with an explicit read failure and a bounded adapter.
    dll = FakeNativeLibrary()
    dll.read_ok = False
    dll.error = 1005
    api = CtypesCascLibApi(library=dll)

    # When/Then: native failure carries its code, while oversize is rejected before allocation.
    with pytest.raises(CascNativeError) as caught:
        api.read_file(202, 4)
    assert caught.value.native_error_code == 1005
    calls = dll.read_calls
    with pytest.raises(CascFileTooLargeError):
        api.read_file(202, MAX_CASC_FILE_SIZE + 1)
    assert dll.read_calls == calls
