"""Typed ctypes boundary for the pinned Windows CascLib build."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Final, Protocol, override

from .casclib_enumeration import (
    ERROR_NO_MORE_FILES,
    CascEntry,
    CascFindData,
    bind_enumeration_signatures,
    entry_from_find_data,
)

ERROR_FILE_NOT_FOUND: Final = 2
ERROR_PROC_NOT_FOUND: Final = 127
MAX_CASC_FILE_SIZE: Final = 40 * 1024 * 1024


class CascLibApi(Protocol):
    """Narrow native operations used by the game-data source."""

    def open_storage(self, path: str) -> int: ...

    def close_storage(self, handle: int) -> None: ...

    def open_file(self, storage: int, name: str) -> int: ...

    def file_size(self, handle: int) -> int: ...

    def read_file(self, handle: int, size: int) -> bytes: ...

    def close_file(self, handle: int) -> None: ...


class _NativeErrorGetter(Protocol):
    def __call__(self) -> int: ...


@dataclass(frozen=True, slots=True)
class CascNativeError(OSError):
    """A CascLib call failed and exposed its thread-local native error."""

    operation: str
    native_error_code: int

    @override
    def __str__(self) -> str:
        return f"{self.operation} failed (native error={self.native_error_code})"


@dataclass(frozen=True, slots=True)
class CascFileNotFoundError(FileNotFoundError):
    """CascOpenFile reported ERROR_FILE_NOT_FOUND for an internal path."""

    name: str
    native_error_code: int

    @override
    def __str__(self) -> str:
        return f"CASC file not found: {self.name} (native error={self.native_error_code})"


@dataclass(frozen=True, slots=True)
class CascPartialReadError(OSError):
    """CascReadFile succeeded without returning the requested byte count."""

    expected: int
    actual: int
    native_error_code: int

    @override
    def __str__(self) -> str:
        return (
            f"CascReadFile partial read: expected={self.expected}, actual={self.actual} "
            f"(native error={self.native_error_code})"
        )


@dataclass(frozen=True, slots=True)
class CascFileTooLargeError(OSError):
    """A resource exceeds the bounded allocation accepted by this application."""

    size: int
    limit: int

    @override
    def __str__(self) -> str:
        return f"CASC resource too large: size={self.size}, limit={self.limit}"


@dataclass(frozen=True, slots=True)
class CascLibLoadError(OSError):
    """The packaged CascLib DLL cannot be selected or loaded."""

    path: Path
    reason: str
    native_error_code: int

    @override
    def __str__(self) -> str:
        suffix = f" (native error={self.native_error_code})" if self.native_error_code else ""
        return f"{self.reason}: {self.path}{suffix}"


class CtypesCascLibApi:
    """ctypes implementation for the x64 Unicode CascLib 3.0 DLL."""

    _library: ctypes.CDLL
    _get_casc_error: _NativeErrorGetter

    def __init__(
        self,
        dll_path: Path | None = None,
        *,
        library: ctypes.CDLL | None = None,
    ) -> None:
        selected_path = dll_path or default_dll_path()
        self._library = library if library is not None else _load_library(selected_path)
        try:
            self._bind_signatures()
        except AttributeError as exc:
            raise CascLibLoadError(
                path=selected_path,
                reason=f"CascLib.dll 缺少必需导出符号：{exc}",
                native_error_code=ERROR_PROC_NOT_FOUND,
            ) from exc
        self._get_casc_error = self._library.GetCascError

    def _bind_signatures(self) -> None:
        handle_pointer = ctypes.POINTER(ctypes.c_void_p)
        self._library.CascOpenStorage.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, handle_pointer]
        self._library.CascOpenStorage.restype = ctypes.c_bool
        self._library.CascCloseStorage.argtypes = [ctypes.c_void_p]
        self._library.CascCloseStorage.restype = ctypes.c_bool
        self._library.CascOpenFile.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            handle_pointer,
        ]
        self._library.CascOpenFile.restype = ctypes.c_bool
        self._library.CascGetFileSize64.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint64),
        ]
        self._library.CascGetFileSize64.restype = ctypes.c_bool
        self._library.CascReadFile.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        self._library.CascReadFile.restype = ctypes.c_bool
        self._library.CascCloseFile.argtypes = [ctypes.c_void_p]
        self._library.CascCloseFile.restype = ctypes.c_bool
        self._library.GetCascError.argtypes = []
        self._library.GetCascError.restype = ctypes.c_uint32
        bind_enumeration_signatures(self._library)

    def open_storage(self, path: str) -> int:
        handle = ctypes.c_void_p()
        if not self._library.CascOpenStorage(path, 0, ctypes.byref(handle)):
            raise self._error("CascOpenStorage")
        return _handle_value(handle, "CascOpenStorage", self._native_error())

    def close_storage(self, handle: int) -> None:
        if not self._library.CascCloseStorage(ctypes.c_void_p(handle)):
            raise self._error("CascCloseStorage")

    def open_file(self, storage: int, name: str) -> int:
        handle = ctypes.c_void_p()
        internal_name = name.replace("/", "\\").encode("utf-8") + b"\0"
        if not self._library.CascOpenFile(
            ctypes.c_void_p(storage),
            internal_name,
            0,
            0,
            ctypes.byref(handle),
        ):
            error_code = self._native_error()
            if error_code == ERROR_FILE_NOT_FOUND:
                raise CascFileNotFoundError(name=name, native_error_code=error_code)
            raise CascNativeError(operation="CascOpenFile", native_error_code=error_code)
        return _handle_value(handle, "CascOpenFile", self._native_error())

    def file_size(self, handle: int) -> int:
        size = ctypes.c_uint64()
        if not self._library.CascGetFileSize64(ctypes.c_void_p(handle), ctypes.byref(size)):
            raise self._error("CascGetFileSize64")
        if size.value > MAX_CASC_FILE_SIZE:
            raise CascFileTooLargeError(size=size.value, limit=MAX_CASC_FILE_SIZE)
        return size.value

    def read_file(self, handle: int, size: int) -> bytes:
        if size > MAX_CASC_FILE_SIZE:
            raise CascFileTooLargeError(size=size, limit=MAX_CASC_FILE_SIZE)
        buffer = ctypes.create_string_buffer(size)
        bytes_read = ctypes.c_uint32()
        if not self._library.CascReadFile(
            ctypes.c_void_p(handle),
            buffer,
            size,
            ctypes.byref(bytes_read),
        ):
            raise self._error("CascReadFile")
        if bytes_read.value != size:
            raise CascPartialReadError(
                expected=size,
                actual=bytes_read.value,
                native_error_code=self._native_error(),
            )
        return buffer.raw[:bytes_read.value]

    def close_file(self, handle: int) -> None:
        if not self._library.CascCloseFile(ctypes.c_void_p(handle)):
            raise self._error("CascCloseFile")

    def find_first(
        self,
        storage: int,
        mask: str,
        listfile: str | None,
    ) -> tuple[int, CascEntry] | None:
        data = CascFindData()
        search = self._library.CascFindFirstFile(
            ctypes.c_void_p(storage),
            mask.encode("utf-8") + b"\0",
            ctypes.byref(data),
            listfile,
        )
        value = ctypes.c_void_p(search).value
        if value == ctypes.c_void_p(-1).value or value is None:
            error_code = self._native_error()
            if error_code in {0, ERROR_NO_MORE_FILES}:
                return None
            raise CascNativeError("CascFindFirstFile", error_code)
        return value, entry_from_find_data(data)

    def find_next(self, search: int) -> CascEntry | None:
        data = CascFindData()
        if self._library.CascFindNextFile(ctypes.c_void_p(search), ctypes.byref(data)):
            return entry_from_find_data(data)
        error_code = self._native_error()
        if error_code in {0, ERROR_NO_MORE_FILES}:
            return None
        raise CascNativeError("CascFindNextFile", error_code)

    def close_find(self, search: int) -> None:
        if not self._library.CascFindClose(ctypes.c_void_p(search)):
            raise self._error("CascFindClose")

    def _native_error(self) -> int:
        return self._get_casc_error()

    def _error(self, operation: str) -> CascNativeError:
        return CascNativeError(operation=operation, native_error_code=self._native_error())


def default_dll_path() -> Path:
    """Return the bundled path, falling back to the local Windows build output."""
    module_root = Path(__file__).resolve().parents[1]
    bundled = module_root / "CascLib.dll"
    if bundled.is_file():
        return bundled
    return module_root / "third_party" / "CascLib" / "bin" / "win-x64" / "CascLib.dll"


def _load_library(path: Path) -> ctypes.CDLL:
    if sys.platform != "win32":
        raise CascLibLoadError(path=path, reason="CascLib 仅支持 Windows", native_error_code=0)
    if not path.is_file():
        raise CascLibLoadError(path=path, reason="CascLib.dll 不存在", native_error_code=2)
    try:
        return ctypes.WinDLL(str(path))
    except OSError as exc:
        code = getattr(exc, "winerror", None) or exc.errno or 0
        reason = "CascLib.dll 架构错误" if code == 193 else "CascLib.dll 加载失败"
        raise CascLibLoadError(path=path, reason=reason, native_error_code=code) from exc


def _handle_value(handle: ctypes.c_void_p, operation: str, error_code: int) -> int:
    value = handle.value
    if not isinstance(value, int):
        raise CascNativeError(operation=operation, native_error_code=error_code)
    return value
