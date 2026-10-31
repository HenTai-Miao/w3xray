"""Delete a proved batch stage through held Windows object identities."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path
import stat

from .windows_output_paths import native_output_path
from .windows_source_reads import WindowsSourceRoot

type StageIdentity = tuple[int, int]


class StageCleanupStatus(StrEnum):
    REMOVED = "removed"
    MISSING = "missing"
    UNPROVED = "unproved"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StageCleanupResult:
    status: StageCleanupStatus
    detail: str = ""


@dataclass(frozen=True, slots=True)
class _Entry:
    path: Path
    identity: StageIdentity
    directory: bool


@dataclass(slots=True)
class _OpenedDirectory:
    path: Path
    handle: int
    children: list[_Entry]


class _IdentityInfo(ctypes.Structure):
    _fields_ = (("volume", ctypes.c_uint64), ("file_id", ctypes.c_ubyte * 16))


class _AttributeInfo(ctypes.Structure):
    _fields_ = (("attributes", ctypes.c_uint32), ("tag", ctypes.c_uint32))


class _UnicodeString(ctypes.Structure):
    _fields_ = (
        ("length", ctypes.c_ushort),
        ("capacity", ctypes.c_ushort),
        ("buffer", ctypes.c_wchar_p),
    )


class _ObjectAttributes(ctypes.Structure):
    _fields_ = (
        ("length", ctypes.c_uint32),
        ("root", ctypes.c_void_p),
        ("name", ctypes.POINTER(_UnicodeString)),
        ("attributes", ctypes.c_uint32),
        ("security", ctypes.c_void_p),
        ("quality", ctypes.c_void_p),
    )


class _IoStatus(ctypes.Structure):
    _fields_ = (("status", ctypes.c_void_p), ("information", ctypes.c_size_t))


class _CleanupApi:
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
        self.kernel.GetFileInformationByHandleEx.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        )
        self.kernel.GetFileInformationByHandleEx.restype = ctypes.c_int
        self.kernel.SetFileInformationByHandle.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        )
        self.kernel.SetFileInformationByHandle.restype = ctypes.c_int
        self.kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
        self.kernel.CloseHandle.restype = ctypes.c_int
        self.kernel.LocalFree.argtypes = (ctypes.c_void_p,)
        self.kernel.LocalFree.restype = ctypes.c_void_p
        self.kernel.ReadFile.argtypes = (
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_void_p,
        )
        self.kernel.ReadFile.restype = ctypes.c_int

    def open(self, path: Path, *, deleting: bool = True) -> int:
        handle = self.kernel.CreateFileW(
            native_output_path(str(path)),
            0x00010081 if deleting else 0x81,
            0x1,  # READ sharing only: the opened object cannot be replaced.
            None,
            3,
            0x02200000,
            None,  # OPEN_EXISTING, BACKUP | OPEN_REPARSE_POINT
        )
        if handle is None or handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        return int(handle)

    def create_directory(self, parent: int, name: str) -> int:
        native = ctypes.WinDLL("ntdll")
        native.NtCreateFile.argtypes = (
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_uint32,
            ctypes.POINTER(_ObjectAttributes),
            ctypes.POINTER(_IoStatus),
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
        )
        native.NtCreateFile.restype = ctypes.c_long
        native.RtlNtStatusToDosError.argtypes = (ctypes.c_long,)
        native.RtlNtStatusToDosError.restype = ctypes.c_uint32
        buffer = ctypes.create_unicode_buffer(name)
        length = len(name.encode("utf-16-le"))
        name_value = _UnicodeString(
            length, length + 2, ctypes.cast(buffer, ctypes.c_wchar_p)
        )
        security_api = ctypes.WinDLL("advapi32", use_last_error=True)
        security_api.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
        )
        security_api.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = (
            ctypes.c_int
        )
        security = ctypes.c_void_p()
        # Same protected DACL as Python's Windows mkdir(mode=0o700).
        if not security_api.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;OW)",
            1,
            ctypes.byref(security),
            None,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        handle = ctypes.c_void_p()
        try:
            attributes = _ObjectAttributes(
                ctypes.sizeof(_ObjectAttributes),
                parent,
                ctypes.pointer(name_value),
                0x40,
                security,
                None,
            )
            status = native.NtCreateFile(
                ctypes.byref(handle),
                0x00110081,
                ctypes.byref(attributes),
                ctypes.byref(_IoStatus()),
                None,
                0x10,
                1,
                2,
                0x00200021,
                None,
                0,
            )
        finally:
            self.kernel.LocalFree(security)
        if status < 0:
            raise ctypes.WinError(native.RtlNtStatusToDosError(status))
        if handle.value is None:
            raise OSError("stage creation returned no directory handle")
        return int(handle.value)

    def state(self, handle: int) -> tuple[StageIdentity, bool]:
        attributes = _AttributeInfo()
        identity = _IdentityInfo()
        for kind, value in ((9, attributes), (18, identity)):
            if not self.kernel.GetFileInformationByHandleEx(
                handle, kind, ctypes.byref(value), ctypes.sizeof(value)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
        if attributes.attributes & 0x400:
            raise OSError("stage child is a reparse point")
        inode = int.from_bytes(bytes(identity.file_id), "little")
        if not inode:
            raise OSError("stage object identity is unavailable")
        return (
            (int(identity.volume), inode),
            bool(attributes.attributes & 0x10),
        )

    def delete(self, handle: int) -> None:
        disposition = ctypes.c_ubyte(1)
        if not self.kernel.SetFileInformationByHandle(
            handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    def read(self, handle: int) -> bytes:
        buffer = ctypes.create_string_buffer(1024 * 1024)
        chunks: list[bytes] = []
        while True:
            size = ctypes.c_uint32()
            if not self.kernel.ReadFile(
                handle, buffer, len(buffer), ctypes.byref(size), None
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            if not size.value:
                return b"".join(chunks)
            chunks.append(buffer.raw[: size.value])

    def close(self, handle: int) -> None:
        if not self.kernel.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


def create_owned_stage(path: Path) -> StageIdentity:
    """Create a new directory and capture its identity through that same handle."""
    if os.name != "nt":
        raise OSError("held batch stage creation requires Windows")
    with WindowsSourceRoot.open(path.parent):
        api = _CleanupApi()
        parent = api.open(path.parent, deleting=False)
        try:
            handle = api.create_directory(parent, path.name)
            try:
                identity, directory = api.state(handle)
                if not directory:
                    raise OSError("batch stage is not a regular directory")
                return identity
            finally:
                api.close(handle)
        finally:
            api.close(parent)


def remove_owned_stage(
    path: Path, expected: StageIdentity | None
) -> StageCleanupResult:
    """Retain unproved paths; never recursively delete through a pathname check."""
    if expected is None:
        return StageCleanupResult(
            StageCleanupStatus.UNPROVED, "stage creation identity is unavailable"
        )
    if os.name != "nt":
        return StageCleanupResult(
            StageCleanupStatus.UNPROVED, "held stage cleanup requires Windows"
        )
    try:
        with WindowsSourceRoot.open(path.parent):
            api = _CleanupApi()
            try:
                handle = api.open(path)
            except FileNotFoundError:
                return StageCleanupResult(StageCleanupStatus.MISSING)
            opened: list[_OpenedDirectory] = []
            try:
                actual, directory = api.state(handle)
                if actual != expected or not directory:
                    return StageCleanupResult(
                        StageCleanupStatus.UNPROVED, "stage directory identity changed"
                    )
                opened.append(_OpenedDirectory(path, handle, []))
                handle = -1
                opened[-1].children = _children(path)
                while opened:
                    current = opened[-1]
                    if current.children:
                        child = current.children.pop()
                        _open_child(api, child, opened)
                        continue
                    api.delete(current.handle)
                    api.close(opened.pop().handle)
                return StageCleanupResult(StageCleanupStatus.REMOVED)
            finally:
                handles = [entry.handle for entry in reversed(opened)]
                if handle >= 0:
                    handles.insert(0, handle)
                _close_all(api, handles)
    except (OSError, ValueError) as exc:
        return StageCleanupResult(StageCleanupStatus.FAILED, _exception_detail(exc))


def remove_owned_record(
    path: Path, expected: StageIdentity, payload: bytes
) -> StageCleanupResult:
    """Revalidate complete record bytes and delete through that same held handle."""
    if os.name != "nt":
        return StageCleanupResult(
            StageCleanupStatus.UNPROVED, "held record cleanup requires Windows"
        )
    try:
        with WindowsSourceRoot.open(path.parent):
            api = _CleanupApi()
            try:
                handle = api.open(path)
            except FileNotFoundError:
                return StageCleanupResult(StageCleanupStatus.MISSING)
            try:
                identity, directory = api.state(handle)
                if directory or identity != expected:
                    return StageCleanupResult(
                        StageCleanupStatus.UNPROVED,
                        "transaction record identity changed",
                    )
                if api.read(handle) != payload:
                    return StageCleanupResult(
                        StageCleanupStatus.UNPROVED, "transaction record bytes changed"
                    )
                api.delete(handle)
            finally:
                api.close(handle)
        return StageCleanupResult(StageCleanupStatus.REMOVED)
    except (OSError, ValueError) as exc:
        return StageCleanupResult(StageCleanupStatus.FAILED, _exception_detail(exc))


def _open_child(
    api: _CleanupApi, child: _Entry, opened: list[_OpenedDirectory]
) -> None:
    handle = api.open(child.path)
    try:
        if api.state(handle) != (child.identity, child.directory):
            raise OSError(f"stage child identity changed: {child.path.name}")
        if child.directory:
            opened.append(_OpenedDirectory(child.path, handle, []))
            handle = -1
            opened[-1].children = _children(child.path)
        else:
            api.delete(handle)
    finally:
        if handle >= 0:
            api.close(handle)


def _children(path: Path) -> list[_Entry]:
    with os.scandir(native_output_path(str(path))) as entries:
        return [
            _entry(
                path / item.name, os.lstat(native_output_path(str(path / item.name)))
            )
            for item in entries
        ]


def _close_all(api: _CleanupApi, handles: list[int]) -> None:
    errors: list[str] = []
    for handle in handles:
        try:
            api.close(handle)
        except OSError as exc:
            errors.append(str(exc))
    if errors:
        raise OSError("stage handle cleanup failed: " + "; ".join(errors))


def _exception_detail(exception: BaseException) -> str:
    details: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exception
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        details.append(f"{type(current).__name__}: {current}")
        current = current.__cause__ or current.__context__
    return "; ".join(reversed(details))


def _entry(path: Path, details: os.stat_result) -> _Entry:
    if (
        getattr(details, "st_file_attributes", 0) & 0x400
        or stat.S_ISLNK(details.st_mode)
        or not (stat.S_ISDIR(details.st_mode) or stat.S_ISREG(details.st_mode))
    ):
        raise OSError(f"stage child is not an independent regular entry: {path.name}")
    if not details.st_ino:
        raise OSError(f"stage child identity is unavailable: {path.name}")
    return _Entry(path, (details.st_dev, details.st_ino), stat.S_ISDIR(details.st_mode))


__all__ = (
    "StageCleanupResult",
    "StageCleanupStatus",
    "StageIdentity",
    "create_owned_stage",
    "remove_owned_record",
    "remove_owned_stage",
)
