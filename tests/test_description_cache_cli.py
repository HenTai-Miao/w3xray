"""Typed CLI tests for explicit historical description-cache migration."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

import main as entrypoint
from tests.description_cache_migration_fixture import (
    write_legacy_inputs,
    write_mutated_inputs,
)
from w3xtool import description_cache_cli as cli
from w3xtool.description_cache_migration import DescriptionCacheMigrationOptions
from w3xtool.trusted_description_cache import (
    TrustedDescriptionCacheError,
    load_trusted_description_cache,
)


def test_description_cache_cli_parses_exact_required_paths() -> None:
    # Given / When
    options = cli.parse_description_cache_cli_options(
        (
            "migrate",
            "--legacy-output",
            "legacy-output",
            "--legacy-cache",
            "legacy-cache.tsv",
            "--output",
            "trusted",
        )
    )

    # Then
    assert options == DescriptionCacheMigrationOptions(
        Path("legacy-output"),
        Path("legacy-cache.tsv"),
        Path("trusted"),
    )


@pytest.mark.parametrize(
    "argv",
    (
        (),
        ("inspect",),
        ("migrate",),
        ("migrate", "--unknown", "value"),
        ("migrate", "--legacy-output"),
        ("migrate", "--legacy-output", "--output"),
        (
            "migrate",
            "--legacy-output",
            "one",
            "--legacy-output",
            "two",
            "--legacy-cache",
            "cache",
            "--output",
            "out",
        ),
        (
            "migrate",
            "--legacy-output",
            "legacy",
            "--legacy-cache",
            "cache",
            "--output",
            "out",
            "extra",
        ),
    ),
)
def test_description_cache_cli_rejects_inexact_arguments(
    argv: tuple[str, ...],
) -> None:
    # Given / When / Then
    with pytest.raises(cli.DescriptionCacheCliOptionError):
        cli.parse_description_cache_cli_options(argv)


def test_description_cache_cli_returns_two_without_traceback_for_parse_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given / When
    code = cli.run_description_cache_cli(("migrate",))

    # Then
    captured = capsys.readouterr()
    assert code == 2
    assert "参数错误" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_description_cache_cli_returns_zero_for_structurally_valid_partial_migration(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: one structurally valid candidate lacks semantic proof.
    legacy_output, legacy_cache = write_mutated_inputs(tmp_path, "readable")
    output = tmp_path / "trusted"

    # When
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

    # Then
    captured = capsys.readouterr()
    assert code == 0
    assert "接受 0" in captured.out
    assert "拒绝 1" in captured.out
    assert captured.err == ""
    assert not load_trusted_description_cache(output).cache.entries


def test_description_cache_cli_returns_two_without_traceback_for_preflight_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: the required CLI shape names nonexistent inputs.
    argv = (
        "migrate",
        "--legacy-output",
        str(tmp_path / "missing-output"),
        "--legacy-cache",
        str(tmp_path / "missing-cache.tsv"),
        "--output",
        str(tmp_path / "trusted"),
    )

    # When
    code = cli.run_description_cache_cli(argv)

    # Then
    captured = capsys.readouterr()
    assert code == 2
    assert "迁移失败" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_description_cache_cli_returns_two_for_parent_leaf_output(
    tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: valid inputs live outside a working directory whose output leaf is `..`.
    input_root = tmp_path_factory.mktemp("description-cache-cli-input")
    legacy_output, legacy_cache = write_legacy_inputs(input_root)
    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.chdir(working)

    # When
    code = cli.run_description_cache_cli(
        (
            "migrate",
            "--legacy-output",
            str(legacy_output),
            "--legacy-cache",
            str(legacy_cache),
            "--output",
            "..",
        )
    )

    # Then: path validation remains inside the typed CLI error boundary.
    captured = capsys.readouterr()
    assert code == 2
    assert "迁移失败" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_description_cache_cli_returns_two_for_unauthorized_schema1_result(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: exact CLI paths lead to a parseable but unpublished legacy result.
    legacy_output, legacy_cache = write_legacy_inputs(
        tmp_path,
        stage="failed-but-has-output",
    )
    output = tmp_path / "trusted"

    # When
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

    # Then
    captured = capsys.readouterr()
    assert code == 2
    assert "迁移失败" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""
    assert not output.exists()


def test_description_cache_cli_returns_two_for_trust_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: the owned-cache boundary refuses publication.
    monkeypatch.setattr(
        cli,
        "migrate_description_cache",
        lambda _options: (_ for _ in ()).throw(TrustedDescriptionCacheError("tamper")),
    )

    # When
    code = cli.run_description_cache_cli(
        (
            "migrate",
            "--legacy-output",
            "legacy",
            "--legacy-cache",
            "cache",
            "--output",
            "out",
        )
    )

    # Then
    captured = capsys.readouterr()
    assert code == 2
    assert "tamper" in captured.err
    assert "Traceback" not in captured.err


def test_main_dispatches_description_cache_without_starting_gui(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    legacy_output, legacy_cache = write_legacy_inputs(tmp_path)
    output = tmp_path / "trusted"
    received: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        cli,
        "run_description_cache_cli",
        lambda argv: received.append(argv) or 7,
    )
    argv = (
        "main.py",
        "description-cache",
        "migrate",
        "--legacy-output",
        str(legacy_output),
        "--legacy-cache",
        str(legacy_cache),
        "--output",
        str(output),
    )
    monkeypatch.setattr(sys, "argv", list(argv))

    # When / Then
    with pytest.raises(SystemExit) as caught:
        entrypoint.main()
    assert caught.value.code == 7
    assert received == [argv[2:]]
