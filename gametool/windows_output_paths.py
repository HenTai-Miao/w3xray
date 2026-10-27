"""Extended Windows file-I/O spellings without changing logical path meaning."""

from __future__ import annotations

import ntpath
import os
import ctypes
import sys


def logical_output_path(path: str) -> str:
    """Remove only a drive/UNC extended prefix for logical path comparisons."""
    if os.name != "nt":
        return path
    normalized = path.replace("/", "\\")
    if normalized[:8].upper() == "\\\\?\\UNC\\":
        return "\\\\" + normalized[8:]
    if normalized.startswith("\\\\?\\"):
        remainder = normalized[4:]
        if len(remainder) >= 3 and remainder[1:3] == ":\\":
            return remainder
    return normalized


def native_output_path(path: str) -> str:
    """Use Unicode extended I/O for already-normalized absolute file paths.

    No filesystem/network access occurs here. The caller still proves root
    containment, reparse boundaries and file ownership using logical paths.
    Prefixes disable Win32 normalization, so ambiguous components are rejected
    rather than being allowed to acquire a different filesystem meaning.
    """
    if os.name != "nt":
        return path
    if path.replace("/", "\\").startswith("\\\\?\\") and "/" in path:
        raise ValueError("extended Windows output paths require backslash separators")
    logical = logical_output_path(path)
    try:
        _ = logical.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValueError("Windows output path is not strict UTF-8") from exc
    drive, tail = ntpath.splitdrive(logical)
    if drive.startswith("\\\\") and not drive.startswith(("\\\\?\\", "\\\\.\\")):
        authority = drive[2:].split("\\")
        if len(authority) != 2 or not all(authority):
            raise ValueError("Windows output UNC path requires a server and share")
        for part in authority:
            _require_component(part)
        prefix = "\\\\?\\UNC\\"
        body = logical[2:]
    elif (
        len(drive) == 2
        and drive[0] in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        and drive[1] == ":"
        and tail.startswith("\\")
    ):
        prefix = "\\\\?\\"
        body = logical
    else:
        raise ValueError("Windows output requires an absolute drive or UNC file path")
    if tail and not tail.startswith("\\"):
        raise ValueError("Windows output path is not absolute")
    parts = tail[1:].split("\\") if tail else []
    for index, part in enumerate(parts):
        if not part and index == len(parts) - 1:
            continue
        _require_component(part)
    return prefix + body


def validate_output_root(path: str) -> None:
    """Check raw root components before Win32 abspath can trim their spelling.

    Ordinary relative roots retain Win32's explicit '.' and '..' navigation.
    An already extended root must satisfy the stricter normalized I/O contract.
    """
    if os.name != "nt":
        return
    normalized = path.replace("/", "\\")
    if normalized.startswith("\\\\?\\"):
        _ = native_output_path(path)
        return
    try:
        _ = path.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValueError("Windows output root is not strict UTF-8") from exc
    drive, tail = ntpath.splitdrive(normalized)
    if drive.startswith("\\\\"):
        if drive.startswith("\\\\.\\"):
            raise ValueError("Windows output root cannot use a device namespace")
        authority = drive[2:].split("\\")
        if len(authority) != 2 or not all(authority):
            raise ValueError("Windows output UNC root requires a server and share")
        for part in authority:
            _require_component(part)
    elif drive and not (
        len(drive) == 2
        and drive[0] in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        and drive[1] == ":"
    ):
        raise ValueError("Windows output root has an invalid drive")
    for part in tail.split("\\"):
        if part not in {"", ".", ".."}:
            _require_component(part)


def _require_component(part: str) -> None:
    if not part or part in {".", ".."} or ntpath.isreserved(part):
        raise ValueError(f"unsafe Windows output component: {part!r}")


class _FileIdInfo(ctypes.Structure):
    _fields_ = [
        ("VolumeSerialNumber", ctypes.c_uint64),
        ("FileId", ctypes.c_ubyte * 16),
    ]


class _AttributeTagInfo(ctypes.Structure):
    _fields_ = [("FileAttributes", ctypes.c_uint32), ("ReparseTag", ctypes.c_uint32)]


def remove_owned_output(path: str, expected: tuple[int, int]) -> bool:
    """Delete only the exact opened Windows object, never a rechecked pathname.

    Sharing only READ denies rename, deletion and writing while the held file ID
    is verified and disposition is set. A missing or replaced object is retained
    rather than guessed to be ours. Native access/API errors retain diagnostics.
    """
    if os.name != "nt":
        raise OSError("owned output handle cleanup requires Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.GetFileInformationByHandleEx.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    kernel.GetFileInformationByHandleEx.restype = ctypes.c_int
    kernel.SetFileInformationByHandle.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    kernel.SetFileInformationByHandle.restype = ctypes.c_int
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    handle = kernel.CreateFileW(
        native_output_path(path),
        0x00010080,
        0x1,
        None,
        3,
        0x00200000,
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        error = ctypes.get_last_error()
        if error in {2, 3}:
            return False
        raise OSError(f"CreateFileW (owned cleanup {path}): {ctypes.WinError(error)}")
    try:
        attributes = _AttributeTagInfo()
        if not kernel.GetFileInformationByHandleEx(
            handle, 9, ctypes.byref(attributes), ctypes.sizeof(attributes)
        ):
            raise OSError(
                f"GetFileInformationByHandleEx (attributes {path}): "
                f"{ctypes.WinError(ctypes.get_last_error())}"
            )
        if attributes.FileAttributes & 0x410:
            return False
        identity = _FileIdInfo()
        if not kernel.GetFileInformationByHandleEx(
            handle, 18, ctypes.byref(identity), ctypes.sizeof(identity)
        ):
            raise OSError(
                f"GetFileInformationByHandleEx (identity {path}): "
                f"{ctypes.WinError(ctypes.get_last_error())}"
            )
        actual = (
            identity.VolumeSerialNumber,
            int.from_bytes(bytes(identity.FileId), "little"),
        )
        if actual != expected:
            return False
        _mark_owned_for_deletion(kernel, handle, path)
        return True
    finally:
        primary = sys.exc_info()[1]
        if not kernel.CloseHandle(handle):
            close_error = ctypes.WinError(ctypes.get_last_error())
            raise OSError(
                f"{primary}; CloseHandle (owned cleanup {path}): {close_error}"
                if primary is not None
                else f"CloseHandle (owned cleanup {path}): {close_error}"
            )


def _mark_owned_for_deletion(kernel: ctypes.CDLL, handle: int, path: str) -> None:
    disposition = ctypes.c_ubyte(1)
    if not kernel.SetFileInformationByHandle(
        handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)
    ):
        raise OSError(
            f"SetFileInformationByHandle (owned disposition {path}): "
            f"{ctypes.WinError(ctypes.get_last_error())}"
        )


__all__ = (
    "logical_output_path",
    "native_output_path",
    "validate_output_root",
    "remove_owned_output",
)
