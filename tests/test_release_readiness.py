"""Release acceptance must cover queries and preserve the user's environment."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from gametool import acceptance_cli, acceptance_runner


def test_release_report_discloses_skipped_coverage() -> None:
    report = acceptance_runner.AcceptanceReport(
        "now",
        "Windows",
        "3.14",
        "gamexray.exe",
        (
            acceptance_runner.AcceptanceCheck(
                "map_load", acceptance_runner.AcceptanceStatus.PASS, "loaded", 1
            ),
            acceptance_runner.AcceptanceCheck(
                "real_windows_casc",
                acceptance_runner.AcceptanceStatus.SKIP,
                "no local installation",
                0,
            ),
        ),
    )
    payload = json.loads(report.to_json())
    assert payload["coverage_complete"] is False
    assert payload["skipped_checks"] == ["real_windows_casc"]


def test_release_map_check_closes_failed_input(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[bool] = []
    md = SimpleNamespace(scripts={}, close=lambda: closed.append(True))
    monkeypatch.setattr(acceptance_runner, "load_map", lambda _path: md)
    with pytest.raises(acceptance_runner.AcceptanceCheckError):
        acceptance_runner._check_map(Path("fixture.w3x"))
    assert closed == [True]


def test_release_cli_isolates_cache_and_gui_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    caller_cache = tmp_path / "user-cache"
    caller_config = tmp_path / "user-config.json"
    monkeypatch.setenv("GAMEXRAY_CACHE_DIR", str(caller_cache))
    monkeypatch.setenv("GAMEXRAY_GUI_CONFIG_PATH", str(caller_config))
    original = dict(os.environ)

    def run(_config: acceptance_runner.AcceptanceConfig):
        assert Path(os.environ["GAMEXRAY_CACHE_DIR"]) != caller_cache
        assert Path(os.environ["GAMEXRAY_GUI_CONFIG_PATH"]) != caller_config
        os.environ["GAMEXRAY_MATERIALIZE_WORKERS"] = "release-fixture"
        return acceptance_runner.AcceptanceReport(
            "now",
            "Windows",
            "3.14",
            "gamexray.exe",
            (
                acceptance_runner.AcceptanceCheck(
                    "map_load", acceptance_runner.AcceptanceStatus.PASS, "loaded", 1
                ),
            ),
        )

    monkeypatch.setattr(acceptance_cli, "run_acceptance", run)
    assert (
        acceptance_cli.run_acceptance_cli(
            ("--map", "fixture.w3x", "--output", str(tmp_path / "output"), "--no-gui")
        )
        == 0
    )
    assert dict(os.environ) == original
    assert not caller_cache.exists()
    assert not caller_config.exists()


def test_release_acceptance_exercises_all_query_modes(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    report = acceptance_runner.run_acceptance(
        acceptance_runner.AcceptanceConfig(
            map_path=root / "tests/fixtures/maps/war3net-map-script-builder.w3x",
            campaign_path=None,
            war3_dir=None,
            output_dir=tmp_path,
            repeat_count=1,
            run_gui=False,
        )
    )
    check = next(item for item in report.checks if item.name == "pack_query_workflow")
    assert check.status is acceptance_runner.AcceptanceStatus.PASS, check.detail
    from gametool.pack_query_cli import _QUERIES

    assert "calls" in _QUERIES
    assert f"modes={len(_QUERIES)};" in check.detail
    assert "export=" in check.detail
