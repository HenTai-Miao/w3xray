"""Bounded disk hints and orchestration for current-map resolution."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from itertools import chain, islice
import os
from pathlib import Path, PureWindowsPath
import stat
import time
from typing import Final

from . import current_map_models as models
from . import current_map_process
from .current_map_process import OpenMapProbeReport, ProcessProbeReport
from .gameconfig import parse_game_configuration

_MAX_ROOTS: Final = 8
_MAX_DEPTH: Final = 5
_MAX_DIRECTORY_ENTRIES: Final = 5_000
_MAX_WGC_BYTES: Final = 1_048_576
_MAX_WGC_FILES: Final = 64
_MAX_WGC_BASES: Final = 24
_MAX_ANCESTORS_PER_ROOT: Final = 8
_HINT_WINDOW_NS: Final = 15 * 60 * 1_000_000_000
_MAP_SUFFIXES: Final = frozenset({".w3x", ".w3m", ".w3n"})


type _ProcessProvider = Callable[[], ProcessProbeReport]
type _OpenFileProvider = Callable[[Iterable[models.GameProcess]], OpenMapProbeReport]


def discover_default_map_roots(extra_roots: Iterable[Path] = ()) -> tuple[Path, ...]:
    """Return at most eight unique, existing, non-symlink map roots."""
    roots: list[Path] = []
    seen: set[str] = set()
    candidates = chain(extra_roots, _known_map_roots(Path.home()))
    for candidate in candidates:
        root = Path(os.path.abspath(candidate.expanduser()))
        key = os.path.normcase(os.fspath(root))
        if key in seen:
            continue
        seen.add(key)
        if not _is_real_directory(root):
            continue
        roots.append(root)
        if len(roots) == _MAX_ROOTS:
            break
    return tuple(roots)


def locate_current_map(
    extra_roots: Iterable[Path] = (),
    now_ns: int | None = None,
    *,
    process_provider: _ProcessProvider | None = None,
    open_file_provider: _OpenFileProvider | None = None,
) -> models.CurrentMapResolution:
    """Collect bounded direct and hint evidence, then call the pure resolver."""
    roots = discover_default_map_roots(extra_roots)
    process_report = (process_provider or current_map_process.probe_game_processes)()
    if not process_report.available:
        return models.CurrentMapResolution(models.ResolutionStatus.UNAVAILABLE, ())
    processes = process_report.processes
    evidence: list[models.MapEvidence] = []

    if processes:
        open_probe = open_file_provider or current_map_process.probe_open_map_files
        open_report = open_probe(processes)
        arguments = current_map_process.explicit_argument_evidence(processes, roots)
        direct_evidence = chain(open_report.evidence, arguments)
        evidence.extend(item for item in direct_evidence if _is_regular_map_file(item.path))
        clock_ns = time.time_ns() if now_ns is None else now_ns
        evidence.extend(_scan_hint_evidence(roots, clock_ns))
        direct_probe_available = open_report.available
    else:
        direct_probe_available = True

    return models.resolve_current_map(processes, evidence, direct_probe_available=direct_probe_available)


def _known_map_roots(home: Path) -> tuple[Path, ...]:
    user = home.name
    return (
        home / "Documents" / "Warcraft III" / "Maps",
        home / "Library/Application Support/Blizzard/Warcraft III/Maps",
        home / "Library/Application Support/CrossOver/Bottles/Battle.net/drive_c"
        / "users/crossover/Documents/Warcraft III/Maps",
        home / f".wine/drive_c/users/{user}/Documents/Warcraft III/Maps",
        home / ".wine/drive_c/Program Files (x86)/Warcraft III/Maps",
        Path("/Applications/Warcraft III/Maps"),
        Path("/Volumes") / user / "Program Files (x86)/Warcraft III/Warcraft III Frozen Throne/Maps",
    )


def _scan_hint_evidence(roots: tuple[Path, ...], now_ns: int) -> tuple[models.MapEvidence, ...]:
    pending = deque((root, 0) for root in roots)
    evidence: set[models.MapEvidence] = set()
    seen_entries = 0
    parsed_configs = 0
    while pending and seen_entries < _MAX_DIRECTORY_ENTRIES:
        directory, depth = pending.popleft()
        try:
            entries = os.scandir(directory)
        except OSError:
            continue
        with entries:
            remaining = _MAX_DIRECTORY_ENTRIES - seen_entries
            for entry in islice(entries, remaining):
                seen_entries += 1
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                mode = metadata.st_mode
                if stat.S_ISDIR(mode):
                    if depth < _MAX_DEPTH:
                        pending.append((Path(entry.path), depth + 1))
                    continue
                if not stat.S_ISREG(mode) or not _is_recent(metadata.st_mtime_ns, now_ns):
                    continue
                path = Path(entry.path)
                suffix = path.suffix.casefold()
                if suffix in _MAP_SUFFIXES:
                    evidence.add(models.MapEvidence(path, models.EvidenceKind.RECENT_CACHE))
                elif suffix == ".wgc" and parsed_configs < _MAX_WGC_FILES:
                    parsed_configs += 1
                    evidence.update(_wgc_reference_evidence(path, roots, now_ns))
    return tuple(evidence)


def _wgc_reference_evidence(config_path: Path, roots: tuple[Path, ...], now_ns: int) -> tuple[models.MapEvidence, ...]:
    payload = _read_recent_wgc(config_path, now_ns)
    if payload is None:
        return ()
    try:
        map_path = parse_game_configuration(payload).map_path
    except ValueError:
        return ()
    parts = _relative_windows_map_parts(map_path)
    if parts is None:
        return ()
    evidence: set[models.MapEvidence] = set()
    for base in _wgc_bases(config_path, roots):
        candidate = _regular_descendant(base, parts)
        if candidate is not None:
            evidence.add(models.MapEvidence(candidate, models.EvidenceKind.WGC_REFERENCE))
    return tuple(evidence)


def _read_recent_wgc(path: Path, now_ns: int) -> bytes | None:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            regular = stat.S_ISREG(metadata.st_mode)
            bounded = metadata.st_size <= _MAX_WGC_BYTES
            if not regular or not bounded or not _is_recent(metadata.st_mtime_ns, now_ns):
                return None
            payload = stream.read(_MAX_WGC_BYTES + 1)
    except OSError:
        return None
    return payload if len(payload) <= _MAX_WGC_BYTES else None


def _relative_windows_map_parts(raw_path: str) -> tuple[str, ...] | None:
    windows_path = PureWindowsPath(raw_path.strip())
    if windows_path.drive or windows_path.root:
        return None
    parts = tuple(part for part in windows_path.parts if part not in {"", "."})
    if not parts or ".." in parts or PureWindowsPath(parts[-1]).suffix.casefold() not in _MAP_SUFFIXES:
        return None
    return parts


def _wgc_bases(config_path: Path, roots: tuple[Path, ...]) -> tuple[Path, ...]:
    candidates: list[Path] = [config_path.parent, *roots]
    for root in roots:
        candidates.extend(
            parent
            for parent in islice(chain((root,), root.parents), _MAX_ANCESTORS_PER_ROOT)
            if "warcraft" in parent.name.casefold()
        )
    bases: list[Path] = []
    seen: set[str] = set()
    for base in candidates:
        key = os.path.normcase(os.fspath(base))
        if key in seen:
            continue
        seen.add(key)
        bases.append(base)
        if len(bases) == _MAX_WGC_BASES:
            break
    return tuple(bases)


def _regular_descendant(base: Path, parts: tuple[str, ...]) -> Path | None:
    if not _is_real_directory(base):
        return None
    current = base
    for index, part in enumerate(parts):
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError:
            return None
        final_part = index == len(parts) - 1
        if (final_part and not stat.S_ISREG(mode)) or (
            not final_part and not stat.S_ISDIR(mode)
        ):
            return None
    return current


def _is_real_directory(path: Path) -> bool:
    try:
        return stat.S_ISDIR(path.lstat().st_mode)
    except OSError:
        return False


def _is_regular_map_file(path: Path) -> bool:
    if path.suffix.casefold() not in _MAP_SUFFIXES:
        return False
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _is_recent(mtime_ns: int, now_ns: int) -> bool:
    return 0 <= now_ns - mtime_ns <= _HINT_WINDOW_NS
