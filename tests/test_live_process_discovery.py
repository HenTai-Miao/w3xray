"""Unavailable process observation cannot masquerade as an absent game."""

from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

from gametool import current_map_process
from gametool.current_map_models import GameProcess
from gametool.current_map_process import ProbeIssue, ProcessProbeReport


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows live API")


@pytest.mark.parametrize("issue", tuple(ProbeIssue))
def test_live_discovery_preserves_typed_probe_failure(
    monkeypatch: pytest.MonkeyPatch, issue: ProbeIssue
) -> None:
    from gametool import live_inventory as live

    monkeypatch.setattr(
        current_map_process,
        "probe_game_processes",
        lambda: ProcessProbeReport((), False, issue),
    )
    with pytest.raises(OSError, match=issue.value):
        live.find_war3_pids()


def test_live_discovery_uses_exact_shared_process_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gametool import live_inventory as live

    report = current_map_process.windows_process_report(
        b'"ProcessId","Name","CommandLine"\n'
        b'"1","Warcraft Launcher.exe",""\n'
        b'"42","war3.exe",""\n'
        b'"43","Warcraft III.exe",""\n'
    )
    monkeypatch.setattr(current_map_process, "probe_game_processes", lambda: report)
    assert live.find_war3_pids() == [42, 43]


@pytest.mark.parametrize("entrypoint", ("live", "dump", "hero"))
def test_process_failure_reaches_each_entrypoint_without_open_or_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    entrypoint: str,
) -> None:
    from gametool import live_inventory as live

    monkeypatch.setattr(
        current_map_process,
        "probe_game_processes",
        lambda: ProcessProbeReport((), False, ProbeIssue.ACCESS_DENIED),
    )
    monkeypatch.setattr(live, "mem_setup", lambda: None)
    open_process = Mock(side_effect=AssertionError("must not open a process"))
    monkeypatch.setattr(live, "open_process", open_process)
    destination = tmp_path / "no-publication"
    if entrypoint == "live":
        report = live.read_live(None, verbose=False)
        messages = report["notes"]
        assert report["pid"] is None and not report["units"]
    elif entrypoint == "dump":
        from gametool.live_object_dump import dump_live_objects

        result = dump_live_objects(str(destination), verbose=False)
        messages = result.notes
        assert result.objects == 0 and result.files == 0
    else:
        from gametool import hero_chain

        monkeypatch.setattr(sys, "argv", ["hero_chain", "--pack", str(tmp_path)])
        assert hero_chain.main() == 2
        messages = [capsys.readouterr().err]
    assert any("access_denied" in message for message in messages)
    assert all("war3 未运行" not in message for message in messages)
    open_process.assert_not_called()
    assert not destination.exists()


def test_confirmed_empty_process_observation_remains_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gametool import live_inventory as live

    monkeypatch.setattr(
        current_map_process,
        "probe_game_processes",
        lambda: ProcessProbeReport((), True),
    )
    assert live.find_war3_pids() == []


def test_shared_pid_list_is_unique_and_sorted(monkeypatch: pytest.MonkeyPatch) -> None:
    from gametool import live_inventory as live

    processes = tuple(GameProcess(pid, "war3.exe", "") for pid in (43, 42, 43))
    monkeypatch.setattr(
        current_map_process,
        "probe_game_processes",
        lambda: ProcessProbeReport(processes, True),
    )
    assert live.find_war3_pids() == [42, 43]
