"""Pure current-map evidence resolution behavior."""

from __future__ import annotations

from pathlib import Path

from w3xtool.current_map_models import (
    CurrentMapResolution,
    EvidenceKind,
    GameProcess,
    MapCandidate,
    MapEvidence,
    ResolutionStatus,
    resolve_current_map,
)


def test_finds_normalized_path_when_one_direct_map_is_observed(tmp_path: Path) -> None:
    # Given: one game process and one direct path containing a redundant segment.
    process = GameProcess(17, "Warcraft III", "/games/Warcraft III")
    raw_path = tmp_path / "maps" / ".." / "maps" / "中文地图.w3x"
    evidence = MapEvidence(raw_path, EvidenceKind.DIRECT_OPEN, process.pid)

    # When: the pure resolver classifies the observation.
    resolution = resolve_current_map((process,), (evidence,))

    # Then: the unique direct map is selected under its normalized path.
    assert resolution == CurrentMapResolution(
        ResolutionStatus.FOUND,
        (
            MapCandidate(
                raw_path.resolve(strict=False),
                (
                    MapEvidence(
                        raw_path.resolve(strict=False),
                        EvidenceKind.DIRECT_OPEN,
                        process.pid,
                    ),
                ),
            ),
        ),
    )


def test_groups_duplicate_direct_evidence_for_one_normalized_path(
    tmp_path: Path,
) -> None:
    # Given: open-file and argument evidence name the same map differently.
    process = GameProcess(23, "war3", "war3 -loadfile maps/arena.w3x")
    canonical = tmp_path / "maps" / "arena.w3x"
    evidence = (
        MapEvidence(
            canonical.parent / "." / canonical.name, EvidenceKind.EXPLICIT_ARGUMENT, 23
        ),
        MapEvidence(canonical, EvidenceKind.DIRECT_OPEN, 23),
    )

    # When: duplicate observations are resolved.
    resolution = resolve_current_map((process,), evidence)

    # Then: one candidate retains both observations in confidence order.
    assert resolution.status is ResolutionStatus.FOUND
    assert len(resolution.candidates) == 1
    assert resolution.candidates[0].path == canonical.resolve(strict=False)
    assert tuple(item.kind for item in resolution.candidates[0].evidence) == (
        EvidenceKind.DIRECT_OPEN,
        EvidenceKind.EXPLICIT_ARGUMENT,
    )


def test_reports_ambiguity_with_two_direct_paths_in_deterministic_order(
    tmp_path: Path,
) -> None:
    # Given: two game processes directly identify different maps in reverse order.
    processes = (
        GameProcess(31, "war3", "war3 zeta.w3x"),
        GameProcess(29, "war3", "war3 alpha.w3x"),
    )
    zeta = tmp_path / "zeta.w3x"
    alpha = tmp_path / "alpha.w3x"
    evidence = (
        MapEvidence(zeta, EvidenceKind.DIRECT_OPEN, 31),
        MapEvidence(alpha, EvidenceKind.EXPLICIT_ARGUMENT, 29),
    )

    # When: the resolver sees more than one directly linked path.
    resolution = resolve_current_map(processes, evidence)

    # Then: it refuses to guess and presents normalized paths deterministically.
    assert resolution.status is ResolutionStatus.AMBIGUOUS
    assert tuple(candidate.path for candidate in resolution.candidates) == (
        alpha.resolve(strict=False),
        zeta.resolve(strict=False),
    )


def test_suggests_hint_only_paths_when_a_game_process_exists(tmp_path: Path) -> None:
    # Given: a running game and only cache/configuration hint evidence.
    process = GameProcess(41, "Warcraft III", "war3")
    recent = tmp_path / "recent.w3x"
    configured = tmp_path / "configured.w3m"
    evidence = (
        MapEvidence(recent, EvidenceKind.RECENT_CACHE),
        MapEvidence(configured, EvidenceKind.WGC_REFERENCE),
    )

    # When: hints are resolved without direct evidence.
    resolution = resolve_current_map((process,), evidence)

    # Then: candidates are suggestions, never an automatic direct match.
    assert resolution.status is ResolutionStatus.SUGGESTED
    assert tuple(candidate.path for candidate in resolution.candidates) == (
        configured.resolve(strict=False),
        recent.resolve(strict=False),
    )


def test_treats_game_log_entries_as_suggestion_tier_hints(tmp_path: Path) -> None:
    # Given: a running game whose own log named one loaded map.
    process = GameProcess(43, "Warcraft III", "war3")
    logged = tmp_path / "logged.w3x"
    evidence = (MapEvidence(logged, EvidenceKind.GAME_LOG),)

    # When: the log hint is resolved without any direct evidence.
    resolution = resolve_current_map((process,), evidence)

    # Then: the logged map is only ever suggested for confirmation.
    assert resolution.status is ResolutionStatus.SUGGESTED
    assert tuple(candidate.path for candidate in resolution.candidates) == (
        logged.resolve(strict=False),
    )


def test_game_log_hint_outranks_weaker_disk_hints(tmp_path: Path) -> None:
    # Given: the live game's log names one map while disk recency names two others.
    process = GameProcess(47, "Warcraft III", "war3")
    logged = tmp_path / "logged.w3x"
    recent_a = tmp_path / "recent_a.w3x"
    recent_b = tmp_path / "recent_b.w3m"
    evidence = (
        MapEvidence(recent_a, EvidenceKind.RECENT_CACHE),
        MapEvidence(recent_b, EvidenceKind.RECENT_CACHE),
        MapEvidence(logged, EvidenceKind.GAME_LOG),
    )

    # When: hints are resolved without any direct evidence.
    resolution = resolve_current_map((process,), evidence)

    # Then: the log-backed map is the only suggestion, never "non-unique".
    assert resolution.status is ResolutionStatus.SUGGESTED
    assert tuple(candidate.path for candidate in resolution.candidates) == (
        logged.resolve(strict=False),
    )


def test_ignores_hint_only_paths_without_a_game_process(tmp_path: Path) -> None:
    # Given: a recently touched cache map but no detected game process.
    evidence = (MapEvidence(tmp_path / "recent.w3x", EvidenceKind.RECENT_CACHE),)

    # When: the hint is resolved without a running game.
    resolution = resolve_current_map((), evidence)

    # Then: the resolver does not present an unrelated recent file.
    assert resolution == CurrentMapResolution(ResolutionStatus.NOT_FOUND, ())


def test_ignores_direct_observation_without_a_game_process(tmp_path: Path) -> None:
    # Given: direct-looking evidence names a PID but no game process was detected.
    evidence = (MapEvidence(tmp_path / "orphan.w3x", EvidenceKind.DIRECT_OPEN, 59),)

    # When: the observation is resolved without a running game.
    resolution = resolve_current_map((), evidence)

    # Then: an unlinked observation cannot authorize automatic map selection.
    assert resolution == CurrentMapResolution(ResolutionStatus.NOT_FOUND, ())


def test_ignores_direct_observation_from_unknown_process(tmp_path: Path) -> None:
    # Given: a game exists but the direct observation belongs to another PID.
    process = GameProcess(61, "Warcraft III", "war3")
    evidence = (
        MapEvidence(tmp_path / "unlinked.w3x", EvidenceKind.EXPLICIT_ARGUMENT, 999),
    )

    # When: the observation is resolved against detected game processes.
    resolution = resolve_current_map((process,), evidence)

    # Then: evidence from an unknown PID cannot become a direct candidate.
    assert resolution == CurrentMapResolution(ResolutionStatus.NOT_FOUND, ())


def test_reports_unavailable_when_direct_probe_is_missing_for_running_game() -> None:
    # Given: a game process on a platform without an available direct-file probe.
    process = GameProcess(53, "Warcraft III", "war3")

    # When: resolution receives no evidence from the unavailable probe.
    resolution = resolve_current_map(
        (process,),
        (),
        direct_probe_available=False,
    )

    # Then: probe unavailability is distinct from an ordinary empty result.
    assert resolution == CurrentMapResolution(ResolutionStatus.UNAVAILABLE, ())
