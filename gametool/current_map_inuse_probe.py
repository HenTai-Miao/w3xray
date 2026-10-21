"""Bounded file-in-use observations for the live Warcraft map on Windows."""

from __future__ import annotations

from collections.abc import Iterable
import os
from pathlib import Path
from typing import Final


MAX_PROBED_PATHS: Final = 32
GENERIC_READ: Final = 0x80000000
GENERIC_WRITE: Final = 0x40000000
OPEN_EXISTING: Final = 3
ERROR_SHARING_VIOLATION: Final = 32
_INVALID_HANDLE: Final = 0xFFFFFFFFFFFFFFFF


def probe_in_use_files(paths: Iterable[Path]) -> tuple[Path, ...]:
    """Return the subset of paths another process currently keeps open.

    Each candidate is probed with one exclusive-open attempt; a sharing
    violation proves a live handle without touching any game process.
    """
    if os.name != "nt":
        return ()
    probed: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = os.path.normcase(os.fspath(path))
        if key in seen:
            continue
        seen.add(key)
        if not path.is_file():
            continue
        probed.append(path)
        if len(probed) == MAX_PROBED_PATHS:
            break
    return tuple(path for path in probed if _is_in_use(path))


def _is_in_use(path: Path) -> bool:
    import ctypes
    import ctypes.wintypes as wt

    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.CreateFileW.restype = wt.HANDLE
    kernel32.CreateFileW.argtypes = (
        wt.LPCWSTR,
        wt.DWORD,
        wt.DWORD,
        wt.LPVOID,
        wt.DWORD,
        wt.DWORD,
        wt.HANDLE,
    )
    kernel32.CloseHandle.argtypes = (wt.HANDLE,)
    handle = kernel32.CreateFileW(
        os.fspath(path),
        GENERIC_READ | GENERIC_WRITE,
        0,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle in (None, _INVALID_HANDLE):
        return kernel32.GetLastError() == ERROR_SHARING_VIOLATION
    kernel32.CloseHandle(handle)
    return False
