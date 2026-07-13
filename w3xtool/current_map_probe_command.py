"""Bounded subprocess execution and output parsers for current-map probes."""

from __future__ import annotations

from collections.abc import Iterable
import csv
from dataclasses import dataclass
from enum import StrEnum, unique
import io
import os
from pathlib import Path
from queue import Empty, Queue
import re
import subprocess
from threading import Thread
from typing import Final, override

from .current_map_models import EvidenceKind, GameProcess, MapEvidence


COMMAND_TIMEOUT_SECONDS: Final = 2.0
COMMAND_OUTPUT_LIMIT: Final = 1024 * 1024
MAX_PROBE_PIDS: Final = 8
MAX_PROCESS_RECORDS: Final = 128
MAX_OPEN_PATHS: Final = 256
MAX_PATH_CHARS: Final = 4096
MAX_COMMAND_CHARS: Final = 32768
MAP_SUFFIXES: Final = frozenset({".w3x", ".w3m", ".w3n"})
_WINDOWS_CREATE_NO_WINDOW: Final = 0x08000000
_WINE_EXECUTABLES: Final = frozenset({"wine", "wine64", "wine-preloader", "wine64-preloader"})
_MAC_GAME_COMMAND = re.compile(
    r'^"?/[^"\r\n]*\.app/Contents/MacOS/(?:Warcraft III|war3)(?:\.exe)?"?(?=$|\s+-)',
    re.IGNORECASE,
)
_COMMAND_TOKEN_PATTERN = re.compile(r'"([^"\r\n]*)"|\'([^\'\r\n]*)\'|([^\s"\']+)')


@unique
class ProbeIssue(StrEnum):
    """Stable, non-sensitive reason why an operating-system probe failed."""

    TOOL_UNAVAILABLE = "tool_unavailable"
    TIMEOUT = "timeout"
    OUTPUT_LIMIT = "output_limit"
    COMMAND_FAILED = "command_failed"
    MALFORMED_OUTPUT = "malformed_output"
    ACCESS_DENIED = "access_denied"
    UNSUPPORTED_PLATFORM = "unsupported_platform"


@dataclass(frozen=True, slots=True)
class CommandResult:
    stdout: bytes
    issue: ProbeIssue | None
    returncode: int | None = None


@dataclass(frozen=True, slots=True)
class ProbeParseError(ValueError):
    source: str

    @override
    def __str__(self) -> str:
        return f"malformed {self.source} output"


def run_bounded_command(
    command: tuple[str, ...],
    *,
    timeout_seconds: float,
    output_limit: int,
) -> CommandResult:
    """Run one absolute executable without a shell and retain bounded output."""
    if not command or not Path(command[0]).is_absolute():
        return CommandResult(b"", ProbeIssue.TOOL_UNAVAILABLE)
    try:
        process: subprocess.Popen[bytes] = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            shell=False,
            close_fds=True,
            creationflags=popen_creation_flags(os.name),
        )
    except OSError:
        return CommandResult(b"", ProbeIssue.TOOL_UNAVAILABLE)
    captured: Queue[bytes] = Queue(maxsize=1)

    def read_stdout() -> None:
        stream = process.stdout
        if stream is None:
            captured.put(b"")
            return
        try:
            payload = bytearray()
            while len(payload) <= output_limit:
                chunk = os.read(
                    stream.fileno(),
                    min(65536, output_limit + 1 - len(payload)),
                )
                if not chunk:
                    break
                payload.extend(chunk)
            captured.put(bytes(payload))
        except OSError:
            captured.put(b"")
        finally:
            stream.close()

    reader = Thread(target=read_stdout, daemon=True)
    reader.start()
    try:
        returncode = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            _ = process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            reader.join(timeout=1.0)
            return CommandResult(b"", ProbeIssue.TIMEOUT)
        reader.join(timeout=1.0)
        return CommandResult(b"", ProbeIssue.TIMEOUT)
    reader.join(timeout=1.0)
    try:
        payload = captured.get_nowait()
    except Empty:
        return CommandResult(b"", ProbeIssue.COMMAND_FAILED, returncode)
    if len(payload) > output_limit:
        return CommandResult(b"", ProbeIssue.OUTPUT_LIMIT, returncode)
    if returncode != 0:
        return CommandResult(b"", ProbeIssue.COMMAND_FAILED, returncode)
    return CommandResult(payload, None, returncode)


def popen_creation_flags(platform_name: str) -> int:
    return _WINDOWS_CREATE_NO_WINDOW if platform_name == "nt" else 0


def parse_posix_processes(payload: bytes) -> tuple[GameProcess, ...]:
    """Parse ``ps`` PID/command records and retain game executables only."""
    processes: list[GameProcess] = []
    saw_record = False
    for raw_line in payload.decode("utf-8").splitlines():
        fields = raw_line.strip().split(maxsplit=1)
        if not fields:
            continue
        pid = _parse_pid(fields[0], "ps")
        saw_record = True
        if len(fields) == 1 or len(fields[1]) > MAX_COMMAND_CHARS:
            continue
        command_line = fields[1]
        if _is_posix_game_process(command_line):
            processes.append(GameProcess(pid, "Warcraft III", command_line))
            if len(processes) >= MAX_PROCESS_RECORDS:
                break
    if not saw_record:
        raise ProbeParseError("ps")
    return tuple(processes)


def parse_windows_processes(payload: bytes) -> tuple[GameProcess, ...]:
    """Parse PowerShell ``ConvertTo-Csv`` records returned from CIM."""
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    if not {"ProcessId", "Name", "CommandLine"}.issubset(reader.fieldnames or ()):
        raise ProbeParseError("CIM")
    processes: list[GameProcess] = []
    for row in reader:
        pid_text, name = row.get("ProcessId"), row.get("Name")
        command_line = row.get("CommandLine") or ""
        if pid_text is None or name is None:
            raise ProbeParseError("CIM")
        pid = _parse_pid(pid_text, "CIM")
        if len(command_line) <= MAX_COMMAND_CHARS and _is_game_executable(name):
            processes.append(GameProcess(pid, name, command_line))
            if len(processes) >= MAX_PROCESS_RECORDS:
                break
    return tuple(processes)


def parse_lsof_open_maps(
    payload: bytes,
    allowed_pids: frozenset[int],
) -> tuple[MapEvidence, ...]:
    """Parse NUL-delimited lsof PID/name fields without splitting path spaces."""
    evidence: list[MapEvidence] = []
    current_pid: int | None = None
    for raw_field in payload.split(b"\0"):
        field = raw_field.lstrip(b"\r\n")
        if not field:
            continue
        if field[:1] == b"p":
            try:
                parsed_pid = _parse_pid(field[1:].decode("ascii"), "lsof")
            except UnicodeDecodeError as exc:
                raise ProbeParseError("lsof") from exc
            current_pid = parsed_pid if parsed_pid in allowed_pids else None
        elif field[:1] == b"n" and current_pid is not None:
            path = Path(os.fsdecode(field[1:]))
            if is_map_path(path):
                evidence.append(MapEvidence(path, EvidenceKind.DIRECT_OPEN, current_pid))
                if len(evidence) >= MAX_OPEN_PATHS:
                    break
    return ordered_evidence(evidence)


def ordered_evidence(evidence: Iterable[MapEvidence]) -> tuple[MapEvidence, ...]:
    return tuple(
        sorted(
            set(evidence),
            key=lambda item: (str(item.path).casefold(), str(item.path), item.process_id or -1),
        )
    )


def _is_posix_game_process(command_line: str) -> bool:
    tokens = parse_command_tokens(command_line, limit=2)
    if not tokens:
        return False
    if _is_game_executable(tokens[0]):
        return True
    executable = _executable_basename(tokens[0])
    if executable in _WINE_EXECUTABLES and len(tokens) > 1:
        return _is_game_executable(tokens[1])
    return _MAC_GAME_COMMAND.match(command_line) is not None


def parse_command_tokens(command_line: str, *, limit: int) -> tuple[str, ...]:
    """Split top-level command arguments without consuming Windows separators."""
    tokens: list[str] = []
    for match in _COMMAND_TOKEN_PATTERN.finditer(command_line):
        token = match.group(1) or match.group(2) or match.group(3)
        if token is None:
            continue
        tokens.append(token)
        if len(tokens) >= limit:
            break
    return tuple(tokens)


def _is_game_executable(value: str) -> bool:
    return _executable_basename(value).removesuffix(".exe") in {"war3", "warcraft iii"}


def _executable_basename(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", maxsplit=1)[-1].strip('"').casefold()


def _parse_pid(value: str, source: str) -> int:
    try:
        pid = int(value)
    except ValueError as exc:
        raise ProbeParseError(source) from exc
    if pid < 1 or pid > 2_147_483_647:
        raise ProbeParseError(source)
    return pid


def is_map_path(path: Path) -> bool:
    return len(str(path)) <= MAX_PATH_CHARS and path.suffix.casefold() in MAP_SUFFIXES
