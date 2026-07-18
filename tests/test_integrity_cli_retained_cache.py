"""Retained-cache integrity CLI output and exit-code contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.retained_integrity_fixture import (
    active_cache,
    install_previous,
    retained,
    stage,
)
from w3xtool import description_cache_retained_integrity as retained_api
from w3xtool import description_cache_retained_set_scan as set_api
from w3xtool.description_cache_retained_integrity_models import SiblingState
from w3xtool.integrity_cli import run_integrity_cli


def _argv(active: Path, output: Path) -> tuple[str, ...]:
    return (
        "retained-cache",
        "--active-root",
        str(active),
        "--output",
        str(output),
    )


def test_retained_cache_cli_returns_zero_and_writes_ordinary_evidence(
    tmp_path: Path,
) -> None:
    active = active_cache(tmp_path)
    install_previous(active, tmp_path)
    failed = retained(active, "2", "failed-stage")
    failed.mkdir()
    (failed / "partial").write_bytes(b"evidence")
    output = tmp_path / "report.json"

    code = run_integrity_cli(_argv(active, output))

    assert code == 0
    assert output.is_file()
    assert '"valid-cache"' in output.read_text(encoding="utf-8")
    assert '"partial-evidence"' in output.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "violation", ["invalid", "unsafe", "oversized", "transient", "malformed"]
)
def test_retained_cache_cli_returns_one_and_writes_artifact_violations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    violation: str,
) -> None:
    active = active_cache(tmp_path)
    if violation == "invalid":
        previous = install_previous(active, tmp_path)
        (previous / "来源清单.tsv").unlink()
    elif violation == "unsafe":
        retained(active, "2", "recovery").symlink_to(tmp_path / "outside")
    elif violation == "oversized":
        monkeypatch.setattr(retained_api, "MAX_RETAINED_FILE_BYTES", 2)
        artifact = retained(active, "2", "failed-output")
        artifact.write_bytes(b"big")
    elif violation == "transient":
        stage(active, "2").mkdir()
    else:
        (active.parent / ".w3xray-description-cache-retained-bad").mkdir()
    output = tmp_path / f"{violation}.json"

    code = run_integrity_cli(_argv(active, output))

    assert code == 1
    assert output.is_file()


def test_retained_cache_cli_returns_two_for_request_and_root_boundaries(
    tmp_path: Path,
) -> None:
    active = active_cache(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(active, target_is_directory=True)

    assert run_integrity_cli(("retained-cache",)) == 2
    assert run_integrity_cli(_argv(alias, tmp_path / "alias.json")) == 2


@pytest.mark.parametrize("replacement", ["active", "previous"])
def test_retained_cache_cli_rejects_top_level_replacement_without_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
) -> None:
    active = active_cache(tmp_path)
    previous = install_previous(active, tmp_path)
    output = tmp_path / f"{replacement}.json"
    original = set_api.capture_relevant_siblings
    calls = 0

    def replace_before_recapture(
        parent_descriptor: int,
        active_name: str,
    ) -> tuple[SiblingState, ...]:
        nonlocal calls
        calls += 1
        if calls == 2:
            target = active if replacement == "active" else previous
            target.rename(tmp_path / f"moved-{replacement}")
            target.mkdir()
        return original(parent_descriptor, active_name)

    monkeypatch.setattr(set_api, "capture_relevant_siblings", replace_before_recapture)

    code = run_integrity_cli(_argv(active, output))

    assert code == 2
    assert not output.exists()


@pytest.mark.parametrize("inside", ["active", "retained"])
def test_retained_cache_cli_rejects_output_inside_an_artifact(
    tmp_path: Path,
    inside: str,
) -> None:
    active = active_cache(tmp_path)
    artifact = retained(active, "2", "failed-stage")
    artifact.mkdir()
    output = (active if inside == "active" else artifact) / "report.json"

    code = run_integrity_cli(_argv(active, output))

    assert code == 2
    assert not output.exists()


def test_retained_cache_cli_returns_two_when_report_write_fails(
    tmp_path: Path,
) -> None:
    active = active_cache(tmp_path)
    output = tmp_path / "existing-directory"
    output.mkdir()

    assert run_integrity_cli(_argv(active, output)) == 2
