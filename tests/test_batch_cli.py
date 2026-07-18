"""Batch command parsing, exit status, and main dispatch tests."""

from __future__ import annotations

from dataclasses import replace
import signal
import sys
from typing import assert_never

import pytest

import main as entrypoint
import w3xtool.batch_cli as batch_cli
from w3xtool.batch_models import (
    BATCH_SCHEMA_VERSION,
    BatchState,
    MapBatchResult,
    MapBatchState,
    SourceFingerprint,
)
from w3xtool.batch_runner import DEFAULT_BATCH_OUTPUT, BatchOptions
from w3xtool.batch_runtime import BatchAction, BatchProgress
from w3xtool.batch_status import PublicationResult, derive_batch_axes


def _result(state: MapBatchState) -> MapBatchResult:
    match state:
        case MapBatchState.COMPLETE:
            publication, raw_blocks, restricted_blocks = (
                PublicationResult.PUBLISHED,
                0,
                0,
            )
        case MapBatchState.PARTIAL:
            publication, raw_blocks, restricted_blocks = (
                PublicationResult.PUBLISHED,
                1,
                0,
            )
        case MapBatchState.RESTRICTED:
            publication, raw_blocks, restricted_blocks = (
                PublicationResult.PUBLISHED,
                0,
                1,
            )
        case MapBatchState.FAILED:
            publication, raw_blocks, restricted_blocks = (
                PublicationResult.FAILED,
                0,
                0,
            )
        case MapBatchState.CANCELLED:
            publication, raw_blocks, restricted_blocks = (
                PublicationResult.CANCELLED,
                0,
                0,
            )
        case unreachable:
            assert_never(unreachable)
    terminal = publication is not PublicationResult.PUBLISHED
    axes = derive_batch_axes(
        publication,
        raw_blocks=raw_blocks,
        damaged_blocks=0,
        restricted_blocks=restricted_blocks,
        icon_gaps=0,
        current_text_states=(),
        relation_partial_count=0,
        unresolved_endpoint_count=0,
    )
    return MapBatchResult(
        source=SourceFingerprint("/maps/a.w3x", 10, 20, "a" * 64),
        display_name="A",
        output_directory="" if terminal else "地图/001_A_aaaaaaaa",
        stage="load/process" if terminal else "published",
        state=state,
        first_error="broken" if terminal else "",
        object_count=1,
        description_counts=(),
        named_icon_count=1,
        anonymous_icon_count=0,
        original_written_count=1,
        png_written_count=1,
        icon_failure_count=0,
        restricted_block_count=restricted_blocks,
        elapsed_ms=1,
        publication_result=axes.publication,
        archive_integrity=axes.archive,
        knowledge_evidence=axes.knowledge,
        knowledge_gap_reasons=axes.knowledge_reasons,
        raw_block_count=raw_blocks,
        damaged_block_count=0,
        valid_icon_reference_count=0,
        resolved_icon_reference_count=0,
        filtered_icon_field_count=0,
        unresolved_icon_count=0,
        unresolved_icon_reference_count=0,
        anonymous_read_failure_count=0,
        original_write_failure_count=0,
        png_failure_count=0,
    )


def test_parse_batch_cli_uses_documented_default_output() -> None:
    # Given / When
    options = batch_cli.parse_batch_cli_options(("/maps",))

    # Then
    assert options.source_directory == "/maps"
    assert options.output_root == DEFAULT_BATCH_OUTPUT
    assert options.game_data_path is None
    assert options.retry_failed
    assert options.map_timeout_seconds > 0
    assert options.max_memory_bytes is None
    assert options.minimum_free_bytes > 0


def test_parse_batch_cli_accepts_paths_and_retry_policy() -> None:
    # Given
    argv = ("Maps", "--output", "out", "--game-data", "Warcraft", "--no-retry-failed")

    # When
    options = batch_cli.parse_batch_cli_options(argv)

    # Then
    assert options == batch_cli.BatchCliOptions("Maps", "out", "Warcraft", False)


def test_parse_batch_cli_accepts_resource_limits() -> None:
    # Given
    argv = (
        "Maps",
        "--map-timeout-seconds",
        "12.5",
        "--max-memory-bytes",
        "1048576",
        "--minimum-free-bytes",
        "4096",
    )

    # When
    options = batch_cli.parse_batch_cli_options(argv)

    # Then
    assert options.map_timeout_seconds == 12.5
    assert options.max_memory_bytes == 1_048_576
    assert options.minimum_free_bytes == 4_096
    batch_options = options.to_batch_options()
    assert batch_options.map_timeout_seconds == 12.5
    assert batch_options.max_memory_bytes == 1_048_576
    assert batch_options.minimum_free_bytes == 4_096


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
        ("Maps", "--map-timeout-seconds", "0"),
        ("Maps", "--map-timeout-seconds", "never"),
        ("Maps", "--max-memory-bytes", "-1"),
        ("Maps", "--minimum-free-bytes", "-1"),
    ),
)
def test_parse_batch_cli_rejects_missing_unknown_and_duplicate_arguments(
    argv: tuple[str, ...],
) -> None:
    # Given / When / Then
    with pytest.raises(batch_cli.BatchCliOptionError):
        batch_cli.parse_batch_cli_options(argv)


def test_direct_batch_options_disable_isolation_by_default() -> None:
    options = BatchOptions("Maps")

    assert options.map_timeout_seconds is None


def test_run_batch_cli_returns_one_only_when_a_map_failed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    state = BatchState(
        BATCH_SCHEMA_VERSION,
        (_result(MapBatchState.COMPLETE), _result(MapBatchState.FAILED)),
    )
    monkeypatch.setattr(batch_cli, "run_batch", lambda _options, **_kwargs: state)

    # When
    code = batch_cli.run_batch_cli(batch_cli.BatchCliOptions("Maps"))

    # Then
    assert code == 1
    output = capsys.readouterr().out
    assert "完成：1/2" in output
    assert "失败：1" in output


def test_run_batch_cli_uses_authoritative_publication_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: the compatibility state is not the publication authority.
    failed = replace(_result(MapBatchState.FAILED), state=MapBatchState.PARTIAL)
    monkeypatch.setattr(
        batch_cli,
        "run_batch",
        lambda _options, **_kwargs: BatchState(BATCH_SCHEMA_VERSION, (failed,)),
    )

    # When
    code = batch_cli.run_batch_cli(batch_cli.BatchCliOptions("Maps"))

    # Then
    assert code == 1
    assert "失败：1" in capsys.readouterr().out


def test_first_sigint_requests_graceful_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    installed: dict[int, signal.Handlers] = {}
    monkeypatch.setattr(batch_cli.signal, "getsignal", lambda _signal: signal.SIG_DFL)
    monkeypatch.setattr(
        batch_cli.signal,
        "signal",
        lambda number, handler: installed.__setitem__(number, handler),
    )

    def cancel_run(_options, *, cancellation, on_progress) -> BatchState:
        _ = on_progress
        handler = installed[signal.SIGINT]
        assert callable(handler)
        handler(signal.SIGINT, None)
        assert cancellation.is_set()
        return BatchState(BATCH_SCHEMA_VERSION, (_result(MapBatchState.CANCELLED),))

    monkeypatch.setattr(batch_cli, "run_batch", cancel_run)

    # When
    code = batch_cli.run_batch_cli(batch_cli.BatchCliOptions("Maps"))

    # Then
    assert code == 130
    captured = capsys.readouterr()
    assert "正在安全取消" in captured.err
    assert "完成：0/1" in captured.out
    assert "已取消：1" in captured.out
    assert installed[signal.SIGINT] == signal.SIG_DFL


def test_second_sigint_raises_immediate_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    installed: dict[int, signal.Handlers] = {}
    monkeypatch.setattr(batch_cli.signal, "getsignal", lambda _signal: signal.SIG_DFL)
    monkeypatch.setattr(
        batch_cli.signal,
        "signal",
        lambda number, handler: installed.__setitem__(number, handler),
    )

    def interrupt_run(_options, *, cancellation, on_progress) -> BatchState:
        _ = cancellation, on_progress
        handler = installed[signal.SIGINT]
        assert callable(handler)
        handler(signal.SIGINT, None)
        handler(signal.SIGINT, None)
        raise AssertionError("second signal must interrupt")

    monkeypatch.setattr(batch_cli, "run_batch", interrupt_run)

    # When
    code = batch_cli.run_batch_cli(batch_cli.BatchCliOptions("Maps"))

    # Then
    assert code == 130


def test_cli_progress_prints_counts_action_elapsed_rss_and_eta(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    def progress_run(_options, *, cancellation, on_progress) -> BatchState:
        _ = cancellation
        on_progress(
            BatchProgress(
                completed=1,
                total=2,
                source_path="/maps/a.w3x",
                action=BatchAction.PROCESSED,
                elapsed_ms=1_500,
                eta_seconds=2.5,
                peak_rss_bytes=1_048_576,
                published_bytes=2_048,
                diagnostic_code="processed",
            )
        )
        return BatchState(BATCH_SCHEMA_VERSION, (_result(MapBatchState.COMPLETE),))

    monkeypatch.setattr(batch_cli, "run_batch", progress_run)

    # When
    _ = batch_cli.run_batch_cli(batch_cli.BatchCliOptions("Maps"))

    # Then
    output = capsys.readouterr().out
    assert "1/2" in output
    assert "processed" in output
    assert "1.50s" in output
    assert "1.00 MiB" in output
    assert "ETA 2.50s" in output


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


def test_main_enables_frozen_multiprocessing_before_batch_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    events: list[str] = []
    monkeypatch.setattr(
        entrypoint.multiprocessing,
        "freeze_support",
        lambda: events.append("freeze-support"),
    )
    monkeypatch.setattr(
        batch_cli,
        "run_batch_cli",
        lambda _options: events.append("batch") or 0,
    )
    monkeypatch.setattr(sys, "argv", ["main.py", "batch", "Maps"])

    # When
    with pytest.raises(SystemExit):
        entrypoint.main()

    # Then
    assert events == ["freeze-support", "batch"]
