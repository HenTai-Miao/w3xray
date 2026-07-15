"""Typed command-line boundary for resumable batch map extraction."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
import math
import signal
import threading
from types import FrameType
from typing import assert_never, override

from .batch_configuration import (
    DEFAULT_MAP_TIMEOUT_SECONDS,
    DEFAULT_MINIMUM_FREE_BYTES,
)
from .batch_models import MapBatchState
from .batch_runtime import BatchProgress
from .batch_runner import (
    DEFAULT_BATCH_OUTPUT,
    BatchConfigurationError,
    BatchOptions,
    BatchOutputError,
    run_batch,
)
from .presentation_safety import single_line_text


class _ValueOption(StrEnum):
    OUTPUT = "--output"
    GAME_DATA = "--game-data"
    MAP_TIMEOUT = "--map-timeout-seconds"
    MAX_MEMORY = "--max-memory-bytes"
    MINIMUM_FREE = "--minimum-free-bytes"


@dataclass(frozen=True, slots=True)
class BatchCliOptions:
    source_directory: str
    output_root: str = DEFAULT_BATCH_OUTPUT
    game_data_path: str | None = None
    retry_failed: bool = True
    map_timeout_seconds: float = DEFAULT_MAP_TIMEOUT_SECONDS
    max_memory_bytes: int | None = None
    minimum_free_bytes: int = DEFAULT_MINIMUM_FREE_BYTES

    def to_batch_options(self) -> BatchOptions:
        return BatchOptions(
            source_directory=self.source_directory,
            output_root=self.output_root,
            game_data_path=self.game_data_path,
            retry_failed=self.retry_failed,
            map_timeout_seconds=self.map_timeout_seconds,
            max_memory_bytes=self.max_memory_bytes,
            minimum_free_bytes=self.minimum_free_bytes,
        )


@dataclass(frozen=True, slots=True)
class BatchCliOptionError(ValueError):
    detail: str

    @override
    def __str__(self) -> str:
        return single_line_text(self.detail)


def parse_batch_cli_options(argv: Sequence[str]) -> BatchCliOptions:
    """Parse arguments following the `batch` subcommand."""
    if not argv:
        raise BatchCliOptionError("缺少地图目录")
    source_directory = argv[0]
    if source_directory.startswith("--"):
        raise BatchCliOptionError(f"缺少地图目录：{source_directory}")
    output_root = DEFAULT_BATCH_OUTPUT
    game_data_path: str | None = None
    retry_failed = True
    map_timeout_seconds = DEFAULT_MAP_TIMEOUT_SECONDS
    max_memory_bytes: int | None = None
    minimum_free_bytes = DEFAULT_MINIMUM_FREE_BYTES
    seen: set[str] = set()
    index = 1
    while index < len(argv):
        option = argv[index]
        if option not in {
            "--output",
            "--game-data",
            "--no-retry-failed",
            "--map-timeout-seconds",
            "--max-memory-bytes",
            "--minimum-free-bytes",
        }:
            raise BatchCliOptionError(f"不支持的参数：{option}")
        if option in seen:
            raise BatchCliOptionError(f"参数不能重复：{option}")
        seen.add(option)
        if option == "--no-retry-failed":
            retry_failed = False
            index += 1
            continue
        value_index = index + 1
        if (
            value_index >= len(argv)
            or not argv[value_index]
            or argv[value_index].startswith("--")
        ):
            raise BatchCliOptionError(f"参数缺少路径值：{option}")
        value = argv[value_index]
        match _ValueOption(option):
            case _ValueOption.OUTPUT:
                output_root = value
            case _ValueOption.GAME_DATA:
                game_data_path = value
            case _ValueOption.MAP_TIMEOUT:
                try:
                    parsed_timeout = float(value)
                except ValueError as exc:
                    raise BatchCliOptionError(f"参数必须是正数：{option}") from exc
                if not math.isfinite(parsed_timeout) or parsed_timeout <= 0:
                    raise BatchCliOptionError(f"参数必须是正数：{option}")
                map_timeout_seconds = parsed_timeout
            case _ValueOption.MAX_MEMORY:
                try:
                    parsed_memory = int(value)
                except ValueError as exc:
                    raise BatchCliOptionError(f"参数必须是正整数：{option}") from exc
                if parsed_memory <= 0:
                    raise BatchCliOptionError(f"参数必须是正整数：{option}")
                max_memory_bytes = parsed_memory
            case _ValueOption.MINIMUM_FREE:
                try:
                    parsed_free = int(value)
                except ValueError as exc:
                    raise BatchCliOptionError(f"参数必须是非负整数：{option}") from exc
                if parsed_free < 0:
                    raise BatchCliOptionError(f"参数必须是非负整数：{option}")
                minimum_free_bytes = parsed_free
            case unreachable:
                assert_never(unreachable)
        index += 2
    return BatchCliOptions(
        source_directory,
        output_root,
        game_data_path,
        retry_failed,
        map_timeout_seconds,
        max_memory_bytes,
        minimum_free_bytes,
    )


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
    failed = sum(result.state is MapBatchState.FAILED for result in state.results)
    cancelled = sum(result.state is MapBatchState.CANCELLED for result in state.results)
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
