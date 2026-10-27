"""Hold Windows source ancestry and leaves against redirection while reading."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
import ctypes
from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Final, final, override

from .windows_output_paths import native_output_path


_FILE_READ_ATTRIBUTES: Final = 0x0080
_FILE_READ_DATA_OR_LIST_DIRECTORY: Final = 0x0001
_FILE_TRAVERSE: Final = 0x0020
_FILE_SHARE_READ: Final = 0x0001
_OPEN_EXISTING: Final = 3
_FILE_FLAG_BACKUP_SEMANTICS: Final = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT: Final = 0x00200000
_FILE_ATTRIBUTE_DIRECTORY: Final = 0x0010
_FILE_ATTRIBUTE_REPARSE_POINT: Final = 0x0400
_FILE_TYPE_DISK: Final = 1


class WindowsSourceError(OSError):
    """A Windows source cannot be proved safe for a complete read."""

    __slots__: tuple[str, ...] = ("path", "reason")

    path: Path
    reason: str

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(reason)
        self.path = path
        self.reason = reason

    @override
    def __str__(self) -> str:
        return f"cannot read Windows source {self.path}: {self.reason}"


class _BasicInfo(ctypes.Structure):
    _fields_ = (
        ("CreationTime", ctypes.c_int64),
        ("LastAccessTime", ctypes.c_int64),
        ("LastWriteTime", ctypes.c_int64),
        ("ChangeTime", ctypes.c_int64),
        ("FileAttributes", ctypes.c_uint32),
    )


class _StandardInfo(ctypes.Structure):
    _fields_ = (
        ("AllocationSize", ctypes.c_int64),
        ("EndOfFile", ctypes.c_int64),
        ("NumberOfLinks", ctypes.c_uint32),
        ("DeletePending", ctypes.c_ubyte),
        ("Directory", ctypes.c_ubyte),
    )


class _IdInfo(ctypes.Structure):
    _fields_ = (
        ("VolumeSerialNumber", ctypes.c_uint64),
        ("FileId", ctypes.c_ubyte * 16),
    )


@dataclass(frozen=True, slots=True)
class _SourceState:
    volume: int
    file_id: bytes
    attributes: int
    size: int
    creation_time: int
    write_time: int
    change_time: int
    directory: bool

    @property
    def identity(self) -> tuple[int, bytes, int, bool]:
        return self.volume, self.file_id, self.attributes, self.directory


@final
class _SourceApi:
    """Read-only native handles whose sharing excludes writers and deletion."""

    def __init__(self) -> None:
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateFileW.argtypes = (
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        )
        self.kernel.CreateFileW.restype = ctypes.c_void_p
        self.kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
        self.kernel.CloseHandle.restype = ctypes.c_int
        self.kernel.GetFileType.argtypes = (ctypes.c_void_p,)
        self.kernel.GetFileType.restype = ctypes.c_uint32
        self.kernel.GetFileInformationByHandleEx.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        )
        self.kernel.GetFileInformationByHandleEx.restype = ctypes.c_int

    def open(self, path: Path, *, directory: bool = False) -> int:
        # READ_ATTRIBUTES alone does not exclude an already open data writer.
        # Traversal protects directories without requiring permission to list them.
        read_access = _FILE_TRAVERSE if directory else _FILE_READ_DATA_OR_LIST_DIRECTORY
        handle = self.kernel.CreateFileW(
            native_output_path(str(path)),
            _FILE_READ_ATTRIBUTES | read_access,
            _FILE_SHARE_READ,
            None,
            _OPEN_EXISTING,
            _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
            None,
        )
        if handle is None or handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        return int(handle)

    def close(self, handle: int) -> None:
        if not self.kernel.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def state(self, handle: int) -> _SourceState:
        if self.kernel.GetFileType(handle) != _FILE_TYPE_DISK:
            raise OSError("source is not a regular disk file or directory")
        basic = _BasicInfo()
        standard = _StandardInfo()
        identity = _IdInfo()
        for kind, details in ((0, basic), (1, standard), (18, identity)):
            if not self.kernel.GetFileInformationByHandleEx(
                handle, kind, ctypes.byref(details), ctypes.sizeof(details)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
        if standard.DeletePending:
            raise OSError("source is pending deletion")
        return _SourceState(
            int(identity.VolumeSerialNumber),
            bytes(identity.FileId),
            int(basic.FileAttributes),
            int(standard.EndOfFile),
            int(basic.CreationTime),
            int(basic.LastWriteTime),
            int(basic.ChangeTime),
            bool(standard.Directory),
        )


@final
class WindowsSourceRoot:
    """One source root whose complete native ancestry stays held for a replay.

    Every component is opened without following its final reparse point. Holding
    all previously opened ancestors without write/delete sharing makes the next
    full-path component open equivalent to traversal through those identities.
    The temporary locks end with this context; no persistent state is installed.
    """

    __slots__: tuple[str, ...] = ("path", "_api", "_stack", "_ancestors")

    def __init__(
        self,
        path: Path,
        api: _SourceApi,
        stack: ExitStack,
        ancestors: tuple[tuple[Path, int, _SourceState], ...],
    ) -> None:
        self.path = path
        self._api = api
        self._stack = stack
        self._ancestors = ancestors

    @classmethod
    def open(cls, path: Path) -> WindowsSourceRoot:
        if os.name != "nt":
            raise WindowsSourceError(path, "Windows protected source reads unavailable")
        if not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
            raise WindowsSourceError(path, "source root is not canonical absolute text")
        stack = ExitStack()
        try:
            api = _SourceApi()
            ancestors: list[tuple[Path, int, _SourceState]] = []
            for component in (*reversed(path.parents), path):
                handle, state = _hold_component(api, stack, component, directory=True)
                ancestors.append((component, handle, state))
            return cls(path, api, stack, tuple(ancestors))
        except (OSError, AttributeError, ValueError) as exc:
            try:
                stack.close()
            except OSError as cleanup:
                raise WindowsSourceError(
                    path, f"{exc}; source handle cleanup failed: {cleanup}"
                ) from exc
            raise WindowsSourceError(path, str(exc)) from exc

    def __enter__(self) -> WindowsSourceRoot:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._stack.close()
        except OSError as exc:
            raise WindowsSourceError(self.path, str(exc)) from exc

    @contextmanager
    def protect(self, relative: PurePosixPath) -> Iterator[None]:
        """Keep every source component fixed across the caller's complete read."""
        path = self.path.joinpath(*relative.parts)
        if (
            relative.is_absolute()
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise WindowsSourceError(path, "source path is not canonical relative text")
        try:
            with ExitStack() as stack:
                directories = list(self._ancestors)
                parent = self.path
                _require_directories(self._api, directories)
                for part in relative.parts[:-1]:
                    parent /= part
                    handle, state = _hold_component(
                        self._api, stack, parent, directory=True
                    )
                    directories.append((parent, handle, state))
                leaf, before = _hold_component(self._api, stack, path, directory=False)
                yield
                if self._api.state(leaf) != before:
                    raise WindowsSourceError(
                        path, "source identity or metadata changed"
                    )
                _require_directories(self._api, directories)
        except WindowsSourceError:
            raise
        except (OSError, ValueError) as exc:
            raise WindowsSourceError(path, str(exc)) from exc


def _hold_component(
    api: _SourceApi,
    stack: ExitStack,
    path: Path,
    *,
    directory: bool,
) -> tuple[int, _SourceState]:
    handle = api.open(path, directory=directory)
    _ = stack.callback(api.close, handle)
    state = api.state(handle)
    if state.attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        raise WindowsSourceError(path, "source component is a reparse point or symlink")
    if (
        state.directory != directory
        or bool(state.attributes & _FILE_ATTRIBUTE_DIRECTORY) != directory
    ):
        kind = "directory" if directory else "regular file"
        raise WindowsSourceError(path, f"source is not a {kind}")
    return handle, state


def _require_directories(
    api: _SourceApi, directories: list[tuple[Path, int, _SourceState]]
) -> None:
    for path, handle, before in directories:
        if api.state(handle).identity != before.identity:
            raise WindowsSourceError(path, "source directory identity changed")


__all__ = ("WindowsSourceError", "WindowsSourceRoot")
