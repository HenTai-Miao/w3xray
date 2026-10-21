"""Typed command-line boundary for resumable batch map extraction."""

from __future__ import annotations

import signal
import sys
import threading
from types import FrameType

from .batch_cli_options import (
    BatchCliOptionError as BatchCliOptionError,
    BatchCliOptions,
    parse_batch_cli_options as parse_batch_cli_options,
)
from .batch_runtime import BatchProgress
from .batch_status import PublicationResult
from .batch_runner import (
    BatchConfigurationError,
    BatchOutputError,
    run_batch,
)
from .presentation_safety import single_line_text


def run_batch_cli(options: BatchCliOptions) -> int:
    """Run the batch and print one stable result line per source."""
    cancellation = threading.Event()
    interrupt_count = 0
    previous_handler = signal.getsignal(signal.SIGINT)

    def handle_interrupt(_signum: int, _frame: FrameType | None) -> None:
        nonlocal interrupt_count
        interrupt_count += 1
        if interrupt_count == 1:
            cancellation.set()
            print("正在安全取消；再次按 Ctrl-C 将立即中断。", file=sys.stderr)
            return
        raise KeyboardInterrupt

    _ = signal.signal(signal.SIGINT, handle_interrupt)
    try:
        state = run_batch(
            options.to_batch_options(),
            cancellation=cancellation,
            on_progress=_print_batch_progress,
        )
    except (BatchConfigurationError, BatchOutputError) as exc:
        print(f"批量提取失败：{single_line_text(str(exc))}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("批量提取已立即中断。", file=sys.stderr)
        return 130
    finally:
        _ = signal.signal(signal.SIGINT, previous_handler)
    for result in state.results:
        print(
            single_line_text(
                f"[{result.state.value}] {result.display_name} -> {result.output_directory or '未发布'}",
            )
        )
    failed = sum(
        result.publication_result is PublicationResult.FAILED
        for result in state.results
    )
    cancelled = sum(
        result.publication_result is PublicationResult.CANCELLED
        for result in state.results
    )
    completed = len(state.results) - failed - cancelled
    print(
        f"完成：{completed}/{len(state.results)}，失败：{failed}，已取消：{cancelled}"
    )
    if cancelled:
        return 130
    return int(failed > 0)


def _print_batch_progress(progress: BatchProgress) -> None:
    eta = "未知" if progress.eta_seconds is None else f"{progress.eta_seconds:.2f}s"
    rss_mib = progress.peak_rss_bytes / (1024 * 1024)
    print(
        single_line_text(
            f"进度 {progress.completed}/{progress.total} "
            f"{progress.action.value} "
            f"耗时 {progress.elapsed_ms / 1000:.2f}s "
            f"RSS {rss_mib:.2f} MiB ETA {eta}"
        )
    )
