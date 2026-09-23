"""Bounded disk hints and current-map discovery orchestration."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
import inspect
import os
from pathlib import Path
import stat
import struct
import time
from types import TracebackType
from typing import Never

import pytest

from w3xtool import current_map_discovery as discovery
from w3xtool.current_map_discovery import (
    discover_default_map_roots,
    locate_current_map,
)
from w3xtool.current_map_models import CurrentMapResolution, EvidenceKind, GameProcess, MapEvidence, ResolutionStatus
from w3xtool.current_map_process import OpenMapProbeReport, ProcessProbeReport

_NOW_NS = 1_800_000_000_000_000_000
_WINDOW_NS = 15 * 60 * 1_000_000_000
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

    def __exit__(self, _error_type: type[BaseException] | None, _error: BaseException | None, _traceback: TracebackType | None) -> None:
        self._close()


def _locate(
    root: Path,
    *,
    processes: tuple[GameProcess, ...] = (_GAME,),
    open_report: OpenMapProbeReport | None = None,
    now_ns: int = _NOW_NS,
    log_home: Path | None = None,
) -> CurrentMapResolution:
    report = OpenMapProbeReport((), True) if open_report is None else open_report
    isolated_home = root / ".isolated-home" if log_home is None else log_home
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "home", staticmethod(lambda: isolated_home))
        return locate_current_map(
            (root,),
            now_ns,
            process_provider=_ProcessProvider(ProcessProbeReport(processes, True)),
            open_file_provider=_OpenFileProvider(report),
        )


def _write_at(path: Path, payload: bytes, mtime_ns: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_bytes(payload)
    os.utime(path, ns=(mtime_ns, mtime_ns))


def _wgc(map_path: str) -> bytes:
    return struct.pack("<iii", 1, 0, 1) + map_path.encode() + b"\0" + struct.pack("<i", 0)


def test_default_roots_dedupe_existing_directories_before_eight_root_cap(tmp_path: Path) -> None:
    # Given: duplicates, a missing path, and ten existing user roots.
    roots = tuple(tmp_path / f"root-{index}" for index in range(10))
    for root in roots:
        root.mkdir()
    extras = (roots[0], roots[0] / ".", tmp_path / "missing", *roots[1:])

    # When: roots are normalized for bounded discovery.
    discovered = discover_default_map_roots(extras)

    # Then: only the first eight unique existing directories remain.
    assert discovered == tuple(root.resolve() for root in roots[:8])


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX /Volumes semantics")
def test_known_roots_include_fixed_user_volume_pattern_without_volume_scan(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_hint_scan_stops_after_five_nested_directories(tmp_path: Path) -> None:
    # Given: recent maps at the fifth and sixth nested directory levels.
    root = tmp_path / "maps"
    directory = root
    for index in range(5):
        directory /= f"level-{index}"
    inside = directory / "inside.w3x"
    beyond = directory / "level-5" / "beyond.w3x"
    _write_at(inside, b"inside", _NOW_NS)
    _write_at(beyond, b"beyond", _NOW_NS)

    # When: hint discovery traverses the bounded root.
    resolution = _locate(root)

    # Then: depth five is visible and depth six is never scanned.
    assert tuple(item.path for item in resolution.candidates) == (inside.resolve(),)


def test_hint_scan_stops_at_five_thousand_directory_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: one root containing 5,001 recent regular map entries.
    root = tmp_path / "many"
    root.mkdir()
    for index in range(5_001):
        (root / f"map-{index:04}.w3x").touch()
    now_ns = time.time_ns()
    real_scandir = os.scandir
    scans: list[_CountingScandir] = []

    def counting_scandir(path: Path) -> _CountingScandir:
        entries = real_scandir(path)
        scan = _CountingScandir(entries, entries.close)
        scans.append(scan)
        return scan

    monkeypatch.setattr(os, "scandir", counting_scandir)

    # When: discovery scans with its global directory-entry budget.
    resolution = _locate(root, now_ns=now_ns)

    # Then: the underlying iterator itself is never advanced past the budget.
    assert resolution.status is ResolutionStatus.SUGGESTED
    assert len(resolution.candidates) == 5_000
    assert len(scans) == 1
    assert scans[0].next_calls == 5_000


def test_hint_scan_accepts_only_regular_map_files(tmp_path: Path) -> None:
    # Given: a recent real map beside a map-suffixed directory and non-map file.
    root = tmp_path / "regular"
    root.mkdir()
    real_map = root / "real.W3X"
    _write_at(real_map, b"map", _NOW_NS)
    (root / "directory.w3m").mkdir()
    _write_at(root / "notes.txt", b"not a map", _NOW_NS)

    # When: recent cache hints are collected.
    resolution = _locate(root)

    # Then: only the regular map file is suggested.
    assert tuple(item.path for item in resolution.candidates) == (real_map.resolve(),)


def test_hint_scan_does_not_follow_map_symlinks(tmp_path: Path) -> None:
    # Given: a recent map is reachable only through a map-suffixed symlink.
    root = tmp_path / "links"
    root.mkdir()
    target = tmp_path / "outside.w3x"
    _write_at(target, b"outside", _NOW_NS)
    try:
        (root / "linked.w3x").symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    # When: discovery scans the configured root.
    resolution = _locate(root)

    # Then: no symlink target becomes hint evidence.
    assert resolution.status is ResolutionStatus.NOT_FOUND


def test_open_probe_nonregular_map_evidence_is_rejected(tmp_path: Path) -> None:
    # Given: an injected direct probe names a directory with a map suffix.
    root = tmp_path / "direct-regularity"
    root.mkdir()
    fake_map = root / "directory.w3x"
    fake_map.mkdir()
    open_report = OpenMapProbeReport(
        (MapEvidence(fake_map, EvidenceKind.DIRECT_OPEN, _GAME.pid),),
        True,
    )

    # When: orchestration validates evidence before pure resolution.
    resolution = _locate(root, open_report=open_report)

    # Then: non-regular direct observations cannot authorize automatic selection.
    assert resolution.status is ResolutionStatus.NOT_FOUND


def test_recent_hint_window_includes_boundary_but_rejects_stale_and_future(tmp_path: Path) -> None:
    # Given: maps exactly at, just before, and just after the allowed time window.
    root = tmp_path / "window"
    boundary = root / "boundary.w3m"
    _write_at(boundary, b"boundary", _NOW_NS - _WINDOW_NS)
    _write_at(root / "stale.w3x", b"stale", _NOW_NS - _WINDOW_NS - 1_000_000)
    _write_at(root / "future.w3n", b"future", _NOW_NS + 1_000_000)

    # When: the injected clock anchors hint discovery.
    resolution = _locate(root)

    # Then: only an age in the closed fifteen-minute interval is useful.
    normalized_boundary = Path(os.path.normcase(os.fspath(boundary.resolve())))
    assert tuple(item.path for item in resolution.candidates) == (normalized_boundary,)


def test_recent_hints_are_not_useful_without_a_game_process(tmp_path: Path) -> None:
    # Given: a recent map exists but process discovery finds no running game.
    root = tmp_path / "idle"
    _write_at(root / "recent.w3x", b"recent", _NOW_NS)

    # When: orchestration delegates the observations to the pure resolver.
    resolution = _locate(root, processes=())

    # Then: unrelated disk recency cannot create a suggestion.
    assert resolution == CurrentMapResolution(ResolutionStatus.NOT_FOUND, ())


def test_unavailable_process_probe_returns_unavailable(tmp_path: Path) -> None:
    # Given: the process provider cannot inspect whether Warcraft is running.
    root = tmp_path / "unavailable-processes"
    root.mkdir()
    provider = _ProcessProvider(ProcessProbeReport((), False))

    # When: current-map orchestration receives the unavailable report.
    resolution = locate_current_map((root,), _NOW_NS, process_provider=provider)

    # Then: probe failure remains distinct from a successful empty process list.
    assert resolution == CurrentMapResolution(ResolutionStatus.UNAVAILABLE, ())


def test_recent_wgc_resolves_windows_paths_from_config_root_and_warcraft_ancestor(tmp_path: Path) -> None:
    # Given: three recent configs reference old maps through each allowed base.
    warcraft = tmp_path / "Warcraft III"
    root = warcraft / "Cache"
    config_map = root / "configs" / "local.w3m"
    root_map = root / "root.w3x"
    ancestor_map = warcraft / "Maps" / "Anime" / "ancestor.w3n"
    for map_path in (config_map, root_map, ancestor_map):
        _write_at(map_path, b"old map", _NOW_NS - _WINDOW_NS - 1)
    _write_at(root / "configs" / "local.wgc", _wgc("local.w3m"), _NOW_NS)
    _write_at(root / "root.wgc", _wgc("root.w3x"), _NOW_NS)
    _write_at(root / "ancestor.wgc", _wgc("Maps\\Anime\\ancestor.w3n"), _NOW_NS)

    # When: bounded .wgc files are parsed as hint evidence.
    resolution = _locate(root)

    # Then: all existing regular references are suggestions, never direct matches.
    assert resolution.status is ResolutionStatus.SUGGESTED
    assert {item.path for item in resolution.candidates} == {
        config_map.resolve(),
        root_map.resolve(),
        ancestor_map.resolve(),
    }
    assert all(item.evidence[0].kind is EvidenceKind.WGC_REFERENCE for item in resolution.candidates)


def test_wgc_ancestor_iteration_is_lazy_and_bounded() -> None:
    # Given: the discovery module source implementing Warcraft ancestor lookup.
    source = inspect.getsource(discovery)

    # When/Then: islice receives a lazy root-plus-parents chain, never a star tuple.
    assert "islice(chain((root,), root.parents), _MAX_ANCESTORS_PER_ROOT)" in source


def test_stale_wgc_reference_does_not_participate(tmp_path: Path) -> None:
    # Given: an old config references an existing old map.
    root = tmp_path / "stale-config"
    map_path = root / "old.w3x"
    _write_at(map_path, b"old", _NOW_NS - _WINDOW_NS - 1)
    _write_at(root / "old.wgc", _wgc("old.w3x"), _NOW_NS - _WINDOW_NS - 1)

    # When: hint discovery evaluates its injected time window.
    resolution = _locate(root)

    # Then: the stale config cannot suggest its referenced map.
    assert resolution.status is ResolutionStatus.NOT_FOUND


def test_oversized_wgc_is_not_passed_to_the_parser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: a recent .wgc exceeds the bounded one-megabyte read limit.
    root = tmp_path / "oversized"
    _write_at(root / "large.wgc", b"x" * (1_048_576 + 1), _NOW_NS)

    def unexpected_parse(_payload: bytes) -> Never:
        raise AssertionError("oversized .wgc must not be parsed")

    monkeypatch.setattr(discovery, "parse_game_configuration", unexpected_parse)

    # When: discovery inspects the configuration metadata.
    resolution = _locate(root)

    # Then: the bounded file is ignored without invoking the parser.
    assert resolution.status is ResolutionStatus.NOT_FOUND


@pytest.mark.skipif(_NONBLOCK_FLAG == 0, reason="requires nonblocking POSIX file open")
def test_wgc_open_is_nonblocking_against_fifo_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_direct_process_evidence_always_outranks_recent_hints(tmp_path: Path) -> None:
    # Given: one direct open map and a different recent disk hint.
    root = tmp_path / "precedence"
    _write_at(root / "recent.w3x", b"hint", _NOW_NS)
    direct = tmp_path / "current.w3m"
    _write_at(direct, b"direct", _NOW_NS - _WINDOW_NS - 1)
    open_report = OpenMapProbeReport(
        (MapEvidence(direct, EvidenceKind.DIRECT_OPEN, _GAME.pid),),
        True,
    )

    # When: injected providers and the disk scanner feed the pure resolver.
    resolution = _locate(root, open_report=open_report)

    # Then: the unique process-linked map is the only returned candidate.
    assert resolution.status is ResolutionStatus.FOUND
    assert tuple(item.path for item in resolution.candidates) == (direct.resolve(),)


def test_log_hint_supplies_last_opening_map_as_suggestion(tmp_path: Path) -> None:
    # Given: the game log's latest opening line names an existing absolute map.
    home = tmp_path / "home"
    log = home.joinpath(*discovery._LOG_RELPATH)
    log.parent.mkdir(parents=True)
    map_file = tmp_path / "elsewhere" / "logmap.w3x"
    _write_at(map_file, b"map", _NOW_NS - _WINDOW_NS - 1)
    log_reference = os.fspath(map_file).replace("\\", "/")
    _ = log.write_bytes(
        (
            "9/16 21:18:38.751  Opening map - C:/gone/older.w3x\n"
            f"9/16 21:18:48.259  Opening map - {log_reference}\n"
            f"9/16 21:18:48.259  Opening mod - {log_reference}\n"
        ).encode()
    )

    # When: discovery runs with a live game and no platform open-file probe.
    resolution = _locate(
        tmp_path / "empty",
        open_report=OpenMapProbeReport((), False),
        log_home=home,
    )

    # Then: the latest log entry becomes the single suggested candidate.
    assert resolution.status is ResolutionStatus.SUGGESTED
    assert len(resolution.candidates) == 1
    assert resolution.candidates[0].evidence[0].kind is EvidenceKind.GAME_LOG


def test_log_hint_outlives_recent_hints_in_full_discovery(tmp_path: Path) -> None:
    # Given: a fresh recent map under the root and a log naming a different map.
    home = tmp_path / "home"
    log = home.joinpath(*discovery._LOG_RELPATH)
    log.parent.mkdir(parents=True)
    recent = tmp_path / "empty" / "recent.w3x"
    _write_at(recent, b"hint", _NOW_NS)
    logged_map = tmp_path / "elsewhere" / "logmap.w3x"
    _write_at(logged_map, b"map", _NOW_NS - _WINDOW_NS - 1)
    _ = log.write_bytes(
        ("Opening map - " + os.fspath(logged_map).replace("\\", "/") + "\n").encode()
    )

    # When: full discovery runs with a live game and no open-file probe.
    resolution = _locate(
        tmp_path / "empty",
        open_report=OpenMapProbeReport((), False),
        log_home=home,
    )

    # Then: only the log-backed map is suggested for confirmation.
    assert resolution.status is ResolutionStatus.SUGGESTED
    assert tuple(item.path for item in resolution.candidates) == (
        Path(os.path.normcase(logged_map.resolve(strict=False))),
    )


def test_log_hint_without_a_game_process_stays_not_found(tmp_path: Path) -> None:
    # Given: a log naming an existing map but no detected game process.
    home = tmp_path / "home"
    log = home.joinpath(*discovery._LOG_RELPATH)
    log.parent.mkdir(parents=True)
    map_file = tmp_path / "elsewhere" / "logmap.w3x"
    _write_at(map_file, b"map", _NOW_NS - _WINDOW_NS - 1)
    _ = log.write_bytes(
        ("Opening map - " + os.fspath(map_file).replace("\\", "/") + "\n").encode()
    )

    # When: discovery runs without any game process.
    resolution = _locate(
        tmp_path / "empty",
        processes=(),
        open_report=OpenMapProbeReport((), False),
        log_home=home,
    )

    # Then: the stale log cannot propose a map on its own.
    assert resolution.status is ResolutionStatus.NOT_FOUND


def test_log_hint_reads_only_the_bounded_tail(tmp_path: Path) -> None:
    # Given: an oversized log whose valid opening line sits inside the tail.
    home = tmp_path
    map_file = tmp_path / "tail.w3n"
    _write_at(map_file, b"map", _NOW_NS - _WINDOW_NS - 1)
    filler = "x" * 4096 + "\n"
    payload = filler * 300 + "Opening map - " + os.fspath(map_file).replace("\\", "/") + "\n"
    assert len(payload.encode()) > 1_048_576 // 2
    log = home.joinpath(*discovery._LOG_RELPATH)
    log.parent.mkdir(parents=True, exist_ok=True)
    _ = log.write_bytes(payload.encode())

    # When: the bounded log reader supplies hint evidence.
    evidence = discovery._log_hint_evidence(home, ())

    # Then: the tail entry still resolves and the read stays under the cap.
    assert evidence == (MapEvidence(map_file, EvidenceKind.GAME_LOG),)


def test_log_hint_skips_unresolvable_and_non_map_entries(tmp_path: Path) -> None:
    # Given: log lines naming a missing campaign path and a non-map file.
    home = tmp_path
    log = home.joinpath(*discovery._LOG_RELPATH)
    log.parent.mkdir(parents=True, exist_ok=True)
    _ = log.write_bytes(
        b"9/16 21:18:48.259  Opening map - Campaign/Classic/ROC/Prologue01.w3m\n"
        b"9/16 21:18:48.385  Opening map - notes.txt\n"
        b"garbage line without an opening\n"
    )

    # When: the bounded log reader classifies every line.
    evidence = discovery._log_hint_evidence(home, (tmp_path / "Maps",))

    # Then: nothing unresolvable becomes map evidence.
    assert evidence == ()


def test_log_hint_resolves_relative_paths_against_roots(tmp_path: Path) -> None:
    # Given: a relative log entry that exists below one scanned root.
    home = tmp_path / "home"
    root = tmp_path / "library"
    map_file = root / "Maps" / "Anime" / "relative.w3x"
    _write_at(map_file, b"map", _NOW_NS - _WINDOW_NS - 1)
    log = home.joinpath(*discovery._LOG_RELPATH)
    log.parent.mkdir(parents=True)
    _ = log.write_bytes(b"Opening map - Maps\\Anime\\relative.w3x\n")

    # When: the bounded log reader resolves the entry against the roots.
    evidence = discovery._log_hint_evidence(home, (root,))

    # Then: the existing relative map becomes exactly one hint observation.
    assert evidence == (MapEvidence(map_file, EvidenceKind.GAME_LOG),)
