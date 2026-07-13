"""Bounded operating-system probes linked to Warcraft game processes."""

from __future__ import annotations

from collections.abc import Iterable
import csv
from dataclasses import dataclass
from itertools import islice
import os
from pathlib import Path
from typing import Final

from .current_map_models import EvidenceKind, GameProcess, MapEvidence
from .current_map_probe_command import (
    COMMAND_OUTPUT_LIMIT,
    COMMAND_TIMEOUT_SECONDS,
    MAX_COMMAND_CHARS,
    MAX_OPEN_PATHS,
    MAX_PROBE_PIDS,
    ProbeIssue as ProbeIssue,
    ProbeParseError,
    is_map_path,
    ordered_evidence,
    parse_command_tokens,
    parse_lsof_open_maps,
    parse_posix_processes,
    parse_windows_processes,
    run_bounded_command,
)


_PS_PATHS: Final = (Path("/bin/ps"), Path("/usr/bin/ps"))
_LSOF_PATHS: Final = (Path("/usr/sbin/lsof"), Path("/usr/bin/lsof"))
_WINDOWS_ROOT = Path(os.environ.get("SystemRoot", r"C:\Windows"))
_POWERSHELL_PATHS: Final = (
    _WINDOWS_ROOT / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe",
)
_POWERSHELL_SCRIPT: Final = (
    "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false);"
    "Get-CimInstance Win32_Process|Select-Object ProcessId,Name,CommandLine|"
    "ConvertTo-Csv -NoTypeInformation"
)
_MAX_FDS_PER_PID: Final = 512
_MAX_ROOTS: Final = 8
_MAX_ARGUMENT_OCCURRENCES: Final = 64
_MAX_EXPLICIT_TOKENS: Final = 256
_LOADFILE_FLAGS: Final = frozenset({"-loadfile", "--loadfile"})


@dataclass(frozen=True, slots=True)
class ProcessProbeReport:
    """Bounded result of discovering Warcraft game processes."""

    processes: tuple[GameProcess, ...]
    available: bool
    issue: ProbeIssue | None = None


@dataclass(frozen=True, slots=True)
class OpenMapProbeReport:
    """Bounded direct-map observations linked to supplied game processes."""

    evidence: tuple[MapEvidence, ...]
    available: bool
    issue: ProbeIssue | None = None


def probe_game_processes() -> ProcessProbeReport:
    """Discover actual Warcraft game processes through a bounded platform tool."""
    if os.name not in {"posix", "nt"}:
        return ProcessProbeReport((), False, ProbeIssue.UNSUPPORTED_PLATFORM)
    if os.name == "posix":
        tool = _find_absolute_tool(_PS_PATHS)
        command = () if tool is None else (str(tool), "-axo", "pid=,args=")
        parser = posix_process_report
    else:
        tool = _find_absolute_tool(_POWERSHELL_PATHS)
        command = () if tool is None else (
            str(tool), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", _POWERSHELL_SCRIPT,
        )
        parser = windows_process_report
    if not command:
        return ProcessProbeReport((), False, ProbeIssue.TOOL_UNAVAILABLE)
    result = run_bounded_command(
        command,
        timeout_seconds=COMMAND_TIMEOUT_SECONDS,
        output_limit=COMMAND_OUTPUT_LIMIT,
    )
    if result.issue is not None:
        return ProcessProbeReport((), False, result.issue)
    return parser(result.stdout)


def probe_open_map_files(processes: Iterable[GameProcess]) -> OpenMapProbeReport:
    """Find map files opened by at most eight supplied game process IDs."""
    selected = tuple(islice((item for item in processes if item.pid > 0), MAX_PROBE_PIDS))
    if not selected:
        return OpenMapProbeReport((), True)
    if os.name != "posix":
        return OpenMapProbeReport((), False, ProbeIssue.UNSUPPORTED_PLATFORM)
    proc_report: OpenMapProbeReport | None = None
    proc_root = Path("/proc")
    if proc_root.is_dir():
        proc_report = probe_proc_open_maps(selected, proc_root)
        if proc_report.available:
            return proc_report
    tool = _find_absolute_tool(_LSOF_PATHS)
    if tool is None:
        return proc_report or OpenMapProbeReport((), False, ProbeIssue.TOOL_UNAVAILABLE)
    command = (str(tool), "-nP", "-a", "-p", ",".join(str(item.pid) for item in selected), "-F0pn")
    result = run_bounded_command(
        command,
        timeout_seconds=COMMAND_TIMEOUT_SECONDS,
        output_limit=COMMAND_OUTPUT_LIMIT,
    )
    if result.issue is not None:
        return OpenMapProbeReport((), False, result.issue)
    try:
        evidence = parse_lsof_open_maps(result.stdout, frozenset(item.pid for item in selected))
    except ProbeParseError:
        return OpenMapProbeReport((), False, ProbeIssue.MALFORMED_OUTPUT)
    return OpenMapProbeReport(evidence, True)


def probe_proc_open_maps(
    processes: tuple[GameProcess, ...],
    proc_root: Path,
) -> OpenMapProbeReport:
    """Inspect bounded Linux proc fd symlinks for supplied process IDs."""
    if not proc_root.is_dir():
        return OpenMapProbeReport((), False, ProbeIssue.TOOL_UNAVAILABLE)
    evidence: list[MapEvidence] = []
    denied = False
    for process in processes[:MAX_PROBE_PIDS]:
        fd_dir = proc_root / str(process.pid) / "fd"
        try:
            entries = os.scandir(fd_dir)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except PermissionError:
            denied = True
            continue
        with entries:
            for entry in islice(entries, _MAX_FDS_PER_PID):
                try:
                    target = os.readlink(entry.path)
                except PermissionError:
                    denied = True
                    continue
                except OSError:
                    continue
                path = Path(target)
                if not path.is_absolute():
                    path = (fd_dir / path).resolve(strict=False)
                if is_map_path(path):
                    evidence.append(MapEvidence(path, EvidenceKind.DIRECT_OPEN, process.pid))
                    if len(evidence) >= MAX_OPEN_PATHS:
                        break
        if len(evidence) >= MAX_OPEN_PATHS:
            break
    if denied:
        return OpenMapProbeReport((), False, ProbeIssue.ACCESS_DENIED)
    return OpenMapProbeReport(ordered_evidence(evidence), True)


def explicit_argument_evidence(
    processes: Iterable[GameProcess],
    roots: Iterable[Path],
) -> tuple[MapEvidence, ...]:
    """Resolve bounded loadfile map arguments against bounded search roots."""
    resolved_roots = tuple(
        root.expanduser().resolve(strict=False) for root in islice(roots, _MAX_ROOTS)
    )
    evidence: set[MapEvidence] = set()
    examined = 0
    for process in islice(processes, MAX_PROBE_PIDS):
        if len(process.command_line) > MAX_COMMAND_CHARS:
            continue
        tokens = parse_command_tokens(process.command_line, limit=_MAX_EXPLICIT_TOKENS)
        for index, token in enumerate(tokens):
            if token.casefold() not in _LOADFILE_FLAGS:
                continue
            if examined >= _MAX_ARGUMENT_OCCURRENCES:
                return ordered_evidence(evidence)
            examined += 1
            if index + 1 >= len(tokens):
                continue
            raw_path = tokens[index + 1]
            argument = Path(raw_path.replace("\\", os.sep))
            candidates = (argument,) if argument.is_absolute() else tuple(
                root / argument for root in resolved_roots
            )
            for candidate in candidates:
                try:
                    is_file = candidate.is_file()
                except OSError:
                    continue
                if is_file and is_map_path(candidate):
                    evidence.add(
                        MapEvidence(
                            candidate.resolve(strict=False),
                            EvidenceKind.EXPLICIT_ARGUMENT,
                            process.pid,
                        )
                    )
                if len(evidence) >= _MAX_ARGUMENT_OCCURRENCES:
                    return ordered_evidence(evidence)
    return ordered_evidence(evidence)


def posix_process_report(payload: bytes) -> ProcessProbeReport:
    try:
        return ProcessProbeReport(parse_posix_processes(payload)[:MAX_PROBE_PIDS], True)
    except (UnicodeDecodeError, ProbeParseError):
        return ProcessProbeReport((), False, ProbeIssue.MALFORMED_OUTPUT)


def windows_process_report(payload: bytes) -> ProcessProbeReport:
    try:
        return ProcessProbeReport(parse_windows_processes(payload)[:MAX_PROBE_PIDS], True)
    except (UnicodeDecodeError, csv.Error, ProbeParseError):
        return ProcessProbeReport((), False, ProbeIssue.MALFORMED_OUTPUT)


def _find_absolute_tool(candidates: tuple[Path, ...]) -> Path | None:
    for candidate in candidates:
        try:
            if candidate.is_absolute() and candidate.is_file():
                return candidate
        except OSError:
            continue
    return None
