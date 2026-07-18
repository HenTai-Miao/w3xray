"""Closed typed option parser for the batch command."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
import math
from typing import assert_never, override

from .batch_configuration import (
    DEFAULT_BATCH_OUTPUT,
    DEFAULT_MAP_TIMEOUT_SECONDS,
    DEFAULT_MINIMUM_FREE_BYTES,
    BatchOptions,
)
from .presentation_safety import single_line_text


class _ValueOption(StrEnum):
    OUTPUT = "--output"
    GAME_DATA = "--game-data"
    MAP_TIMEOUT = "--map-timeout-seconds"
    MAX_MEMORY = "--max-memory-bytes"
    MINIMUM_FREE = "--minimum-free-bytes"
    DESCRIPTION_CACHE = "--description-cache"


@dataclass(frozen=True, slots=True)
class BatchCliOptions:
    source_directory: str
    output_root: str = DEFAULT_BATCH_OUTPUT
    game_data_path: str | None = None
    retry_failed: bool = True
    map_timeout_seconds: float = DEFAULT_MAP_TIMEOUT_SECONDS
    max_memory_bytes: int | None = None
    minimum_free_bytes: int = DEFAULT_MINIMUM_FREE_BYTES
    description_cache_path: str | None = None

    def to_batch_options(self) -> BatchOptions:
        return BatchOptions(
            source_directory=self.source_directory,
            output_root=self.output_root,
            game_data_path=self.game_data_path,
            retry_failed=self.retry_failed,
            map_timeout_seconds=self.map_timeout_seconds,
            max_memory_bytes=self.max_memory_bytes,
            minimum_free_bytes=self.minimum_free_bytes,
            description_cache_path=self.description_cache_path,
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
    values = _BatchCliValues()
    seen: set[str] = set()
    index = 1
    while index < len(argv):
        option = argv[index]
        if option == "--no-retry-failed":
            if option in seen:
                raise BatchCliOptionError(f"参数不能重复：{option}")
            seen.add(option)
            values = replace(values, retry_failed=False)
            index += 1
            continue
        try:
            parsed_option = _ValueOption(option)
        except ValueError as exc:
            raise BatchCliOptionError(f"不支持的参数：{option}") from exc
        if option in seen:
            raise BatchCliOptionError(f"参数不能重复：{option}")
        seen.add(option)
        value_index = index + 1
        if (
            value_index >= len(argv)
            or not argv[value_index]
            or argv[value_index].startswith("--")
        ):
            raise BatchCliOptionError(f"参数缺少路径值：{option}")
        values = _apply_value(values, parsed_option, argv[value_index])
        index += 2
    return values.build(source_directory)


@dataclass(frozen=True, slots=True)
class _BatchCliValues:
    """Immutable values accumulated by one parse operation."""

    output_root: str = DEFAULT_BATCH_OUTPUT
    game_data_path: str | None = None
    retry_failed: bool = True
    map_timeout_seconds: float = DEFAULT_MAP_TIMEOUT_SECONDS
    max_memory_bytes: int | None = None
    minimum_free_bytes: int = DEFAULT_MINIMUM_FREE_BYTES
    description_cache_path: str | None = None

    def build(self, source_directory: str) -> BatchCliOptions:
        return BatchCliOptions(
            source_directory,
            self.output_root,
            self.game_data_path,
            self.retry_failed,
            self.map_timeout_seconds,
            self.max_memory_bytes,
            self.minimum_free_bytes,
            self.description_cache_path,
        )


def _apply_value(
    values: _BatchCliValues,
    option: _ValueOption,
    value: str,
) -> _BatchCliValues:
    match option:
        case _ValueOption.OUTPUT:
            return replace(values, output_root=value)
        case _ValueOption.GAME_DATA:
            return replace(values, game_data_path=value)
        case _ValueOption.MAP_TIMEOUT:
            try:
                parsed_timeout = float(value)
            except ValueError as exc:
                raise BatchCliOptionError(f"参数必须是正数：{option}") from exc
            if not math.isfinite(parsed_timeout) or parsed_timeout <= 0:
                raise BatchCliOptionError(f"参数必须是正数：{option}")
            return replace(values, map_timeout_seconds=parsed_timeout)
        case _ValueOption.MAX_MEMORY:
            return replace(
                values,
                max_memory_bytes=_bounded_integer(
                    value,
                    option,
                    minimum=1,
                    label="正整数",
                ),
            )
        case _ValueOption.MINIMUM_FREE:
            return replace(
                values,
                minimum_free_bytes=_bounded_integer(
                    value,
                    option,
                    minimum=0,
                    label="非负整数",
                ),
            )
        case _ValueOption.DESCRIPTION_CACHE:
            return replace(values, description_cache_path=value)
        case unreachable:
            assert_never(unreachable)


def _bounded_integer(
    value: str,
    option: _ValueOption,
    *,
    minimum: int,
    label: str,
) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise BatchCliOptionError(f"参数必须是{label}：{option}") from exc
    if parsed < minimum:
        raise BatchCliOptionError(f"参数必须是{label}：{option}")
    return parsed


__all__ = ("BatchCliOptionError", "BatchCliOptions", "parse_batch_cli_options")
