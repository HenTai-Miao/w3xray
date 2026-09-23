"""Typed observations and pure resolution for the current Warcraft map."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path
from typing import assert_never


@unique
class EvidenceKind(StrEnum):
    """Confidence-bearing source of a possible current map path."""

    DIRECT_OPEN = "direct_open"
    EXPLICIT_ARGUMENT = "explicit_argument"
    WGC_REFERENCE = "wgc_reference"
    RECENT_CACHE = "recent_cache"
    GAME_LOG = "game_log"


@unique
class ResolutionStatus(StrEnum):
    """Exhaustive outcome of current-map evidence resolution."""

    FOUND = "found"
    AMBIGUOUS = "ambiguous"
    SUGGESTED = "suggested"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class GameProcess:
    """Operating-system observation of one running Warcraft game process."""

    pid: int
    name: str
    command_line: str


@dataclass(frozen=True, slots=True)
class MapEvidence:
    """One observed map path and the probe that supplied it."""

    path: Path
    kind: EvidenceKind
    process_id: int | None = None


@dataclass(frozen=True, slots=True)
class MapCandidate:
    """All observations grouped under one normalized map path."""

    path: Path
    evidence: tuple[MapEvidence, ...]


@dataclass(frozen=True, slots=True)
class CurrentMapResolution:
    """Deterministic candidate set classified for safe caller behavior."""

    status: ResolutionStatus
    candidates: tuple[MapCandidate, ...]


def resolve_current_map(
    processes: Iterable[GameProcess],
    evidence: Iterable[MapEvidence],
    *,
    direct_probe_available: bool = True,
) -> CurrentMapResolution:
    """Group normalized evidence and construct the safe resolution status."""
    game_processes = tuple(processes)
    game_process_ids = frozenset(process.pid for process in game_processes)
    has_game_process = bool(game_processes)
    grouped: dict[Path, list[MapEvidence]] = {}
    direct_paths: set[Path] = set()
    hint_paths: set[Path] = set()

    for observation in evidence:
        path = Path(
            os.path.normcase(observation.path.expanduser().resolve(strict=False))
        )
        normalized = MapEvidence(path, observation.kind, observation.process_id)
        grouped.setdefault(path, []).append(normalized)
        match observation.kind:
            case EvidenceKind.DIRECT_OPEN | EvidenceKind.EXPLICIT_ARGUMENT:
                if observation.process_id in game_process_ids:
                    direct_paths.add(path)
            case EvidenceKind.WGC_REFERENCE | EvidenceKind.RECENT_CACHE | EvidenceKind.GAME_LOG:
                hint_paths.add(path)
            case unreachable:
                assert_never(unreachable)

    candidates = tuple(
        MapCandidate(
            path,
            tuple(
                sorted(
                    grouped[path],
                    key=lambda item: (
                        item.kind.value,
                        item.process_id is None,
                        item.process_id if item.process_id is not None else -1,
                    ),
                )
            ),
        )
        for path in sorted(grouped, key=lambda item: (str(item).casefold(), str(item)))
    )
    direct_candidates = tuple(item for item in candidates if item.path in direct_paths)
    if len(direct_candidates) == 1:
        return CurrentMapResolution(ResolutionStatus.FOUND, direct_candidates)
    if len(direct_candidates) > 1:
        return CurrentMapResolution(ResolutionStatus.AMBIGUOUS, direct_candidates)

    hint_candidates = tuple(
        item for item in candidates if has_game_process and item.path in hint_paths
    )
    if hint_candidates:
        return CurrentMapResolution(ResolutionStatus.SUGGESTED, hint_candidates)
    if has_game_process and not direct_probe_available:
        return CurrentMapResolution(ResolutionStatus.UNAVAILABLE, ())
    return CurrentMapResolution(ResolutionStatus.NOT_FOUND, ())
