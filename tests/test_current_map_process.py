"""Public process-linked current-map probe behavior."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path

import pytest

from w3xtool.current_map_models import EvidenceKind, GameProcess, MapEvidence
from w3xtool.current_map_probe_command import CommandResult
from w3xtool.current_map_process import (
    OpenMapProbeReport,
    ProbeIssue,
    ProcessProbeReport,
    explicit_argument_evidence,
    posix_process_report,
    probe_game_processes,
    probe_open_map_files,
    probe_proc_open_maps,
    windows_process_report,
)


def test_public_process_report_caps_game_processes_at_eight() -> None:
    # Given: valid ps output contains nine actual game processes.
    payload = "\n".join(f"{pid} war3" for pid in range(601, 610)).encode()

    # When: the POSIX boundary constructs its public process report.
    report = posix_process_report(payload)

    # Then: only the first eight bounded PID records are exposed.
    assert tuple(item.pid for item in report.processes) == tuple(range(601, 609))


@pytest.mark.parametrize(
    ("report_factory", "payload"),
    (
        (posix_process_report, b"not-a-pid malformed"),
        (windows_process_report, b'"Wrong","Columns"\r\n"1","war3"\r\n'),
    ),
)
def test_malformed_process_output_returns_typed_unavailable_report(
    report_factory: Callable[[bytes], ProcessProbeReport],
    payload: bytes,
) -> None:
    # Given: successful tools returned structurally invalid process records.

    # When: each platform boundary converts its untrusted output.
    report = report_factory(payload)

    # Then: callers receive a stable issue without any raw output text.
    assert report == ProcessProbeReport((), False, ProbeIssue.MALFORMED_OUTPUT)


def test_proc_fd_symlinks_produce_pid_linked_direct_evidence(tmp_path: Path) -> None:
    # Given: a synthetic proc fd tree points at one Chinese map and one non-map.
    process = GameProcess(301, "Warcraft III", "war3")
    map_path = tmp_path / "中文 对战.w3x"
    _ = map_path.write_bytes(b"map")
    ignored_path = tmp_path / "notes.txt"
    _ = ignored_path.write_text("ignore", encoding="utf-8")
    fd_dir = tmp_path / "proc" / str(process.pid) / "fd"
    fd_dir.mkdir(parents=True)
    (fd_dir / "7").symlink_to(map_path)
    (fd_dir / "8").symlink_to(ignored_path)

    # When: the proc adapter inspects only the supplied process.
    report = probe_proc_open_maps((process,), tmp_path / "proc")

    # Then: the map path is preserved and carries its owning PID.
    assert report == OpenMapProbeReport(
        (MapEvidence(map_path, EvidenceKind.DIRECT_OPEN, process.pid),),
        True,
    )


def test_proc_readlink_permission_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: proc enumeration succeeds but reading its descriptor target is denied.
    process = GameProcess(302, "Warcraft III", "war3")
    fd_dir = tmp_path / "proc" / str(process.pid) / "fd"
    fd_dir.mkdir(parents=True)
    (fd_dir / "7").symlink_to(tmp_path / "denied.w3x")

    def deny_readlink(_path: str) -> str:
        raise PermissionError

    monkeypatch.setattr(os, "readlink", deny_readlink)

    # When: the proc adapter inspects the inaccessible descriptor.
    report = probe_proc_open_maps((process,), tmp_path / "proc")

    # Then: permission denial is unavailable, not an available empty observation.
    assert report == OpenMapProbeReport((), False, ProbeIssue.ACCESS_DENIED)


def test_proc_mixed_success_and_permission_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one proc descriptor resolves to a map while another is denied.
    process = GameProcess(304, "Warcraft III", "war3")
    map_path = tmp_path / "partial.w3x"
    _ = map_path.write_bytes(b"partial")
    fd_dir = tmp_path / "proc" / str(process.pid) / "fd"
    fd_dir.mkdir(parents=True)
    (fd_dir / "7").symlink_to(map_path)
    (fd_dir / "8").symlink_to(tmp_path / "denied.w3x")
    real_readlink = os.readlink

    def partly_denied(path: str) -> str:
        if Path(path).name == "8":
            raise PermissionError
        return real_readlink(path)

    monkeypatch.setattr(os, "readlink", partly_denied)

    # When: the proc adapter observes the mixed descriptor set.
    report = probe_proc_open_maps((process,), tmp_path / "proc")

    # Then: partial evidence is discarded and the adapter is unavailable.
    assert report == OpenMapProbeReport((), False, ProbeIssue.ACCESS_DENIED)


def test_public_open_probe_falls_back_to_lsof_after_proc_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: proc is present but denied and bounded lsof returns one direct map.
    process = GameProcess(303, "Warcraft III", "war3")
    map_path = Path("/tmp/fallback.w3x")
    payload = b"p303\0\nn" + os.fsencode(map_path) + b"\0\n"

    def denied_proc(
        _processes: tuple[GameProcess, ...],
        _root: Path,
    ) -> OpenMapProbeReport:
        partial = MapEvidence(Path("/tmp/partial.w3x"), EvidenceKind.DIRECT_OPEN, process.pid)
        return OpenMapProbeReport((partial,), False, ProbeIssue.ACCESS_DENIED)

    def fixed_lsof(_candidates: tuple[Path, ...]) -> Path:
        return Path("/usr/sbin/lsof")

    def lsof_result(
        _command: tuple[str, ...],
        *,
        timeout_seconds: float,
        output_limit: int,
    ) -> CommandResult:
        _ = timeout_seconds, output_limit
        return CommandResult(payload, None, 0)

    def proc_exists(_path: Path) -> bool:
        return True

    monkeypatch.setattr(Path, "is_dir", proc_exists)
    monkeypatch.setattr("w3xtool.current_map_process.probe_proc_open_maps", denied_proc)
    monkeypatch.setattr("w3xtool.current_map_process._find_absolute_tool", fixed_lsof)
    monkeypatch.setattr("w3xtool.current_map_process.run_bounded_command", lsof_result)

    # When: the public direct-file probe handles proc denial.
    report = probe_open_map_files((process,))

    # Then: it returns the lsof evidence instead of stopping at proc denial.
    assert report == OpenMapProbeReport(
        (MapEvidence(map_path, EvidenceKind.DIRECT_OPEN, process.pid),),
        True,
    )


def test_resolves_quoted_map_argument_against_bounded_roots(tmp_path: Path) -> None:
    # Given: a Wine-style quoted relative map argument exists under the second root.
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    map_path = second_root / "Maps" / "中文 对战.w3x"
    map_path.parent.mkdir(parents=True)
    _ = map_path.write_bytes(b"map")
    process = GameProcess(501, "Warcraft III", 'war3.exe -loadfile "Maps\\中文 对战.w3x"')

    # When: explicit arguments are resolved under the supplied roots.
    evidence = explicit_argument_evidence((process,), (first_root, second_root))

    # Then: the existing map is normalized and linked to its process.
    assert evidence == (
        MapEvidence(map_path.resolve(), EvidenceKind.EXPLICIT_ARGUMENT, process.pid),
    )


def test_quoted_map_path_requires_loadfile_flag(tmp_path: Path) -> None:
    # Given: both quoted paths exist, but one is ordinary description text.
    maps = tmp_path / "Maps"
    maps.mkdir()
    selected = maps / "selected map.w3x"
    decoy = maps / "decoy map.w3x"
    _ = selected.write_bytes(b"selected")
    _ = decoy.write_bytes(b"decoy")
    process = GameProcess(
        503,
        "Warcraft III",
        'war3.exe --description "Maps\\decoy map.w3x" --loadfile "Maps\\selected map.w3x"',
    )

    # When: explicit quoted arguments are extracted.
    evidence = explicit_argument_evidence((process,), (tmp_path,))

    # Then: only the path syntactically bound to loadfile becomes evidence.
    assert evidence == (
        MapEvidence(selected.resolve(), EvidenceKind.EXPLICIT_ARGUMENT, process.pid),
    )


def test_nested_description_loadfile_text_is_not_an_argument(tmp_path: Path) -> None:
    # Given: a description token contains loadfile-like text naming an existing map.
    decoy = tmp_path / "Maps" / "decoy.w3x"
    decoy.parent.mkdir()
    _ = decoy.write_bytes(b"decoy")
    process = GameProcess(
        504,
        "Warcraft III",
        "war3.exe --description 'please use -loadfile \"Maps\\decoy.w3x\" later'",
    )

    # When: explicit arguments are parsed from top-level command tokens.
    evidence = explicit_argument_evidence((process,), (tmp_path,))

    # Then: nested prose cannot create direct map evidence.
    assert evidence == ()


def test_resolves_unquoted_loadfile_but_ignores_ordinary_map_text(tmp_path: Path) -> None:
    # Given: both paths exist, but only one follows the explicit -loadfile flag.
    maps = tmp_path / "Maps"
    maps.mkdir()
    selected = maps / "a.w3x"
    decoy = maps / "decoy.w3x"
    _ = selected.write_bytes(b"selected")
    _ = decoy.write_bytes(b"ordinary text")
    process = GameProcess(
        502,
        "Warcraft III",
        r"war3.exe --description Maps\decoy.w3x -loadfile Maps\a.w3x",
    )

    # When: explicit map arguments are extracted from the command line.
    evidence = explicit_argument_evidence((process,), (tmp_path,))

    # Then: the flag-bound unquoted path is retained and ordinary text is ignored.
    assert evidence == (
        MapEvidence(selected.resolve(), EvidenceKind.EXPLICIT_ARGUMENT, process.pid),
    )


def test_explicit_argument_probe_caps_nonexistent_path_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: two process commands contain 80 nonexistent loadfile occurrences.
    calls = 0

    def record_is_file(_path: Path) -> bool:
        nonlocal calls
        calls += 1
        return False

    monkeypatch.setattr(Path, "is_file", record_is_file)
    processes = tuple(
        GameProcess(
            520 + process_index,
            "Warcraft III",
            "war3.exe "
            + " ".join(
                f"-loadfile Maps\\missing-{process_index}-{item}.w3x" for item in range(40)
            ),
        )
        for process_index in range(2)
    )
    roots = tuple(tmp_path / f"root-{item}" for item in range(8))

    # When: explicit arguments are checked against all bounded roots.
    evidence = explicit_argument_evidence(processes, roots)

    # Then: only 64 occurrences reach at most 8 filesystem checks each.
    assert evidence == ()
    assert calls == 64 * 8


@pytest.mark.skipif(os.name != "posix", reason="requires the POSIX process-table adapter")
def test_real_posix_process_probe_reports_available_when_ps_exists() -> None:
    # Given: this POSIX host exposes one of the fixed absolute ps executables.
    if not any(Path(path).is_file() for path in ("/bin/ps", "/usr/bin/ps")):
        pytest.skip("POSIX ps capability is unavailable at the fixed absolute paths")

    # When: game-process discovery runs through the real adapter.
    report = probe_game_processes()

    # Then: the bounded process table was parsed successfully.
    assert report.available
    assert report.issue is None


@pytest.mark.skipif(os.name != "posix", reason="requires a POSIX open-file adapter")
def test_real_posix_adapter_finds_map_opened_by_only_the_injected_pid(
    tmp_path: Path,
) -> None:
    # Given: this pytest PID holds a real temporary map descriptor open.
    pid = os.getpid()
    proc_capable = Path(f"/proc/{pid}/fd").is_dir()
    lsof_capable = any(Path(path).is_file() for path in ("/usr/sbin/lsof", "/usr/bin/lsof"))
    if not proc_capable and not lsof_capable:
        pytest.skip("POSIX host exposes neither readable /proc PID fds nor fixed-path lsof")
    map_path = tmp_path / "真实 当前地图.w3x"
    _ = map_path.write_bytes(b"map")
    process = GameProcess(pid, "Warcraft III", "pytest injected PID")

    # When: the public adapter probes only that injected process while its map is open.
    with map_path.open("rb"):
        report = probe_open_map_files((process,))

    # Then: real direct evidence names the exact map and no other PID.
    assert report.available, report.issue
    assert MapEvidence(map_path, EvidenceKind.DIRECT_OPEN, pid) in report.evidence
    assert all(item.process_id == pid for item in report.evidence)
