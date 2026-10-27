"""Public process-linked current-map probe behavior."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from gametool.current_map_models import EvidenceKind, GameProcess, MapEvidence
from gametool.current_map_probe_command import CommandResult
from gametool.current_map_process import (
    OpenMapProbeReport,
    ProbeIssue,
    probe_game_processes,
    probe_open_map_files,
    probe_proc_open_maps,
)


@pytest.mark.skipif(os.name != "posix", reason="requires the POSIX /proc adapter")
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


@pytest.mark.skipif(os.name != "posix", reason="requires the POSIX /proc adapter")
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


@pytest.mark.skipif(os.name != "posix", reason="requires the POSIX /proc adapter")
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


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX /proc and lsof adapters")
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
        partial = MapEvidence(
            Path("/tmp/partial.w3x"), EvidenceKind.DIRECT_OPEN, process.pid
        )
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
    monkeypatch.setattr(
        "gametool.current_map_process.probe_proc_open_maps", denied_proc
    )
    monkeypatch.setattr("gametool.current_map_process._find_absolute_tool", fixed_lsof)
    monkeypatch.setattr("gametool.current_map_process.run_bounded_command", lsof_result)

    # When: the public direct-file probe handles proc denial.
    report = probe_open_map_files((process,))

    # Then: it returns the lsof evidence instead of stopping at proc denial.
    assert report == OpenMapProbeReport(
        (MapEvidence(map_path, EvidenceKind.DIRECT_OPEN, process.pid),),
        True,
    )


@pytest.mark.skipif(
    os.name != "posix", reason="requires the POSIX process-table adapter"
)
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
    lsof_capable = any(
        Path(path).is_file() for path in ("/usr/sbin/lsof", "/usr/bin/lsof")
    )
    if not proc_capable and not lsof_capable:
        pytest.skip(
            "POSIX host exposes neither readable /proc PID fds nor fixed-path lsof"
        )
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
