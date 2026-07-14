"""Batch command parsing, exit status, and main dispatch tests."""

from __future__ import annotations

import sys

import pytest

import main as entrypoint
import w3xtool.batch_cli as batch_cli
from w3xtool.batch_models import (
    BatchState,
    MapBatchResult,
    MapBatchState,
    SourceFingerprint,
)
from w3xtool.batch_runner import DEFAULT_BATCH_OUTPUT


def _result(state: MapBatchState) -> MapBatchResult:
    return MapBatchResult(
        source=SourceFingerprint("/maps/a.w3x", 10, 20, "a" * 64),
        display_name="A",
        output_directory="地图/001_A_aaaaaaaa",
        stage="published" if state is not MapBatchState.FAILED else "load/process",
        state=state,
        first_error="" if state is not MapBatchState.FAILED else "broken",
        object_count=1,
        description_counts=(),
        named_icon_count=1,
        anonymous_icon_count=0,
        original_written_count=1,
        png_written_count=1,
        icon_failure_count=0,
        restricted_block_count=0,
        elapsed_ms=1,
    )


def test_parse_batch_cli_uses_documented_default_output() -> None:
    # Given / When
    options = batch_cli.parse_batch_cli_options(("/maps",))

    # Then
    assert options.source_directory == "/maps"
    assert options.output_root == DEFAULT_BATCH_OUTPUT
    assert options.game_data_path is None
    assert options.retry_failed


def test_parse_batch_cli_accepts_paths_and_retry_policy() -> None:
    # Given
    argv = ("Maps", "--output", "out", "--game-data", "Warcraft", "--no-retry-failed")

    # When
    options = batch_cli.parse_batch_cli_options(argv)

    # Then
    assert options == batch_cli.BatchCliOptions("Maps", "out", "Warcraft", False)


@pytest.mark.parametrize(
    "argv",
    (
        (),
        ("--output", "out"),
        ("Maps", "extra"),
        ("Maps", "--unknown"),
        ("Maps", "--output"),
        ("Maps", "--output", "one", "--output", "two"),
        ("Maps", "--no-retry-failed", "--no-retry-failed"),
    ),
)
def test_parse_batch_cli_rejects_missing_unknown_and_duplicate_arguments(
    argv: tuple[str, ...],
) -> None:
    # Given / When / Then
    with pytest.raises(batch_cli.BatchCliOptionError):
        batch_cli.parse_batch_cli_options(argv)


def test_run_batch_cli_returns_one_only_when_a_map_failed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    state = BatchState(
        1, (_result(MapBatchState.COMPLETE), _result(MapBatchState.FAILED))
    )
    monkeypatch.setattr(batch_cli, "run_batch", lambda _options: state)

    # When
    code = batch_cli.run_batch_cli(batch_cli.BatchCliOptions("Maps"))

    # Then
    assert code == 1
    output = capsys.readouterr().out
    assert "完成：1/2" in output
    assert "失败：1" in output


def test_main_dispatches_batch_without_starting_the_gui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    received: list[batch_cli.BatchCliOptions] = []
    monkeypatch.setattr(
        batch_cli, "run_batch_cli", lambda options: received.append(options) or 7
    )
    monkeypatch.setattr(sys, "argv", ["main.py", "batch", "Maps", "--output", "out"])

    # When / Then
    with pytest.raises(SystemExit) as caught:
        entrypoint.main()
    assert caught.value.code == 7
    assert received == [batch_cli.BatchCliOptions("Maps", "out")]
