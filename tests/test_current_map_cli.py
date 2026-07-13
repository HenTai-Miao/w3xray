from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import partial
import os
from pathlib import Path
import subprocess
import sys
from typing import Never

import pytest

from w3xtool import current_map_cli as cli
from w3xtool.cli_options import CliOptions
from w3xtool.current_map_models import CurrentMapResolution, EvidenceKind, MapCandidate, MapEvidence, ResolutionStatus
from w3xtool.current_map_snapshot import CurrentMapSnapshotError


@dataclass(frozen=True, slots=True)
class _Snapshot:
    path: Path


def _candidate(path: Path, kind: EvidenceKind) -> MapCandidate:
    return MapCandidate(path, (MapEvidence(path, kind, 73),))


def _provide_resolution(_roots: Iterable[Path], *, resolution: CurrentMapResolution) -> CurrentMapResolution:
    return resolution


def _provide_snapshot(_path: str | Path, *, snapshot: _Snapshot) -> _Snapshot:
    return snapshot


def _reject_snapshot(_path: str | Path) -> Never:
    pytest.fail("must not snapshot")


def _return_two(_options: CliOptions) -> int:
    return 2


def _raise_boom(_options: CliOptions) -> Never:
    raise CurrentMapSnapshotError(Path("delegate.w3x"), "boom")


def _patch_resolution(monkeypatch: pytest.MonkeyPatch, resolution: CurrentMapResolution) -> None:
    monkeypatch.setattr(cli, "cleanup_stale_current_map_snapshots", lambda: None)
    provider = partial(_provide_resolution, resolution=resolution)
    monkeypatch.setattr(cli, "locate_current_map", provider)


def _patch_found_snapshot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _Snapshot:
    source = tmp_path / "source.w3x"
    snapshot = _Snapshot(tmp_path / "snapshot.w3x")
    resolution = CurrentMapResolution(ResolutionStatus.FOUND, (_candidate(source, EvidenceKind.DIRECT_OPEN),))
    _patch_resolution(monkeypatch, resolution)
    provider = partial(_provide_snapshot, snapshot=snapshot)
    monkeypatch.setattr(cli, "create_current_map_snapshot", provider)
    return snapshot


def test_parser_forwards_sources_and_preserves_repeated_roots() -> None:
    # Given: repeated discovery roots plus every existing map-CLI option.
    argv = (
        "--root", "maps-a", "--listfile", "names.txt", "--root", "maps-b",
        "--game-data", "game-data", "--author-bundle", "bundle", "--pack", "pack",
        "--accept-suggestion",
    )

    # When: current-map arguments cross the typed parsing boundary.
    options = cli.parse_current_map_cli_options(argv)

    # Then: roots stay ordered and map options are forwarded without a positional map.
    assert options == cli.CurrentMapCliOptions(
        roots=(Path("maps-a"), Path("maps-b")),
        accept_suggestion=True,
        map_options=CliOptions("", "names.txt", "game-data", "pack", "bundle"),
    )


@pytest.mark.parametrize("argv", (
    ("map.w3x",), ("--unknown",), ("--root",), ("--listfile",),
    ("--pack", "one", "--pack", "two"), ("--accept-suggestion", "--accept-suggestion"),
))
def test_parser_rejects_positional_unknown_missing_and_duplicate_options(argv: tuple[str, ...]) -> None:
    # Given: an invalid current-map argument sequence.
    # When/Then: a stable typed boundary error rejects it.
    with pytest.raises(cli.CurrentMapCliOptionError):
        _ = cli.parse_current_map_cli_options(argv)


def test_parser_error_sanitizes_untrusted_option_text() -> None:
    # Given: an unknown option containing terminal and line controls.
    with pytest.raises(cli.CurrentMapCliOptionError) as caught:
        _ = cli.parse_current_map_cli_options(("--bad\x1b[2J\nforged",))

    # When: the typed error is rendered.
    rendered = str(caught.value)

    # Then: raw controls cannot alter terminal state or inject a line.
    assert "\x1b" not in rendered
    assert "\n" not in rendered
    assert "forged" in rendered


@pytest.mark.parametrize(("status", "accept_suggestion", "kind"), (
    (ResolutionStatus.FOUND, False, EvidenceKind.DIRECT_OPEN),
    (ResolutionStatus.SUGGESTED, True, EvidenceKind.WGC_REFERENCE),
))
def test_unique_authorized_candidate_snapshots_delegates_and_cleans(
    status: ResolutionStatus,
    accept_suggestion: bool,
    kind: EvidenceKind,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: one authorized candidate and tracked acquisition boundaries.
    source = tmp_path / "source\x1b\nmap.w3x"
    snapshot = _Snapshot(tmp_path / "snapshot.w3x")
    resolution = CurrentMapResolution(status, (_candidate(source, kind),))
    events: list[str] = []
    delegated: list[CliOptions] = []
    def cleanup_stale() -> None:
        events.append("stale")

    def locate(roots: Iterable[Path]) -> CurrentMapResolution:
        events.append(f"locate:{len(tuple(roots))}")
        return resolution

    def create(path: str | Path) -> _Snapshot:
        events.append(f"snapshot:{Path(path).name}")
        return snapshot

    def delegate(options: CliOptions) -> int:
        events.append("delegate")
        delegated.append(options)
        return 0

    def cleanup(item: _Snapshot) -> None:
        events.append(f"cleanup:{item.path.name}")

    monkeypatch.setattr(cli, "cleanup_stale_current_map_snapshots", cleanup_stale)
    monkeypatch.setattr(cli, "locate_current_map", locate)
    monkeypatch.setattr(cli, "create_current_map_snapshot", create)
    monkeypatch.setattr(cli, "run_cli", delegate)
    monkeypatch.setattr(cli, "cleanup_current_map_snapshot", cleanup)
    options = cli.CurrentMapCliOptions(
        roots=(tmp_path,),
        accept_suggestion=accept_suggestion,
        map_options=CliOptions("", "names.txt", "data", "pack", "bundle"),
    )

    # When: the current-map workflow runs.
    code = cli.run_current_map_cli(options)

    # Then: stale cleanup precedes acquisition and the private snapshot is always removed.
    assert code == 0
    assert events == ["stale", "locate:1", f"snapshot:{source.name}", "delegate", "cleanup:snapshot.w3x"]
    assert delegated == [CliOptions(str(snapshot.path), "names.txt", "data", "pack", "bundle")]
    diagnostic = capsys.readouterr().err
    assert "\x1b" not in diagnostic
    assert "来源" in diagnostic and kind.value not in diagnostic


def test_single_suggestion_requires_explicit_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: one hint-only candidate without explicit acceptance.
    resolution = CurrentMapResolution(ResolutionStatus.SUGGESTED, (_candidate(tmp_path / "hint.w3x", EvidenceKind.RECENT_CACHE),))
    _patch_resolution(monkeypatch, resolution)
    monkeypatch.setattr(cli, "create_current_map_snapshot", _reject_snapshot)

    # When: the current-map workflow runs without the acceptance flag.
    code = cli.run_current_map_cli(cli.CurrentMapCliOptions())

    # Then: it refuses the hint and explains the explicit opt-in.
    assert code == 3
    assert "--accept-suggestion" in capsys.readouterr().err


@pytest.mark.parametrize(("status", "kind"), (
    (ResolutionStatus.SUGGESTED, EvidenceKind.RECENT_CACHE),
    (ResolutionStatus.AMBIGUOUS, EvidenceKind.DIRECT_OPEN),
))
def test_multiple_candidates_return_three_with_bounded_sanitized_paths(
    status: ResolutionStatus,
    kind: EvidenceKind,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: ten candidates, including terminal controls, that must not be guessed.
    candidates = tuple(
        _candidate(tmp_path / f"candidate-{index}\x1b.w3x", kind) for index in range(10)
    )
    _patch_resolution(monkeypatch, CurrentMapResolution(status, candidates))
    monkeypatch.setattr(cli, "create_current_map_snapshot", _reject_snapshot)

    # When: the caller even opts in to a non-unique suggestion set.
    code = cli.run_current_map_cli(cli.CurrentMapCliOptions(accept_suggestion=True))

    # Then: output is bounded to eight inert paths and reports the omitted count.
    diagnostic = capsys.readouterr().err
    assert code == 3
    assert "candidate-0" in diagnostic
    assert "candidate-7" in diagnostic
    assert "candidate-8" not in diagnostic
    assert "另有 2 个" in diagnostic
    assert "\x1b" not in diagnostic


@pytest.mark.parametrize("status", (ResolutionStatus.NOT_FOUND, ResolutionStatus.UNAVAILABLE))
def test_no_usable_candidate_returns_two(
    status: ResolutionStatus, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: discovery cannot supply a usable current map.
    _patch_resolution(monkeypatch, CurrentMapResolution(status, ()))

    # When: the current-map workflow runs.
    code = cli.run_current_map_cli(cli.CurrentMapCliOptions())

    # Then: it reports a stable operational failure.
    assert code == 2
    assert capsys.readouterr().err


def test_snapshot_failure_returns_two_with_sanitized_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: direct discovery succeeds but stable copying fails.
    source = tmp_path / "source.w3x"
    resolution = CurrentMapResolution(ResolutionStatus.FOUND, (_candidate(source, EvidenceKind.EXPLICIT_ARGUMENT),))
    _patch_resolution(monkeypatch, resolution)

    def fail_snapshot(path: Path) -> _Snapshot:
        raise CurrentMapSnapshotError(path, "disk\x1b[2J\nfailed")

    monkeypatch.setattr(cli, "create_current_map_snapshot", fail_snapshot)

    # When: snapshot creation fails at its typed boundary.
    code = cli.run_current_map_cli(cli.CurrentMapCliOptions())

    # Then: the stable code and diagnostic expose no control sequence or host path.
    diagnostic = capsys.readouterr().err
    assert code == 2
    assert "无法创建" in diagnostic
    assert "\x1b" not in diagnostic
    assert str(source) not in diagnostic.splitlines()[-1]


def test_snapshot_cleanup_runs_when_delegate_returns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: an acquired snapshot and a downstream map-parser failure.
    snapshot = _patch_found_snapshot(monkeypatch, tmp_path)
    cleaned: list[_Snapshot] = []
    monkeypatch.setattr(cli, "run_cli", _return_two)
    monkeypatch.setattr(cli, "cleanup_current_map_snapshot", cleaned.append)

    # When: the existing CLI returns.
    code = cli.run_current_map_cli(cli.CurrentMapCliOptions())

    # Then: its exact code is preserved and the snapshot is removed once.
    assert code == 2
    assert cleaned == [snapshot]


def test_snapshot_cleanup_runs_when_delegate_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: an acquired snapshot and an unexpected downstream exception.
    snapshot = _patch_found_snapshot(monkeypatch, tmp_path)
    cleaned: list[_Snapshot] = []
    monkeypatch.setattr(cli, "run_cli", _raise_boom)
    monkeypatch.setattr(cli, "cleanup_current_map_snapshot", cleaned.append)

    # When/Then: the exception propagates only after deterministic cleanup.
    with pytest.raises(CurrentMapSnapshotError, match="boom"):
        _ = cli.run_current_map_cli(cli.CurrentMapCliOptions())
    assert cleaned == [snapshot]


def test_main_current_process_returns_two_for_bad_option() -> None:
    # Given: the real current-map command with an unsupported option.
    project_root = Path(__file__).resolve().parents[1]

    # When: the public process entrypoint parses it.
    result = subprocess.run(
        (sys.executable, "main.py", "current", "--bad\x1b[2J\nforged"),
        cwd=project_root,
        check=False,
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )

    # Then: it exits through the typed parser boundary without control injection.
    assert result.returncode == 2
    assert "参数" in result.stderr
    assert "\x1b" not in result.stderr
    assert result.stdout == ""
