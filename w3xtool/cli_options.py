"""Typed command-line options and the map CLI workflow."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import assert_never

from .api import load_map
from .archive_diagnostics import diagnose_archive_open
from .cli_output import configure_cli_output
from .cli_summary import iter_cli_summary_lines
from .external_listfile import read_external_listfile
from .game_config_summary import iter_game_config_summary_lines
from .gameconfig import read_game_configuration_file
from .knowledge_io import safe_filename
from .knowledge_pack import write_knowledge_pack_report
from .knowledge_results import KnowledgeWriteReport, KnowledgeWriteStatus
from .load_context import build_map_load_context
from .presentation_safety import format_user_exception, single_line_text


@dataclass(frozen=True, slots=True)
class CliOptions:
    map_path: str
    listfile_path: str | None = None
    game_data_path: str | None = None
    pack_dir: str | None = None
    author_bundle_path: str | None = None


@dataclass(frozen=True, slots=True)
class CliOptionError(ValueError):
    detail: str

    def __str__(self) -> str:
        return single_line_text(self.detail)


def parse_cli_options(argv: Sequence[str]) -> CliOptions:
    """Parse arguments following the `cli` subcommand."""
    if not argv:
        raise CliOptionError("缺少地图路径")
    map_path = argv[0]
    if map_path.startswith("--"):
        raise CliOptionError(f"缺少地图路径：{map_path}")
    listfile_path: str | None = None
    game_data_path: str | None = None
    pack_dir: str | None = None
    author_bundle_path: str | None = None
    seen: set[str] = set()
    index = 1
    while index < len(argv):
        option = argv[index]
        if option not in {"--listfile", "--game-data", "--pack", "--author-bundle"}:
            raise CliOptionError(f"不支持的参数：{option}")
        if option in seen:
            raise CliOptionError(f"参数不能重复：{option}")
        value_index = index + 1
        if value_index >= len(argv) or argv[value_index].startswith("--"):
            raise CliOptionError(f"参数缺少路径值：{option}")
        value = argv[value_index]
        seen.add(option)
        match option:
            case "--listfile":
                listfile_path = value
            case "--game-data":
                game_data_path = value
            case "--pack":
                pack_dir = value
            case "--author-bundle":
                author_bundle_path = value
            case unreachable:
                assert_never(unreachable)
        index += 2
    return CliOptions(map_path, listfile_path, game_data_path, pack_dir, author_bundle_path)


def run_cli(options: CliOptions) -> int:
    """Load one map, print its summary, and optionally write a knowledge pack."""
    configure_cli_output()
    if options.map_path.lower().endswith(".wgc"):
        return _run_game_config(options.map_path)
    external_names = read_external_listfile(options.listfile_path)
    context = build_map_load_context(
        external_names=external_names,
        game_data_path=options.game_data_path,
        author_bundle_path=options.author_bundle_path,
    )
    try:
        map_data = load_map(options.map_path, load_context=context)
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK - CLI boundary converts parser failures to code 2.
        diagnosis = diagnose_archive_open(options.map_path, exc)
        print(f"无法解析地图：{diagnosis.message}", file=sys.stderr)
        return 2
    try:
        summary_lines = tuple(iter_cli_summary_lines(map_data))
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK - summary boundary returns CLI code 2.
        error = format_user_exception(exc, paths=(options.map_path,))
        print(f"无法生成地图摘要：{error}", file=sys.stderr)
        return 2
    for line in summary_lines:
        print(single_line_text(line))
    if options.pack_dir is None:
        return 0
    try:
        report = _write_cli_packs(map_data, options, external_names)
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK - export boundary reports stable CLI failure.
        error = format_user_exception(
            exc,
            paths=(options.map_path, options.pack_dir or "", options.game_data_path or ""),
        )
        print(f"无法写入资料包：{error}", file=sys.stderr)
        return 2
    match report.status:
        case KnowledgeWriteStatus.COMPLETE:
            print(single_line_text(
                f"资料包: 完整，{report.written_count} 个文件 -> {options.pack_dir}",
            ))
            return 0
        case KnowledgeWriteStatus.PARTIAL:
            print(single_line_text(
                f"资料包: 部分完成，成功 {report.written_count}，"
                f"失败 {report.failed_count} -> {options.pack_dir}",
            ))
            _print_first_write_failure(report)
            return 0
        case KnowledgeWriteStatus.FAILED:
            print(
                single_line_text(
                    f"资料包写入失败，成功 {report.written_count}，"
                    f"失败 {report.failed_count} -> {options.pack_dir}",
                ),
                file=sys.stderr,
            )
            _print_first_write_failure(report)
            return 2
        case unreachable:
            assert_never(unreachable)


def _print_first_write_failure(report: KnowledgeWriteReport) -> None:
    failure = report.first_failure
    if failure is not None:
        print(
            single_line_text(f"首个失败: {failure.path}: {failure.error or '未知错误'}"),
            file=sys.stderr,
        )


def _write_cli_packs(
    map_data,
    options: CliOptions,
    external_names: Sequence[str],
) -> KnowledgeWriteReport:
    """Publish the selected map and every loaded campaign child."""
    if options.pack_dir is None:
        return KnowledgeWriteReport(())
    parent = write_knowledge_pack_report(
        map_data,
        options.pack_dir,
        external_names=external_names,
        game_data_path=options.game_data_path,
    )
    items = list(parent.items)
    for index, child in enumerate(map_data.sub_maps, start=1):
        directory = f"{index:03d}_{safe_filename(child.name)}"
        prefix = f"子地图/{directory}"
        child_report = write_knowledge_pack_report(
            child,
            os.path.join(options.pack_dir, "子地图", directory),
            external_names=external_names,
            game_data_path=options.game_data_path,
            publication_root=options.pack_dir,
        )
        items.extend(replace(item, path=f"{prefix}/{item.path}") for item in child_report.items)
    return KnowledgeWriteReport(tuple(items))


def _run_game_config(path: str) -> int:
    try:
        config = read_game_configuration_file(path)
    except (OSError, ValueError) as exc:
        print(f"无法解析游戏配置：{format_user_exception(exc, paths=(path,))}", file=sys.stderr)
        return 2
    for line in iter_game_config_summary_lines(path, config):
        print(single_line_text(line))
    return 0
