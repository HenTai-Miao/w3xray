"""Release command boundaries must fail before probing a wrong game process."""

import builtins
from pathlib import Path

import pytest

from gametool import live_cli


@pytest.mark.parametrize("pid", ("oops", "", "0", "-1", "42.5"))
def test_invalid_explicit_pid_cannot_fall_back_to_automatic_process(pid: str) -> None:
    with pytest.raises(live_cli.LiveCliOptionError, match="pid"):
        live_cli.parse_live_cli_options(("--dump-objects", "out", "--pid", pid))


def test_programmatic_invalid_pid_fails_before_dump(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unexpected_dump(*_args):
        pytest.fail("an invalid explicit PID must never turn into automatic selection")

    monkeypatch.setattr("gametool.live_object_dump.dump_live_objects", unexpected_dump)

    status = live_cli.run_live_cli(
        live_cli.LiveCliOptions(dump_objects=str(tmp_path), pid="oops")
    )

    assert status == 2
    assert "pid" in capsys.readouterr().err


def test_dump_failure_returns_diagnostic_exit_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failed_dump(*_args):
        raise OSError("fixture snapshot failure")

    monkeypatch.setattr("gametool.live_object_dump.dump_live_objects", failed_dump)

    status = live_cli.run_live_cli(live_cli.LiveCliOptions(dump_objects=str(tmp_path)))

    assert status == 2
    assert "fixture snapshot failure" in capsys.readouterr().err


def test_missing_pack_stops_before_live_process_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.endswith("live_inventory"):
            pytest.fail(
                "a nonexistent pack must be diagnosed before loading a live probe"
            )
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    status = live_cli.run_live_cli(
        live_cli.LiveCliOptions(pack_dir=str(tmp_path / "nonexistent"))
    )

    assert status == 2
    assert "资料包" in capsys.readouterr().err
