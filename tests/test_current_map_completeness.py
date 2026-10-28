"""Regression coverage for complete current-map inputs and late evidence."""

from __future__ import annotations

import csv
import importlib
from collections.abc import Iterator
from itertools import chain, repeat
import os
from pathlib import Path
import sys
import time
from typing import Self

import pytest

from gametool import current_map_discovery as discovery
from gametool import current_map_inuse_probe as inuse
from gametool import current_map_probe_command as probe_command
from gametool.current_map_models import EvidenceKind, GameProcess, MapEvidence
from gametool.current_map_probe_command import (
    parse_windows_processes,
    run_bounded_command,
)
from gametool.current_map_process import (
    explicit_argument_evidence,
    probe_proc_open_maps,
)


def test_overlapping_roots_are_scanned_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    target = nested / "map.w3x"
    target.touch()
    visited: list[Path] = []
    real_scandir = os.scandir

    def scan(path: Path):
        visited.append(path)
        return real_scandir(path)

    monkeypatch.setattr(discovery.os, "scandir", scan)
    result = discovery._scan_hint_evidence(
        (tmp_path, nested), target.stat().st_mtime_ns
    )
    assert [path for path, _ in result.map_files] == [target]
    assert sum(path.samefile(nested) for path in visited) == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows directory junction")
def test_discovery_does_not_follow_directory_junction(tmp_path: Path) -> None:
    root = tmp_path / "maps"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "hidden.w3x"
    target.touch()
    winapi = importlib.import_module("_winapi")
    winapi.CreateJunction(str(outside), str(root / "junction"))
    assert discovery._scan_hint_evidence((root,), time.time_ns()).map_files == ()


def test_in_use_evidence_includes_map_after_fifty_thousand_candidates(
    tmp_path: Path,
) -> None:
    paths = tuple(
        (tmp_path / f"map-{index:05}.w3x", 50_001 - index) for index in range(50_001)
    )
    seen: list[Path] = []

    def probe(batch):
        seen.extend(batch)
        return tuple(path for path in batch if path == paths[-1][0])

    evidence = discovery._in_use_evidence([], paths, probe)
    assert len(seen) == len(set(seen)) == 50_001
    assert evidence == (MapEvidence(paths[-1][0], EvidenceKind.LIVE_FILE),)


def test_wgc_bases_include_warcraft_ancestor_beyond_sixty_four_levels(
    tmp_path: Path,
) -> None:
    warcraft = tmp_path / "Warcraft III"
    root = warcraft.joinpath(*("d" for _ in range(80)))
    assert warcraft in discovery._wgc_bases(root / "current.wgc", (root,))


def test_many_wgc_files_are_all_examined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "last.wgc"
    config.touch()
    with os.scandir(tmp_path) as entries:
        entry = next(entries)
    calls: list[Path] = []

    class Entries:
        def __iter__(self) -> Iterator[os.DirEntry[str]]:
            return iter(repeat(entry, 2050))

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

    monkeypatch.setattr(discovery.os, "scandir", lambda _path: Entries())
    monkeypatch.setattr(
        discovery,
        "_wgc_reference_evidence",
        lambda path, _roots, _now: calls.append(path) or (),
    )
    discovery._scan_hint_evidence((tmp_path,), 0)
    assert calls == [config] * 2050


def test_explicit_map_argument_after_long_command_and_late_process(
    tmp_path: Path,
) -> None:
    target = tmp_path / "tail.w3x"
    target.touch()
    processes = tuple(
        GameProcess(index + 1, "war3", "war3 --ignored") for index in range(129)
    )
    command = "war3 " + "--ignored " * 5000 + f'-loadfile "{target}"'
    selected = GameProcess(200, "war3", command)
    assert explicit_argument_evidence((*processes, selected), ()) == (
        MapEvidence(target.resolve(), EvidenceKind.EXPLICIT_ARGUMENT, 200),
    )


def test_windows_csv_retains_large_command_and_restores_field_settings() -> None:
    command = "war3 " + "x" * 200_000
    payload = (
        '"ProcessId","Name","CommandLine"\r\n"900","war3.exe","' + command + '"\r\n'
    ).encode()
    previous = csv.field_size_limit()
    assert parse_windows_processes(payload) == (GameProcess(900, "war3.exe", command),)
    assert csv.field_size_limit() == previous


def test_command_collects_full_output_above_former_sixteen_mib_limit() -> None:
    size = 16 * 1024 * 1024 + 17
    command = (
        sys.executable,
        "-c",
        f"import sys; sys.stdout.buffer.write(b'x' * {size})",
    )
    result = run_bounded_command(command)
    assert result.issue is None
    assert result.stdout == b"x" * size


def test_log_opening_line_before_former_tail_window_is_found(tmp_path: Path) -> None:
    target = tmp_path / "map.w3x"
    target.touch()
    log = tmp_path.joinpath(*discovery._LOG_RELPATH)
    log.parent.mkdir(parents=True)
    with log.open("wb") as stream:
        stream.write((f"Opening map - {target.as_posix()}\n").encode())
        for _ in range(1025):
            stream.write(b"x" * 65536 + b"\n")
    assert discovery._log_hint_evidence(tmp_path, (), time.time_ns()) == (
        MapEvidence(target, EvidenceKind.GAME_LOG),
    )


def test_unresolved_newer_log_map_does_not_revive_previous_session(
    tmp_path: Path,
) -> None:
    target = tmp_path / "previous.w3x"
    target.touch()
    log = tmp_path.joinpath(*discovery._LOG_RELPATH)
    log.parent.mkdir(parents=True)
    log.write_text(
        f"Opening map - {target.as_posix()}\nOpening map - missing.w3x\n",
        encoding="utf-8",
    )
    assert discovery._log_hint_evidence(tmp_path, (), time.time_ns()) == ()


def test_relative_log_map_retains_candidates_from_every_root(tmp_path: Path) -> None:
    roots = (tmp_path / "first", tmp_path / "second")
    for root in roots:
        root.mkdir()
        (root / "duplicate.w3x").touch()
    log = tmp_path.joinpath(*discovery._LOG_RELPATH)
    log.parent.mkdir(parents=True)
    log.write_text("Opening map - duplicate.w3x\n", encoding="utf-8")
    assert {
        item.path
        for item in discovery._log_hint_evidence(tmp_path, roots, time.time_ns())
    } == {root / "duplicate.w3x" for root in roots}


def test_explicit_output_budget_reports_before_producer_exits() -> None:
    command = (
        sys.executable,
        "-c",
        "import sys,time; sys.stdout.buffer.write(b'x'*1000000); sys.stdout.flush(); time.sleep(10)",
    )
    result = run_bounded_command(command, output_limit=64, timeout_seconds=2.0)
    assert result.issue is not None and result.issue.value == "output_limit"
    assert result.stdout == b""


def test_probe_reader_allocation_failure_returns_a_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def exhausted(_descriptor: int, _size: int) -> bytes:
        raise MemoryError("fixture allocation failure")

    monkeypatch.setattr(os, "read", exhausted)
    result = probe_command._read_command_stdout(123, None)
    assert result.issue is probe_command.ProbeIssue.RESOURCE_EXHAUSTED
    assert result.stdout == b""


def test_proc_probe_covers_late_process_and_all_file_descriptors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    processes = tuple(GameProcess(index + 1, "war3", "war3") for index in range(130))
    proc_root = tmp_path / "proc"
    directory = proc_root / "130" / "fd"
    directory.mkdir(parents=True)
    (directory / "early").touch()
    (directory / "late").touch()
    with os.scandir(directory) as entries:
        by_name = {entry.name: entry for entry in entries}

    class Entries:
        def __iter__(self) -> Iterator[os.DirEntry[str]]:
            return iter(chain(repeat(by_name["early"], 9000), (by_name["late"],)))

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

    def scan(path: Path):
        if path != directory:
            raise FileNotFoundError(path)
        return Entries()

    target = tmp_path / "last.w3x"
    monkeypatch.setattr(os, "scandir", scan)
    monkeypatch.setattr(
        os,
        "readlink",
        lambda path: str(
            target if Path(path).name == "late" else tmp_path / "notes.txt"
        ),
    )
    report = probe_proc_open_maps(processes, proc_root)
    assert report.available
    assert report.evidence == (MapEvidence(target, EvidenceKind.DIRECT_OPEN, 130),)


@pytest.mark.skipif(os.name != "nt", reason="Windows file sharing adapter")
def test_in_use_probe_covers_all_paths_without_per_call_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = tuple(tmp_path / f"map-{index}.w3x" for index in range(600))
    for path in paths:
        path.touch()
    visited: list[Path] = []

    def is_in_use(path: Path) -> bool:
        visited.append(path)
        return path == paths[-1]

    monkeypatch.setattr(inuse, "_is_in_use", is_in_use)
    assert inuse.probe_in_use_files((*paths, paths[-1])) == (paths[-1],)
    assert visited == list(paths)
