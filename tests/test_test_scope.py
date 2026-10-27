"""The supported product suite never converts unexecuted checks into passes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from gametool import dev_test
from gametool.test_scope import (
    ScopeRequestError,
    prepare_test_scope,
    verify_retired_contracts,
)

_ROOT = Path(__file__).resolve().parents[1]


def test_original_retired_function_asts_remain_complete() -> None:
    verify_retired_contracts()


def test_default_scope_never_requests_external_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GAMEXRAY_WAR3_DIR", "unrequested-install")
    request = prepare_test_scope(("-q",))
    assert request.name == "windows"
    assert request.arguments == ("-q",)
    assert request.environment == {"GAMEXRAY_TEST_SCOPE": "windows"}


@pytest.mark.parametrize("lane", ("all", "casc", "historical"))
def test_explicit_real_data_without_original_inputs_stops_before_pytest(
    lane: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in (
        "GAMEXRAY_WAR3_DIR",
        "GAMEXRAY_MAPS_ROOT",
        "GAMEXRAY_OLD_OUTPUT",
        "GAMEXRAY_NEW_OUTPUT",
    ):
        monkeypatch.delenv(name, raising=False)
    called: list[object] = []
    monkeypatch.setattr(
        dev_test.subprocess, "run", lambda *args, **kwargs: called.append(args)
    )
    assert dev_test.main(["--suite", "real-data", "--lane", lane]) == 2
    assert not called
    assert "没有执行或跳过" in capsys.readouterr().err


def test_classic_mpq_cannot_substitute_for_requested_casc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    classic = tmp_path / "classic"
    classic.mkdir()
    (classic / "war3.mpq").write_bytes(b"ordinary synthetic marker")
    with pytest.raises(ScopeRequestError, match="Classic MPQ"):
        prepare_test_scope(
            ("--suite", "real-data", "--lane", "casc", "--war3-dir", str(classic))
        )


def test_explicit_real_scope_selects_original_lane_and_copied_environment(
    tmp_path: Path,
) -> None:
    root = tmp_path / "casc"
    (root / "Data" / "data").mkdir(parents=True)
    (root / ".build.info").write_text("synthetic signature only", encoding="utf-8")
    before = dict(os.environ)
    request = prepare_test_scope(
        ("--suite", "real-data", "--lane", "casc", "--war3-dir", str(root), "-q")
    )
    assert request.name == "real-data"
    assert request.environment["GAMEXRAY_WAR3_DIR"] == str(root.resolve())
    assert request.arguments[-1].endswith(
        "real_data_acceptance" + os.sep + "test_casclib_windows_integration.py"
    )
    assert dict(os.environ) == before


def test_retired_native_suite_refuses_windows_without_skipping() -> None:
    with pytest.raises(ScopeRequestError, match="不能在 Windows 冒充"):
        prepare_test_scope(("--suite", "retired-posix"))


@pytest.mark.parametrize(
    ("body", "expected_code", "outcome"),
    (
        (
            "import pytest\ndef test_probe(): pytest.skip('new capability gap')\n",
            1,
            "skipped",
        ),
        (
            "import pytest\npytest.skip('unavailable module', allow_module_level=True)\n",
            5,
            "skipped",
        ),
        (
            "import pytest\ndef test_probe(): pytest.xfail('new unproved behavior')\n",
            1,
            "xfail/xpass",
        ),
        (
            "import pytest\n@pytest.mark.xfail(reason='stale expected failure')\ndef test_probe(): pass\n",
            1,
            "xfail/xpass",
        ),
        ("raise RuntimeError('controlled collection error')\n", 2, None),
    ),
)
def test_strict_scope_preserves_reports_and_fails_unexecuted_or_invalid_cases(
    tmp_path: Path, body: str, expected_code: int, outcome: str | None
) -> None:
    suite = tmp_path / "suite"
    suite.mkdir()
    target = suite / "test_probe.py"
    target.write_text(body, encoding="utf-8")
    config = suite / "pytest.ini"
    config.write_text("[pytest]\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-m",
            "gametool.dev_test",
            "--noconftest",
            "-q",
            "-c",
            str(config),
            "--confcutdir",
            str(suite),
            str(target),
        ],
        cwd=_ROOT,
        env=dev_test.create_test_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    assert result.returncode == expected_code, result.stdout + result.stderr
    line = next(
        line
        for line in result.stdout.splitlines()
        if line.startswith("TEST-SCOPE windows: ")
    )
    evidence = json.loads(Path(line.split(": ", 1)[1]).read_text(encoding="utf-8"))
    assert evidence["exit_code"] == expected_code
    if outcome is not None:
        assert evidence["unexpected_outcomes"][0]["outcome"] == outcome
        assert not evidence["passed_nodeids"]
    else:
        assert "controlled collection error" in result.stdout
