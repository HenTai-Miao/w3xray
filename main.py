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
    if len(sys.argv) >= 2 and sys.argv[1] == "--version":
        from gametool import __version__  # noqa: PLC0415

        print("GameXRay " + __version__)
        raise SystemExit(0)
    if len(sys.argv) >= 2 and sys.argv[1] in {"--help", "-h"}:
        print(
            "GameXRay 游戏档案透视器\n"
            "  无参数            启动图形界面\n"
            "  cli <地图>        解析地图导出知识包\n"
            "  pack-query <包>…  查询知识包 (28 子命令; --json 结构化输出)\n"
            "  guide <地图>      一份逐关速查报告\n"
            "  live              运行中游戏只读探针 (--dump-objects 导出对象表)\n"
            "  current           定位正在使用的地图\n"
            "  batch <目录>      批量导出 (schema-6)\n"
            "  integrity         根快照/校验/retained-cache 审计\n"
            "  casc …            CASC 客户端浏览/导出\n"
            "  save / savecodes  存档容器/存档码读取\n"
            "  --version         输出版本号"
        )
        raise SystemExit(0)
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
    # 未知子命令: 不静默弹 GUI (脚本打错字会挂死在窗口上) — 给指引后退出 2
    if sys.argv[1:] and not sys.argv[1].startswith("-"):
        print(
            f"未知子命令: {sys.argv[1]} — 运行 main.py --help 查看全部模式",
            file=sys.stderr,
        )
        raise SystemExit(2)
    from gametool.single_instance import ensure_single_instance

    ensure_single_instance()
    from gametool.gui import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
