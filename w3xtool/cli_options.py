"""Typed command-line options and the map CLI workflow."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import sys
from typing import assert_never

from .api import load_map
from .archive_diagnostics import diagnose_archive_open
from .cli_summary import iter_cli_summary_lines
from .external_listfile import read_external_listfile
from .game_config_summary import iter_game_config_summary_lines
from .gameconfig import read_game_configuration_file
from .knowledge_pack import write_knowledge_pack
from .load_context import build_map_load_context


@dataclass(frozen=True, slots=True)
class CliOptions:
    map_path: str
    listfile_path: str | None = None
    game_data_path: str | None = None
    pack_dir: str | None = None


@dataclass(frozen=True, slots=True)
class CliOptionError(ValueError):
    detail: str

    def __str__(self) -> str:
        return self.detail


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
    seen: set[str] = set()
    index = 1
    while index < len(argv):
        option = argv[index]
        if option not in {"--listfile", "--game-data", "--pack"}:
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
            case unreachable:
                assert_never(unreachable)
        index += 2
    return CliOptions(map_path, listfile_path, game_data_path, pack_dir)


def run_cli(options: CliOptions) -> int:
    """Load one map, print its summary, and optionally write a knowledge pack."""
    configure_cli_output()
    if options.map_path.lower().endswith(".wgc"):
        return _run_game_config(options.map_path)
    external_names = read_external_listfile(options.listfile_path)
    context = build_map_load_context(
        external_names=external_names,
        game_data_path=options.game_data_path,
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
        print(f"无法生成地图摘要：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    for line in summary_lines:
        print(line)
    if options.pack_dir is None:
        return 0
    try:
        count = write_knowledge_pack(
            map_data,
            options.pack_dir,
            external_names=external_names,
            game_data_path=options.game_data_path,
        )
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK - export boundary reports stable CLI failure.
        print(f"无法写入资料包：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(f"资料包: {count} 个文件 -> {options.pack_dir}")
    return 0


def configure_cli_output() -> None:
    """Keep redirected output UTF-8 while tolerating console-only characters."""
    output = sys.stdout
    if output is None:
        return
    try:
        if output.isatty():
            output.reconfigure(errors="replace")
        else:
            output.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        return


def _run_game_config(path: str) -> int:
    try:
        config = read_game_configuration_file(path)
    except (OSError, ValueError) as exc:
        print(f"无法解析游戏配置：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    for line in iter_game_config_summary_lines(path, config):
        print(line)
    return 0
