"""CLI reporting for live retained-generation evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.description_cache_publication_fixture import replacement_inputs
from tests.trusted_description_cache_fixture import published_cache
from w3xtool import description_cache_cli as cli
from w3xtool import description_cache_publication as publication
from w3xtool.trusted_description_cache import VerifiedDescriptionCache


def test_description_cache_cli_reports_retained_previous_generation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = published_cache(tmp_path / "first", raw="first")
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")

    code = cli.run_description_cache_cli(
        (
            "migrate",
            "--legacy-output",
            str(legacy_output),
            "--legacy-cache",
            str(legacy_cache),
            "--output",
            str(output),
        )
    )

    captured = capsys.readouterr()
    retained_lines = tuple(
        line for line in captured.out.splitlines() if line.startswith("保留对象：")
    )
    assert code == 0 and "接受 1" in captured.out
    assert len(retained_lines) == 1
    assert "previous" in retained_lines[0] and str(output.parent) in retained_lines[0]
    assert captured.err == ""


def test_description_cache_cli_reports_retained_failure_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "first")
    output = tmp_path / "trusted"
    original = getattr(publication, "_require_valid_at")

    def reject_installed_output(
        parent_descriptor: int,
        path: Path,
    ) -> VerifiedDescriptionCache:
        if path == output:
            raise OSError("post-publication proof failed")
        return original(parent_descriptor, path)

    monkeypatch.setattr(publication, "_require_valid_at", reject_installed_output)
    code = cli.run_description_cache_cli(
        (
            "migrate",
            "--legacy-output",
            str(legacy_output),
            "--legacy-cache",
            str(legacy_cache),
            "--output",
            str(output),
        )
    )

    captured = capsys.readouterr()
    retained_lines = tuple(
        line for line in captured.err.splitlines() if line.startswith("保留对象：")
    )
    assert code == 2 and len(retained_lines) == 1
    assert "failed-output" in retained_lines[0]
    assert str(output.parent) in retained_lines[0]
    assert captured.out == ""
