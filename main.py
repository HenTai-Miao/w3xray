"""魔兽地图提取器入口：默认 GUI，并保留 CLI 与游戏配置模式。"""

from __future__ import annotations

import multiprocessing
import sys

from w3xtool.cli_options import CliOptionError, parse_cli_options, run_cli
from w3xtool.cli_output import configure_cli_output
from w3xtool.cli_summary import iter_cli_summary_lines
from w3xtool.game_config_summary import iter_game_config_summary_lines

__all__ = ("iter_cli_summary_lines", "iter_game_config_summary_lines", "main")


def main() -> None:
    """Dispatch legacy game-config, map CLI, or GUI startup modes."""
    multiprocessing.freeze_support()
    configure_cli_output()
    if len(sys.argv) >= 2 and sys.argv[1] == "description-cache":
        from w3xtool.description_cache_cli import run_description_cache_cli

        raise SystemExit(run_description_cache_cli(tuple(sys.argv[2:])))
    if len(sys.argv) >= 2 and sys.argv[1] == "batch":
        from w3xtool.batch_cli import (
            BatchCliOptionError,
            parse_batch_cli_options,
            run_batch_cli,
        )

        try:
            options = parse_batch_cli_options(tuple(sys.argv[2:]))
        except BatchCliOptionError as exc:
            print(f"批量参数错误：{exc}", file=sys.stderr)
            raise SystemExit(2) from None
        raise SystemExit(run_batch_cli(options))
    if len(sys.argv) >= 2 and sys.argv[1] == "acceptance":
        from w3xtool.acceptance_cli import run_acceptance_cli

        raise SystemExit(run_acceptance_cli(tuple(sys.argv[2:])))
    if len(sys.argv) >= 2 and sys.argv[1] == "casc":
        from w3xtool.casc_cli import run_casc_cli

        raise SystemExit(run_casc_cli(tuple(sys.argv[2:])))
    if len(sys.argv) >= 2 and sys.argv[1] == "save":
        from w3xtool.real_save_cli import run_real_save_cli

        raise SystemExit(run_real_save_cli(tuple(sys.argv[2:])))
    if len(sys.argv) >= 2 and sys.argv[1] == "current":
        from w3xtool.current_map_cli import (
            CurrentMapCliOptionError,
            parse_current_map_cli_options,
            run_current_map_cli,
        )

        try:
            options = parse_current_map_cli_options(tuple(sys.argv[2:]))
        except CurrentMapCliOptionError as exc:
            print(f"当前地图参数错误：{exc}", file=sys.stderr)
            raise SystemExit(2) from None
        raise SystemExit(run_current_map_cli(options))
    if len(sys.argv) >= 3 and sys.argv[1] in {"wgc", "gameconfig"}:
        from w3xtool.gameconfig import read_game_configuration_file

        try:
            config = read_game_configuration_file(sys.argv[2])
        except (OSError, ValueError) as exc:
            print(f"无法解析游戏配置：{type(exc).__name__}: {exc}")
            return
        for line in iter_game_config_summary_lines(sys.argv[2], config):
            print(line)
        return
    if len(sys.argv) >= 2 and sys.argv[1] == "cli":
        try:
            options = parse_cli_options(tuple(sys.argv[2:]))
        except CliOptionError as exc:
            print(f"CLI 参数错误：{exc}", file=sys.stderr)
            raise SystemExit(2) from None
        raise SystemExit(run_cli(options))
    from w3xtool.single_instance import ensure_single_instance

    ensure_single_instance()
    from w3xtool.gui import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
