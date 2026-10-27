"""Only Windows distribution lanes and metadata are offered."""

from __future__ import annotations

from pathlib import Path
import tomllib


_ROOT = Path(__file__).resolve().parents[1]


def test_distribution_workflow_is_windows_only_and_runs_the_full_suite_once() -> None:
    workflows = _ROOT / ".github" / "workflows"
    assert not (workflows / "posix-package.yml").exists()
    workflow = (workflows / "windows-package.yml").read_text(encoding="utf-8")
    assert "runs-on: windows-2022" in workflow
    assert "macos-" not in workflow
    assert "ubuntu-" not in workflow
    suite = workflow.split("      - name: Run full test suite\n", maxsplit=1)[1].split(
        "      - name: ", maxsplit=1
    )[0]
    assert suite.count("uv run gamexray-test") == 1
    assert "run: uv run gamexray-test" in suite
    for weakened in (
        "--deselect",
        "--ignore",
        "--last-failed",
        "--collect-only",
        "--lf",
        " -k ",
        " -m ",
        "continue-on-error",
        "retry",
    ):
        assert weakened not in suite


def test_project_declares_only_windows_distribution_support() -> None:
    project = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    platforms = {
        value
        for value in project["project"].get("classifiers", ())
        if value.startswith("Operating System ::")
    }
    assert platforms == {"Operating System :: Microsoft :: Windows"}
