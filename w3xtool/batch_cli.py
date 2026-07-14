"""Typed command-line boundary for resumable batch map extraction."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import assert_never, override

from .batch_models import MapBatchState
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


@dataclass(frozen=True, slots=True)
class BatchCliOptions:
    source_directory: str
    output_root: str = DEFAULT_BATCH_OUTPUT
    game_data_path: str | None = None
    retry_failed: bool = True

    def to_batch_options(self) -> BatchOptions:
        return BatchOptions(
            source_directory=self.source_directory,
            output_root=self.output_root,
            game_data_path=self.game_data_path,
            retry_failed=self.retry_failed,
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
    seen: set[str] = set()
    index = 1
    while index < len(argv):
        option = argv[index]
        if option not in {"--output", "--game-data", "--no-retry-failed"}:
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
            case unreachable:
                assert_never(unreachable)
        index += 2
    return BatchCliOptions(source_directory, output_root, game_data_path, retry_failed)


def run_batch_cli(options: BatchCliOptions) -> int:
    """Run the batch and print one stable result line per source."""
    try:
        state = run_batch(options.to_batch_options())
    except (BatchConfigurationError, BatchOutputError) as exc:
        print(f"批量提取失败：{single_line_text(str(exc))}", file=sys.stderr)
        return 2
    for result in state.results:
        print(
            single_line_text(
                f"[{result.state.value}] {result.display_name} -> {result.output_directory or '未发布'}",
            )
        )
    failed = sum(result.state is MapBatchState.FAILED for result in state.results)
    print(f"完成：{len(state.results) - failed}/{len(state.results)}，失败：{failed}")
    return int(failed > 0)
