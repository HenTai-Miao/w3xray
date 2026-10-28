"""Complete disk discovery and evidence-based current-map resolution."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from itertools import chain
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import time
from typing import Final

from . import current_map_models as models
from . import current_map_process
from .bounded_file import FileIdentity, read_bounded_regular_file
from .current_map_inuse_probe import probe_in_use_files
from .current_map_process import OpenMapProbeReport, ProcessProbeReport
from .gameconfig import parse_game_configuration
from .windows_output_paths import native_output_path

_HINT_WINDOW_NS: Final = 4 * 60 * 60 * 1_000_000_000
_LOG_WINDOW_NS: Final = 15 * 60 * 1_000_000_000
_LOG_RELPATH: Final = ("Documents", "Warcraft III", "Logs", "War3Log.txt")
_OPENING_MAP_MARKER: Final = re.compile(r"opening map - ", re.IGNORECASE)
_MAP_SUFFIXES: Final = frozenset({".w3x", ".w3m", ".w3n"})
_IN_USE_BATCH_SIZE: Final = 512
_HINT_EVIDENCE_KINDS: Final = frozenset(
    {
        models.EvidenceKind.RECENT_CACHE,
        models.EvidenceKind.WGC_REFERENCE,
        models.EvidenceKind.GAME_LOG,
    }
)


type _ProcessProvider = Callable[[], ProcessProbeReport]
type _OpenFileProvider = Callable[[Iterable[models.GameProcess]], OpenMapProbeReport]
type _InUseProvider = Callable[[Iterable[Path]], tuple[Path, ...]]


@dataclass(frozen=True, slots=True)
class _RootScan:
    """Complete outcome of one map-root directory sweep.

    ``evidence`` keeps only recency-windowed hints; ``map_files`` records
    every regular map file seen during the same walk so in-use
    probing can also cover long-lived local maps whose modification time
    predates the hint window.
    """

    evidence: tuple[models.MapEvidence, ...]
    map_files: tuple[tuple[Path, int], ...]


def discover_default_map_roots(extra_roots: Iterable[Path] = ()) -> tuple[Path, ...]:
    """Return every unique, existing, non-symlink map root."""
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
    return tuple(roots)


def locate_current_map(
    extra_roots: Iterable[Path] = (),
    now_ns: int | None = None,
    *,
    process_provider: _ProcessProvider | None = None,
    open_file_provider: _OpenFileProvider | None = None,
    in_use_provider: _InUseProvider | None = None,
) -> models.CurrentMapResolution:
    """Collect all direct and hint evidence, then call the pure resolver."""
    process_report = (process_provider or current_map_process.probe_game_processes)()
    if not process_report.available:
        return models.CurrentMapResolution(models.ResolutionStatus.UNAVAILABLE, ())
    processes = process_report.processes
    process_roots = (
        root / child
        for process in processes
        for root in current_map_process.process_install_roots(process)
        for child in ("Maps", "Campaigns")
    )
    roots = discover_default_map_roots(chain(extra_roots, process_roots))
    evidence: list[models.MapEvidence] = []

    if processes:
        open_probe = open_file_provider or current_map_process.probe_open_map_files
        open_report = open_probe(processes)
        arguments = current_map_process.explicit_argument_evidence(processes, roots)
        direct_evidence = chain(open_report.evidence, arguments)
        evidence.extend(
            item for item in direct_evidence if _is_regular_map_file(item.path)
        )
        clock_ns = time.time_ns() if now_ns is None else now_ns
        scan = _scan_hint_evidence(roots, clock_ns)
        evidence.extend(scan.evidence)
        evidence.extend(_log_hint_evidence(Path.home(), roots, clock_ns))
        evidence.extend(
            _in_use_evidence(
                evidence, scan.map_files, in_use_provider or probe_in_use_files
            )
        )
        direct_probe_available = open_report.available
    else:
        direct_probe_available = True

    return models.resolve_current_map(
        processes, evidence, direct_probe_available=direct_probe_available
    )


def _in_use_evidence(
    evidence: list[models.MapEvidence],
    root_map_files: tuple[tuple[Path, int], ...],
    provider: _InUseProvider,
) -> tuple[models.MapEvidence, ...]:
    """Probe every map candidate newest-first for live file handles.

    Recency hints keep their head start, but every map file discovered
    during the root walk joins the queue: a long-lived local map
    that was simply re-hosted carries an old modification time and would
    otherwise never be probed. Candidates are probed in provider-sized
    batches, without limiting the total number of candidates.
    """
    candidates: dict[str, tuple[Path, int]] = {}
    for item in evidence:
        if item.kind not in _HINT_EVIDENCE_KINDS:
            continue
        candidates.setdefault(
            os.path.normcase(os.fspath(item.path)), (item.path, item.mtime_ns or 0)
        )
    for path, mtime_ns in root_map_files:
        candidates.setdefault(os.path.normcase(os.fspath(path)), (path, mtime_ns))
    ordered = sorted(candidates.values(), key=lambda item: (-item[1], str(item[0])))
    paths = [item[0] for item in ordered]
    hits: list[Path] = []
    for start in range(0, len(paths), _IN_USE_BATCH_SIZE):
        hits.extend(provider(paths[start : start + _IN_USE_BATCH_SIZE]))
    return tuple(
        models.MapEvidence(path, models.EvidenceKind.LIVE_FILE) for path in hits
    )


def _windows_classic_map_roots() -> tuple[Path, ...]:
    """Fixed classic-install map and campaign roots on the Windows system drive.

    Campaign sessions load missions from a ``.w3n`` sibling of ``Maps``; without
    these roots the in-use probe never sees the open campaign file.
    """
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    drive = PureWindowsPath(system_root).drive or "C:"
    base = PureWindowsPath(f"{drive}\\") / "Program Files (x86)" / "Warcraft III"
    tft = base / "Warcraft III Frozen Throne"
    return (
        Path(base / "Maps"),
        Path(tft / "Maps"),
        Path(tft / "Campaigns"),
        Path(base / "Campaigns"),
    )


def _known_map_roots(home: Path) -> tuple[Path, ...]:
    user = home.name
    return (
        home / "Documents" / "Warcraft III" / "Maps",
        *_windows_classic_map_roots(),
        home / "Library/Application Support/Blizzard/Warcraft III/Maps",
        home
        / "Library/Application Support/CrossOver/Bottles/Battle.net/drive_c"
        / "users/crossover/Documents/Warcraft III/Maps",
        home / f".wine/drive_c/users/{user}/Documents/Warcraft III/Maps",
        home / ".wine/drive_c/Program Files (x86)/Warcraft III/Maps",
        Path("/Applications/Warcraft III/Maps"),
        Path("/Volumes")
        / user
        / "Program Files (x86)/Warcraft III/Warcraft III Frozen Throne/Maps",
    )


def _scan_hint_evidence(roots: tuple[Path, ...], now_ns: int) -> _RootScan:
    pending = deque(roots)
    evidence: set[models.MapEvidence] = set()
    map_files: list[tuple[Path, int]] = []
    seen_directories: set[tuple[int, int]] = set()
    while pending:
        directory = pending.popleft()
        try:
            directory_io = Path(native_output_path(str(directory)))
            directory_metadata = directory_io.lstat()
            identity = (directory_metadata.st_dev, directory_metadata.st_ino)
            if (
                not _real_directory_metadata(directory_metadata)
                or identity in seen_directories
            ):
                continue
            seen_directories.add(identity)
            entries = os.scandir(directory_io)
        except OSError:
            continue
        with entries:
            for entry in entries:
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                mode = metadata.st_mode
                if stat.S_ISDIR(mode):
                    if _real_directory_metadata(metadata):
                        pending.append(directory / entry.name)
                    continue
                if not stat.S_ISREG(mode):
                    continue
                path = directory / entry.name
                suffix = path.suffix.casefold()
                if suffix in _MAP_SUFFIXES:
                    map_files.append((path, metadata.st_mtime_ns))
                    if _is_recent(metadata.st_mtime_ns, now_ns):
                        evidence.add(
                            models.MapEvidence(
                                path,
                                models.EvidenceKind.RECENT_CACHE,
                                mtime_ns=metadata.st_mtime_ns,
                            )
                        )
                elif suffix == ".wgc":
                    evidence.update(_wgc_reference_evidence(path, roots, now_ns))
    return _RootScan(tuple(evidence), tuple(map_files))


def _log_hint_evidence(
    home: Path,
    roots: tuple[Path, ...],
    now_ns: int,
) -> tuple[models.MapEvidence, ...]:
    """Read the live game's freshly written log; its last opening line is a hint.

    The log is append-only history: a last entry written long ago describes a
    previous session's map, so only a log touched within the window counts.
    """
    payload = _read_recent_file(home.joinpath(*_LOG_RELPATH), now_ns, _LOG_WINDOW_NS)
    if payload is None:
        return ()
    lines = payload.decode("utf-8", errors="replace").splitlines()
    for line in reversed(lines):
        raw = _opening_map_path(line)
        if raw is None:
            continue
        # An unresolved newer session must not revive an older opening line.
        return tuple(
            models.MapEvidence(path, models.EvidenceKind.GAME_LOG)
            for path in _resolve_log_hints(raw, roots)
        )
    return ()


def _read_recent_file(path: Path, now_ns: int, window_ns: int) -> bytes | None:
    """Read a complete, recent, stable regular file without following links."""
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or not 0 <= now_ns - metadata.st_mtime_ns <= window_ns
        ):
            return None
        payload, _ = read_bounded_regular_file(
            path,
            expected=FileIdentity(metadata.st_dev, metadata.st_ino, metadata.st_size),
        )
        after = path.lstat()
        if (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mtime_ns,
            metadata.st_size,
        ) != (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_size):
            return None
        return payload
    except OSError:
        return None


def _opening_map_path(line: str) -> str | None:
    markers = list(_OPENING_MAP_MARKER.finditer(line))
    if not markers:
        return None
    raw = line[markers[-1].end() :].strip()
    return raw or None


def _resolve_log_hints(raw: str, roots: tuple[Path, ...]) -> tuple[Path, ...]:
    windows_path = PureWindowsPath(raw)
    normalized = raw.replace("\\", "/")
    if windows_path.drive or windows_path.root:
        candidate = Path(normalized)
        return (candidate,) if _is_regular_map_file(candidate) else ()
    parts = _relative_windows_map_parts(raw)
    if parts is None:
        return ()
    candidates: dict[str, Path] = {}
    for base in roots:
        candidate = _regular_descendant(base, parts)
        if candidate is not None:
            candidates.setdefault(os.path.normcase(os.fspath(candidate)), candidate)
    return tuple(candidates.values())


def _wgc_reference_evidence(
    config_path: Path, roots: tuple[Path, ...], now_ns: int
) -> tuple[models.MapEvidence, ...]:
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
            evidence.add(
                models.MapEvidence(candidate, models.EvidenceKind.WGC_REFERENCE)
            )
    return tuple(evidence)


def _read_recent_wgc(path: Path, now_ns: int) -> bytes | None:
    return _read_recent_file(path, now_ns, _HINT_WINDOW_NS)


def _relative_windows_map_parts(raw_path: str) -> tuple[str, ...] | None:
    windows_path = PureWindowsPath(raw_path.strip())
    if windows_path.drive or windows_path.root:
        return None
    parts = tuple(part for part in windows_path.parts if part not in {"", "."})
    if (
        not parts
        or ".." in parts
        or PureWindowsPath(parts[-1]).suffix.casefold() not in _MAP_SUFFIXES
    ):
        return None
    return parts


def _wgc_bases(config_path: Path, roots: tuple[Path, ...]) -> tuple[Path, ...]:
    candidates: list[Path] = [config_path.parent, *roots]
    for root in roots:
        candidates.extend(
            parent
            for parent in chain((root,), root.parents)
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
    return tuple(bases)


def _regular_descendant(base: Path, parts: tuple[str, ...]) -> Path | None:
    if not _is_real_directory(base):
        return None
    current = base
    for index, part in enumerate(parts):
        current /= part
        try:
            metadata = current.lstat()
        except OSError:
            return None
        final_part = index == len(parts) - 1
        if (final_part and not stat.S_ISREG(metadata.st_mode)) or (
            not final_part and not _real_directory_metadata(metadata)
        ):
            return None
    return current


def _is_real_directory(path: Path) -> bool:
    try:
        return _real_directory_metadata(path.lstat())
    except OSError:
        return False


def _real_directory_metadata(metadata: os.stat_result) -> bool:
    return stat.S_ISDIR(metadata.st_mode) and not (
        (getattr(metadata, "st_file_attributes", 0) or 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _is_regular_map_file(path: Path) -> bool:
    if path.suffix.casefold() not in _MAP_SUFFIXES:
        return False
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _is_recent(mtime_ns: int, now_ns: int) -> bool:
    return 0 <= now_ns - mtime_ns <= _HINT_WINDOW_NS
