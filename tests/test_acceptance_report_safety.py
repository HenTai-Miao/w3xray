"""Acceptance evidence never replaces the input map or an earlier report."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gametool import acceptance_cli, acceptance_runner


def _report() -> acceptance_runner.AcceptanceReport:
    return acceptance_runner.AcceptanceReport(
        "now",
        "Windows",
        "3.14",
        "gamexray.exe",
        (
            acceptance_runner.AcceptanceCheck(
                "map_load", acceptance_runner.AcceptanceStatus.PASS, "完整证据", 1
            ),
        ),
    )


def test_acceptance_report_preserves_existing_source_bytes(tmp_path: Path) -> None:
    source = tmp_path / "source.w3x"
    source.write_bytes(b"MPQ\x1a-original-input")
    before = source.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        acceptance_runner.write_acceptance_report(_report(), source)
    assert source.read_bytes() == before


def test_acceptance_report_creates_new_nested_report(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "报告" / "acceptance.json"
    report = _report()
    acceptance_runner.write_acceptance_report(report, target)
    assert target.read_bytes() == report.to_json().encode("utf-8")
    assert json.loads(target.read_bytes())["overall_status"] == "pass"
    assert list(target.parent.iterdir()) == [target]


def test_acceptance_cli_rejects_existing_report_before_running_lanes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source.w3x"
    source.write_bytes(b"MPQ\x1a-original-input")

    def unexpected(_config: acceptance_runner.AcceptanceConfig) -> None:
        pytest.fail("acceptance must not run when the report would replace the map")

    monkeypatch.setattr(acceptance_cli, "run_acceptance", unexpected)
    code = acceptance_cli.run_acceptance_cli(
        (
            "--map",
            str(source),
            "--output",
            str(tmp_path / "out"),
            "--report",
            str(source),
            "--no-gui",
        )
    )
    assert code == 2
    assert source.read_bytes() == b"MPQ\x1a-original-input"
    assert not (tmp_path / "out").exists()
    assert "新的报告文件" in capsys.readouterr().err


def test_acceptance_cli_preserves_concurrent_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "report.json"

    def run(
        _config: acceptance_runner.AcceptanceConfig,
    ) -> acceptance_runner.AcceptanceReport:
        target.write_bytes(b"another writer")
        return _report()

    monkeypatch.setattr(acceptance_cli, "run_acceptance", run)
    code = acceptance_cli.run_acceptance_cli(
        (
            "--map",
            str(tmp_path / "source.w3x"),
            "--output",
            str(tmp_path / "out"),
            "--report",
            str(target),
            "--no-gui",
        )
    )
    assert code == 2
    assert target.read_bytes() == b"another writer"


@pytest.mark.parametrize("suffix", [".", " "])
def test_acceptance_report_rejects_raw_windows_alias_before_creating_parents(
    tmp_path: Path, suffix: str
) -> None:
    parent = tmp_path / ("new" + suffix)
    with pytest.raises(ValueError):
        acceptance_runner.prepare_acceptance_report(parent / "report.json")
    assert list(tmp_path.iterdir()) == []


def test_acceptance_cli_rejects_raw_extended_slashes_before_path_normalization(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def unexpected(_config: acceptance_runner.AcceptanceConfig) -> None:
        pytest.fail("unsafe raw report path must be rejected before any lane")

    monkeypatch.setattr(acceptance_cli, "run_acceptance", unexpected)
    raw = "\\\\?\\" + str(tmp_path) + "/new/report.json"
    with pytest.raises(SystemExit) as failure:
        acceptance_cli.run_acceptance_cli(
            (
                "--map",
                str(tmp_path / "source.w3x"),
                "--output",
                str(tmp_path / "output"),
                "--report",
                raw,
                "--no-gui",
            )
        )
    assert failure.value.code == 2
    assert list(tmp_path.iterdir()) == []


def test_acceptance_cli_rejects_raw_output_before_selecting_default_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def unexpected(_config: acceptance_runner.AcceptanceConfig) -> None:
        pytest.fail("unsafe raw output must not become a default report destination")

    monkeypatch.setattr(acceptance_cli, "run_acceptance", unexpected)
    raw = "\\\\?\\" + str(tmp_path) + "/output"
    with pytest.raises(SystemExit) as failure:
        acceptance_cli.run_acceptance_cli(
            ("--map", str(tmp_path / "source.w3x"), "--output", raw, "--no-gui")
        )
    assert failure.value.code == 2
    assert list(tmp_path.iterdir()) == []
