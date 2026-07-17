"""Typed CLI boundary for explicit trusted description-cache migration."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
import sys
from typing import Final, assert_never

from .description_cache_migration import (
    DescriptionCacheMigrationOptions,
    migrate_description_cache,
)
from .description_cache_publication_errors import DescriptionCachePublicationError
from .presentation_safety import format_user_exception, single_line_text


_ACTION: Final = "migrate"
_PATH_OPTIONS: Final = (
    "--legacy-output",
    "--legacy-cache",
    "--output",
)


class DescriptionCacheCliOptionError(ValueError):
    """The description-cache command shape is incomplete or ambiguous."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    def __str__(self) -> str:
        return single_line_text(self.detail)


def parse_description_cache_cli_options(
    argv: Sequence[str],
) -> DescriptionCacheMigrationOptions:
    """Parse exactly `migrate` and its three required path options."""
    if not argv:
        raise DescriptionCacheCliOptionError("缺少操作：migrate")
    if argv[0] != _ACTION:
        raise DescriptionCacheCliOptionError(f"不支持的操作：{argv[0]}")
    values: dict[str, str] = {}
    index = 1
    while index < len(argv):
        option = argv[index]
        if option not in _PATH_OPTIONS:
            raise DescriptionCacheCliOptionError(f"不支持的参数：{option}")
        if option in values:
            raise DescriptionCacheCliOptionError(f"参数不能重复：{option}")
        value_index = index + 1
        if (
            value_index >= len(argv)
            or not argv[value_index]
            or argv[value_index].startswith("--")
        ):
            raise DescriptionCacheCliOptionError(f"参数缺少路径值：{option}")
        values[option] = argv[value_index]
        index += 2
    missing = tuple(option for option in _PATH_OPTIONS if option not in values)
    if missing:
        raise DescriptionCacheCliOptionError(f"缺少必需参数：{', '.join(missing)}")
    return DescriptionCacheMigrationOptions(
        Path(values["--legacy-output"]),
        Path(values["--legacy-cache"]),
        Path(values["--output"]),
    )


def run_description_cache_cli(argv: tuple[str, ...]) -> int:
    """Parse, migrate, and map expected boundary failures to exit code 2."""
    try:
        options = parse_description_cache_cli_options(argv)
    except DescriptionCacheCliOptionError as exc:
        print(f"描述缓存参数错误：{exc}", file=sys.stderr)
        return 2
    try:
        result = migrate_description_cache(options)
    except DescriptionCachePublicationError as exc:
        detail = format_user_exception(
            exc,
            paths=(
                str(options.legacy_output),
                str(options.legacy_cache),
                str(options.output),
            ),
        )
        print(f"可信描述缓存迁移失败：{detail}", file=sys.stderr)
        for retained in exc.retained:
            print(
                single_line_text(f"保留对象：{retained.role.value} -> {retained.path}"),
                file=sys.stderr,
            )
        for transient in exc.transient:
            match transient.identity:
                case None:
                    object_identity_text = "unknown"
                case (device, inode):
                    object_identity_text = f"{device}:{inode}"
                case unreachable:
                    assert_never(unreachable)
            match transient.held_identity:
                case None:
                    held_identity_text = "unknown"
                case (device, inode):
                    held_identity_text = f"{device}:{inode}"
                case unreachable:
                    assert_never(unreachable)
            print(
                single_line_text(
                    "瞬态对象："
                    f"display-parent={transient.parent} "
                    f"parent={transient.parent_identity[0]}:"
                    f"{transient.parent_identity[1]} "
                    f"leaf={transient.leaf_name} object={object_identity_text} "
                    f"held={held_identity_text}"
                ),
                file=sys.stderr,
            )
        return 2
    except OSError as exc:
        detail = format_user_exception(
            exc,
            paths=(
                str(options.legacy_output),
                str(options.legacy_cache),
                str(options.output),
            ),
        )
        print(f"可信描述缓存迁移失败：{detail}", file=sys.stderr)
        return 2
    print(
        single_line_text(
            f"可信描述缓存迁移完成：接受 {result.accepted_count}，"
            f"拒绝 {result.rejected_count} -> {options.output}"
        )
    )
    for retained in result.retained:
        print(single_line_text(f"保留对象：{retained.role.value} -> {retained.path}"))
    return 0


__all__ = (
    "DescriptionCacheCliOptionError",
    "parse_description_cache_cli_options",
    "run_description_cache_cli",
)
