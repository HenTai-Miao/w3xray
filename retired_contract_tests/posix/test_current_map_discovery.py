"""Bounded disk hints and current-map discovery orchestration."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
import os
from pathlib import Path
import stat
import struct
from types import TracebackType
from typing import Never

import pytest

from gametool import current_map_discovery as discovery
from gametool.current_map_discovery import (
    discover_default_map_roots,
    locate_current_map,
)
from gametool.current_map_models import (
    CurrentMapResolution,
    GameProcess,
)
from gametool.current_map_process import OpenMapProbeReport, ProcessProbeReport

_NOW_NS = 1_800_000_000_000_000_000
_WINDOW_NS = 4 * 60 * 60 * 1_000_000_000
_LOG_WINDOW_NS = 15 * 60 * 1_000_000_000
_NONBLOCK_FLAG = getattr(os, "O_NONBLOCK", 0)
_GAME = GameProcess(73, "Warcraft III", "war3")


@dataclass(frozen=True, slots=True)
class _ProcessProvider:
    report: ProcessProbeReport

    def __call__(self) -> ProcessProbeReport:
        return self.report


@dataclass(frozen=True, slots=True)
class _OpenFileProvider:
    report: OpenMapProbeReport

    def __call__(self, _processes: Iterable[GameProcess], /) -> OpenMapProbeReport:
        return self.report


class _CountingScandir:
    def __init__(
        self,
        entries: Iterator[os.DirEntry[str]],
        close: Callable[[], None],
    ) -> None:
        self._entries: Iterator[os.DirEntry[str]] = entries
        self._close: Callable[[], None] = close
        self.next_calls: int = 0

    def __iter__(self) -> _CountingScandir:
        return self

    def __next__(self) -> os.DirEntry[str]:
        self.next_calls += 1
        return next(self._entries)

    def __enter__(self) -> _CountingScandir:
        return self

    def __exit__(
        self,
        _error_type: type[BaseException] | None,
        _error: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self._close()


def _locate(
    root: Path,
    *,
    processes: tuple[GameProcess, ...] = (_GAME,),
    open_report: OpenMapProbeReport | None = None,
    now_ns: int = _NOW_NS,
    log_home: Path | None = None,
    in_use_provider=None,
) -> CurrentMapResolution:
    report = OpenMapProbeReport((), True) if open_report is None else open_report
    isolated_home = root / ".isolated-home" if log_home is None else log_home
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "home", staticmethod(lambda: isolated_home))
        # Keep orchestration tests hermetic: the host machine's real classic
        # install directories must not leak map files into isolated roots.
        patch.setattr(discovery, "_windows_classic_map_roots", lambda: ())
        return locate_current_map(
            (root,),
            now_ns,
            process_provider=_ProcessProvider(ProcessProbeReport(processes, True)),
            open_file_provider=_OpenFileProvider(report),
            in_use_provider=in_use_provider,
        )


def _write_at(path: Path, payload: bytes, mtime_ns: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_bytes(payload)
    os.utime(path, ns=(mtime_ns, mtime_ns))


def _wgc(map_path: str) -> bytes:
    return (
        struct.pack("<iii", 1, 0, 1) + map_path.encode() + b"\0" + struct.pack("<i", 0)
    )


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX /Volumes semantics")
def test_known_roots_include_fixed_user_volume_pattern_without_volume_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a macOS home whose username also names the mounted game volume.
    home = Path("/Users/zhongerbing")
    volume_root = Path("/Volumes") / home.name / "Program Files (x86)" / "Warcraft III"
    volume_root /= "Warcraft III Frozen Throne/Maps"

    def fake_home() -> Path:
        return home

    def fake_lstat(path: Path) -> os.stat_result:
        if path == volume_root:
            return os.stat_result((stat.S_IFDIR, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        raise FileNotFoundError(path)

    def unexpected_scan(_path: str | Path) -> Never:
        raise AssertionError("known roots must not recursively scan /Volumes")

    monkeypatch.setattr(Path, "home", staticmethod(fake_home))
    monkeypatch.setattr(Path, "lstat", fake_lstat)
    monkeypatch.setattr(os, "scandir", unexpected_scan)

    # When: public root discovery checks its fixed candidates.
    roots = discover_default_map_roots()

    # Then: the user's legacy Warcraft Maps location is an exact candidate.
    assert roots == (volume_root,)


@pytest.mark.skipif(_NONBLOCK_FLAG == 0, reason="requires nonblocking POSIX file open")
def test_wgc_open_is_nonblocking_against_fifo_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: a recent config whose open boundary could race with entry metadata.
    root = tmp_path / "fifo-race"
    target = root / "target.w3x"
    _write_at(target, b"old", _NOW_NS - _WINDOW_NS - 1)
    _write_at(root / "current.wgc", _wgc("target.w3x"), _NOW_NS)
    real_open = os.open

    def guarded_open(path: Path, flags: int) -> int:
        assert flags & _NONBLOCK_FLAG
        return real_open(path, flags)

    monkeypatch.setattr(os, "open", guarded_open)

    # When: the recent config is opened through discovery.
    resolution = _locate(root)

    # Then: the nonblocking capability preserves normal regular-file resolution.
    assert tuple(item.path for item in resolution.candidates) == (target.resolve(),)
