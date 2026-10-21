"""GameXRay 游戏档案透视器入口：默认 GUI，并保留 CLI 与游戏配置模式。"""

from __future__ import annotations

import multiprocessing
import sys

from gametool.cli_options import CliOptionError, parse_cli_options, run_cli
from gametool.cli_output import configure_cli_output
from gametool.cli_summary import iter_cli_summary_lines
from gametool.game_config_summary import iter_game_config_summary_lines

__all__ = ("iter_cli_summary_lines", "iter_game_config_summary_lines", "main")


def main() -> None:
    """Dispatch legacy game-config, map CLI, or GUI startup modes."""
    multiprocessing.freeze_support()
    configure_cli_output()
    if len(sys.argv) >= 2 and sys.argv[1] == "integrity":
        from gametool.integrity_cli import run_integrity_cli

        raise SystemExit(run_integrity_cli(tuple(sys.argv[2:])))
    if len(sys.argv) >= 2 and sys.argv[1] == "description-cache":
        from gametool.description_cache_cli import run_description_cache_cli

        raise SystemExit(run_description_cache_cli(tuple(sys.argv[2:])))
    if len(sys.argv) >= 2 and sys.argv[1] == "batch":
        from gametool.batch_cli import (
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
        from gametool.acceptance_cli import run_acceptance_cli

        raise SystemExit(run_acceptance_cli(tuple(sys.argv[2:])))
    if len(sys.argv) >= 2 and sys.argv[1] == "casc":
        from gametool.casc_cli import run_casc_cli

        raise SystemExit(run_casc_cli(tuple(sys.argv[2:])))
    if len(sys.argv) >= 2 and sys.argv[1] == "save":
        from gametool.real_save_cli import run_real_save_cli

        raise SystemExit(run_real_save_cli(tuple(sys.argv[2:])))
    if len(sys.argv) >= 2 and sys.argv[1] == "savecodes":
        from gametool.save_code_cli import run_save_code_cli

        raise SystemExit(run_save_code_cli(tuple(sys.argv[2:])))
    if len(sys.argv) >= 2 and sys.argv[1] == "current":
        from gametool.current_map_cli import (
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
        from gametool.gameconfig import read_game_configuration_file

        try:
            config = read_game_configuration_file(sys.argv[2])
        except (OSError, ValueError) as exc:
            print(f"无法解析游戏配置：{type(exc).__name__}: {exc}")
            return
        for line in iter_game_config_summary_lines(sys.argv[2], config):
            print(line)
        return
    if len(sys.argv) >= 2 and sys.argv[1] == "guide":
        from gametool.guide_cli import (
            GuideCliOptionError,
            parse_guide_cli_options,
            run_guide_cli,
        )

        try:
            options = parse_guide_cli_options(tuple(sys.argv[2:]))
        except GuideCliOptionError as exc:
            print(f"攻略参数错误：{exc}", file=sys.stderr)
            raise SystemExit(2) from None
        raise SystemExit(run_guide_cli(options))
    if len(sys.argv) >= 2 and sys.argv[1] == "live":
        from gametool.live_cli import (
            LiveCliOptionError,
            parse_live_cli_options,
            run_live_cli,
        )

        try:
            options = parse_live_cli_options(tuple(sys.argv[2:]))
        except LiveCliOptionError as exc:
            print(f"实时读取参数错误：{exc}", file=sys.stderr)
            raise SystemExit(2) from None
        raise SystemExit(run_live_cli(options))
    if len(sys.argv) >= 2 and sys.argv[1] == "pack-query":
        from gametool.pack_query_cli import (
            PackQueryCliOptionError,
            parse_pack_query_cli_options,
            run_pack_query_cli,
        )

        try:
            options = parse_pack_query_cli_options(tuple(sys.argv[2:]))
        except PackQueryCliOptionError as exc:
            print(f"资料包查询参数错误：{exc}", file=sys.stderr)
            raise SystemExit(2) from None
        raise SystemExit(run_pack_query_cli(options))
    if len(sys.argv) >= 2 and sys.argv[1] == "cli":
        try:
            options = parse_cli_options(tuple(sys.argv[2:]))
        except CliOptionError as exc:
            print(f"CLI 参数错误：{exc}", file=sys.stderr)
            raise SystemExit(2) from None
        raise SystemExit(run_cli(options))
    from gametool.single_instance import ensure_single_instance

    ensure_single_instance()
    from gametool.gui import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
