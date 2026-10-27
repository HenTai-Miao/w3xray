"""Complete file-in-use observations for the live Warcraft map on Windows."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from functools import cache
import os
from pathlib import Path
from typing import Final


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
    hits: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = os.path.normcase(os.fspath(path))
        if key in seen:
            continue
        seen.add(key)
        if not path.is_file():
            continue
        if _is_in_use(path):
            hits.append(path)
    return tuple(hits)


def _is_in_use(path: Path) -> bool:
    return _windows_probe()(path)


@cache
def _windows_probe() -> Callable[[Path], bool]:
    """Configure system API calls once; every path is still probed afresh."""
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

    def probe(path: Path) -> bool:
        handle = kernel32.CreateFileW(
            os.fspath(path),
            GENERIC_READ,
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

    return probe
