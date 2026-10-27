"""Acceptance coverage describes only explicitly requested, executed checks."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from gametool import acceptance_cli, acceptance_runner as runner


_CORE = (
    "map_load",
    "knowledge_pack_export",
    "pack_query_workflow",
    "batch_publication",
    "repeat_load",
)
_RELEASE = (
    "windows_runtime",
    "bundled_casclib",
    "map_load",
    "campaign_switch",
    "knowledge_pack_export",
    "pack_query_workflow",
    "batch_publication",
    "repeat_load",
    "gui_tabs",
)


@pytest.fixture
def actions(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    executed: list[str] = []

    def record(name: str):
        def action(*_args: object) -> str:
            executed.append(name)
            return f"executed {name}"

        return action

    def platform_check(_required: bool) -> runner.AcceptanceCheck:
        executed.append("windows_runtime")
        return runner.AcceptanceCheck(
            "windows_runtime", runner.AcceptanceStatus.PASS, "Windows fixture", 0
        )

    monkeypatch.setattr(runner, "_platform_check", platform_check)
    for function, name in (
        ("_check_bundled_casclib", "bundled_casclib"),
        ("_check_map", "map_load"),
        ("_check_campaign", "campaign_switch"),
        ("_check_knowledge_pack", "knowledge_pack_export"),
        ("check_query_workflow", "pack_query_workflow"),
        ("check_batch_publication", "batch_publication"),
        ("_check_repeat_load", "repeat_load"),
        ("_run_gui", "gui_tabs"),
    ):
        monkeypatch.setattr(runner, function, record(name))

    def unexpected_storage(_root: str):
        pytest.fail("unrequested acceptance must not access real CASC storage")

    monkeypatch.setattr(runner, "CascLibDataSource", unexpected_storage)
    return executed


def _config(tmp_path: Path, **options: object) -> runner.AcceptanceConfig:
    config = runner.AcceptanceConfig(
        map_path=tmp_path / "fixture.w3x",
        campaign_path=tmp_path / "fixture.w3n",
        war3_dir=None,
        output_dir=tmp_path / "output",
        run_gui=True,
        require_windows=True,
    )
    return replace(config, **options)


def test_release_request_executes_all_nine_checks_without_requesting_real_casc(
    tmp_path: Path, actions: list[str]
) -> None:
    report = runner.run_acceptance(_config(tmp_path))

    assert len(report.checks) == 9
    assert tuple(check.name for check in report.checks) == _RELEASE
    assert tuple(actions) == _RELEASE
    assert all(check.status is runner.AcceptanceStatus.PASS for check in report.checks)
    payload = json.loads(report.to_json())
    assert payload["requested_checks"] == list(_RELEASE)
    assert payload["executed_checks"] == list(_RELEASE)
    assert payload["skipped_checks"] == []
    assert payload["not_requested"] == [
        {"name": "real_windows_casc", "reason": report.not_requested[0].reason}
    ]
    assert report.not_requested[0].reason
    assert payload["requested_coverage_complete"] is True
    assert payload["coverage_complete"] is True
    assert payload["coverage_scope"] == "requested"
    assert payload["real_casc_verified"] is False
    assert report.overall_status is runner.AcceptanceStatus.PASS


def test_unrequested_lanes_are_not_called_or_represented_as_skips(
    tmp_path: Path, actions: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected(*_args: object):
        pytest.fail("an unrequested lane must not execute")

    for name in (
        "_platform_check",
        "_bundled_casclib_check",
        "_campaign_check",
        "_casc_check",
        "_gui_check",
    ):
        monkeypatch.setattr(runner, name, unexpected)
    report = runner.run_acceptance(
        _config(tmp_path, campaign_path=None, run_gui=False, require_windows=False)
    )
    payload = json.loads(report.to_json())

    assert tuple(actions) == _CORE
    assert payload["requested_checks"] == list(_CORE)
    assert payload["executed_checks"] == list(_CORE)
    assert {entry["name"] for entry in payload["not_requested"]} == {
        "windows_runtime",
        "bundled_casclib",
        "campaign_switch",
        "real_windows_casc",
        "gui_tabs",
    }
    assert all(entry["reason"] for entry in payload["not_requested"])
    assert payload["skipped_checks"] == []
    assert payload["requested_coverage_complete"] is True
    assert payload["real_casc_verified"] is False


@pytest.mark.parametrize("kind", ("classic", "missing"))
def test_explicit_casc_path_is_requested_and_its_real_validation_failure_is_retained(
    tmp_path: Path, actions: list[str], monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    path = tmp_path / kind
    if kind == "classic":
        path.mkdir()
        (path / "War3.mpq").write_bytes(b"classic fixture")
    attempted: list[str] = []

    def refuse(root: str):
        attempted.append(root)
        raise OSError(f"not a readable CASC installation: {root}")

    monkeypatch.setattr(runner, "CascLibDataSource", refuse)
    report = runner.run_acceptance(_config(tmp_path, war3_dir=path))
    payload = json.loads(report.to_json())

    assert attempted == [str(path)]
    assert "real_windows_casc" in payload["requested_checks"]
    assert "real_windows_casc" in payload["executed_checks"]
    assert payload["not_requested"] == []
    check = next(item for item in report.checks if item.name == "real_windows_casc")
    assert check.status is runner.AcceptanceStatus.FAIL
    assert "not a readable CASC" in check.detail
    assert report.overall_status is runner.AcceptanceStatus.FAIL
    assert payload["requested_coverage_complete"] is False
    assert payload["coverage_complete"] is False
    assert payload["real_casc_verified"] is False
    assert tuple(actions) == _RELEASE


@pytest.mark.parametrize("another_failure", (False, True))
def test_real_casc_verified_requires_its_own_successful_execution(
    tmp_path: Path,
    actions: list[str],
    monkeypatch: pytest.MonkeyPatch,
    another_failure: bool,
) -> None:
    monkeypatch.setattr(runner, "_check_casc", lambda _root: "real CASC read fixture")
    if another_failure:

        def failed_map(_root: Path) -> str:
            raise OSError("map fixture failure")

        monkeypatch.setattr(runner, "_check_map", failed_map)
    report = runner.run_acceptance(_config(tmp_path, war3_dir=tmp_path / "casc"))
    payload = json.loads(report.to_json())

    assert payload["real_casc_verified"] is True
    assert payload["not_requested"] == []
    assert payload["requested_coverage_complete"] is (not another_failure)


@pytest.mark.parametrize(
    ("requested", "rows", "unrequested", "complete"),
    (
        ((), (), (), False),
        (("map_load",), (), (), False),
        (("map_load", "gui_tabs"), (("map_load", "pass"),), (), False),
        (("map_load",), (("map_load", "pass"), ("gui_tabs", "pass")), (), False),
        (("map_load", "map_load"), (("map_load", "pass"),), (), False),
        (("map_load",), (("map_load", "pass"), ("map_load", "pass")), (), False),
        (("map_load",), (("map_load", "skip"),), (), False),
        (("map_load",), (("map_load", "fail"),), (), False),
        (("map_load",), (("map_load", "pass"),), ("map_load",), False),
        (("map_load",), (("map_load", "pass"),), ("gui_tabs", "gui_tabs"), False),
        ((), (("map_load", "pass"),), (), False),
        (("map_load",), (("map_load", "pass"),), (), True),
        (None, (("map_load", "skip"),), (), False),
        (None, (("map_load", "pass"),), (), True),
    ),
)
def test_requested_coverage_requires_a_nonempty_consistent_successful_plan(
    requested: tuple[str, ...] | None,
    rows: tuple[tuple[str, str], ...],
    unrequested: tuple[str, ...],
    complete: bool,
) -> None:
    checks = tuple(
        runner.AcceptanceCheck(name, runner.AcceptanceStatus(status), "fixture", 0)
        for name, status in rows
    )
    report = runner.AcceptanceReport(
        "now",
        "Windows",
        "3.14",
        "gamexray.exe",
        checks,
        requested_checks=requested,
        not_requested=tuple(
            runner.AcceptanceNotRequested(name, "not configured")
            for name in unrequested
        ),
    )
    payload = json.loads(report.to_json())

    assert report.requested_coverage_complete is complete
    assert payload["coverage_complete"] is complete
    assert payload["requested_coverage_complete"] is complete
    assert payload["coverage_scope"] == "requested"
    assert payload["real_casc_verified"] is False
    assert report.overall_status is (
        runner.AcceptanceStatus.PASS if complete else runner.AcceptanceStatus.FAIL
    )
    assert [entry["status"] for entry in payload["checks"]] == [
        status for _, status in rows
    ]


@pytest.mark.parametrize("value", (None, "", " \t\r\n"))
def test_cli_missing_or_blank_environment_does_not_request_or_access_real_casc(
    tmp_path: Path,
    actions: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    value: str | None,
) -> None:
    if value is None:
        monkeypatch.delenv("GAMEXRAY_WAR3_DIR", raising=False)
    else:
        monkeypatch.setenv("GAMEXRAY_WAR3_DIR", value)
    output = tmp_path / "report"
    result = acceptance_cli.run_acceptance_cli(
        (
            "--map",
            "fixture.w3x",
            "--campaign",
            "fixture.w3n",
            "--output",
            str(output),
            "--require-windows",
            "--no-gui",
        )
    )
    payload = json.loads((output / "acceptance.json").read_text("utf-8"))

    assert result == 0
    assert payload["real_casc_verified"] is False
    assert "real_windows_casc" not in payload["requested_checks"]
    assert "real_windows_casc" not in payload["executed_checks"]
    assert payload["skipped_checks"] == []
    assert payload["requested_coverage_complete"] is True
    text = capsys.readouterr().out
    assert "real_casc_verified=false" in text
    assert "[SKIP]" not in text


@pytest.mark.parametrize("source", ("argument", "environment"))
def test_cli_nonempty_real_casc_path_retains_requested_failure_and_exit_one(
    tmp_path: Path, actions: list[str], monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    path = tmp_path / "missing-casc"
    attempted: list[str] = []

    def refuse(root: str):
        attempted.append(root)
        raise FileNotFoundError(root)

    monkeypatch.setattr(runner, "CascLibDataSource", refuse)
    monkeypatch.setenv(
        "GAMEXRAY_WAR3_DIR", str(path) if source == "environment" else "caller fallback"
    )
    output = tmp_path / "report"
    arguments = ["--map", "fixture.w3x", "--output", str(output), "--no-gui"]
    if source == "argument":
        arguments.extend(("--war3-dir", str(path)))
    assert acceptance_cli.run_acceptance_cli(tuple(arguments)) == 1
    payload = json.loads((output / "acceptance.json").read_text("utf-8"))

    assert attempted == [str(path)]
    assert "real_windows_casc" in payload["requested_checks"]
    assert "real_windows_casc" in payload["executed_checks"]
    assert all(
        entry["name"] != "real_windows_casc" for entry in payload["not_requested"]
    )
    assert payload["requested_coverage_complete"] is False
    assert payload["real_casc_verified"] is False


@pytest.mark.parametrize("argument", ("", " \t"))
def test_cli_explicit_blank_casc_path_is_input_error_instead_of_environment_fallback(
    tmp_path: Path, actions: list[str], monkeypatch: pytest.MonkeyPatch, argument: str
) -> None:
    monkeypatch.setenv("GAMEXRAY_WAR3_DIR", "caller installation")
    output = tmp_path / "never-created"
    with pytest.raises(SystemExit) as caught:
        acceptance_cli.run_acceptance_cli(
            (
                "--map",
                "fixture.w3x",
                "--output",
                str(output),
                "--war3-dir",
                argument,
                "--no-gui",
            )
        )

    assert caught.value.code == 2
    assert not actions
    assert not output.exists()
