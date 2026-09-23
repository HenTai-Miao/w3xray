"""Windows in-use file probing for the live current map."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
from pathlib import Path

import pytest

from w3xtool.current_map_inuse_probe import probe_in_use_files

_GENERIC_READ = 0x80000000
_OPEN_EXISTING = 3


@pytest.mark.skipif(os.name != "nt", reason="exclusive-open probing is Windows-only")
def test_in_use_probe_reports_only_held_files(tmp_path: Path) -> None:
    # Given: one file this process keeps open without sharing and one idle file.
    held = tmp_path / "held.w3x"
    idle = tmp_path / "idle.w3x"
    missing = tmp_path / "missing.w3x"
    _ = held.write_bytes(b"m")
    _ = idle.write_bytes(b"m")
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
        os.fspath(held), _GENERIC_READ, 0, None, _OPEN_EXISTING, 0, None
    )
    assert handle not in (None, wt.HANDLE(-1).value)

    # When: the bounded probe classifies held, idle, and missing candidates.
    try:
        in_use = probe_in_use_files([held, idle, missing])
    finally:
        _ = kernel32.CloseHandle(handle)

    # Then: only the held file is reported, and it is released afterwards.
    assert in_use == (held,)
    assert probe_in_use_files([held]) == ()
