"""GameXRay 游戏档案透视器入口：默认 GUI，并保留 CLI 与游戏配置模式。"""

from __future__ import annotations

import multiprocessing
import sys
from typing import NoReturn

from gametool.cli_output import configure_cli_output

__all__ = ("main", "top_level_help")


def top_level_help() -> str:
    """Describe every public dispatch mode without starting the GUI."""
    from gametool.pack_query_cli import _COMMANDS

    return (
        "GameXRay 游戏档案透视器\n"
        "用法: gamexray [命令] [参数] / python -m gametool [命令] [参数]\n"
        "  无参数                  启动图形界面\n"
        "  cli <地图>              解析地图，--pack <新目录> 导出知识包\n"
        f"  pack-query <包>…        查询知识包 ({len(_COMMANDS)} 子命令; --json 结构化输出)\n"
        "  guide <地图>            一份逐关速查报告\n"
        "  live                    运行中游戏只读探针 (--dump-objects 导出对象表)\n"
        "  current                 定位正在使用的地图\n"
        "  batch <目录>            批量导出 (schema-6; 显式指定 --output)\n"
        "  integrity               根快照/校验/retained-cache 审计\n"
        "  description-cache       显式迁移可信描述缓存\n"
        "  casc …                  CASC 客户端浏览/导出\n"
        "  save / savecodes        存档容器/存档码读取\n"
        "  wgc / gameconfig <文件>  读取游戏配置\n"
        "  acceptance              执行地图/战役/GUI 发行验收\n"
        "  --version               输出版本号\n"
        "  -h, --help              显示帮助；每个命令也接受 --help/-h\n"
        "示例: gamexray cli map.w3x --pack <新目录>\n"
        "      gamexray pack-query <包目录> item"
    )


def _command_help(command: str) -> str | None:
    """Give the closed typed parsers the same help boundary as argparse modes."""
    if command == "cli":
        from gametool.cli_options import cli_help

        return cli_help()
    if command == "pack-query":
        from gametool.pack_query_cli import pack_query_help

        return pack_query_help()
    return {
        "guide": (
            "用法: gamexray guide <地图> [--section 段落] [--refresh]\n"
            "  --section basic|commands|quests|heroes|recipes|shops|drops|loot|clues\n"
            "  --refresh                         强制重算攻略缓存\n"
            "  --minimap-marks [输出.png|点位.json]  生成带标记的小地图\n"
            "对源地图只读；战役容器通过 pack-query 查询各任务关。"
        ),
        "live": (
            "用法: gamexray live [地图] [选项]\n"
            "  --pack <包目录>                  使用已有知识包\n"
            "  --strategy auto|handle|chain|icons  选择只读策略\n"
            "  --players / --all-units           列出玩家/全部单位\n"
            "  --unit <名称|四码>                过滤单位\n"
            "  --resources <金币> <木材> | auto   校准资源\n"
            "  --nick <大厅号=名字>              指定玩家标记\n"
            "  --pid <PID>                       明确选择游戏进程\n"
            "  --test-image <截图>               离线图标匹配\n"
            "  --save-snapshot / --load-snapshot <目录>\n"
            "  --profile-json / --export-profile <JSON>\n"
            "  --dump-objects <新目录>            导出全量对象表\n"
            "  --elevated-hint                   显示提权启动参考\n"
            "未指定地图时自动定位；多进程时必须指定 --pid。"
        ),
        "current": (
            "用法: gamexray current [--root <搜索目录>] [选项]\n"
            "  --root <目录>          可重复，添加地图搜索根\n"
            "  --accept-suggestion    明确接受唯一建议候选\n"
            "  --pack <新目录>        导出已确认地图的知识包\n"
            "  --listfile <文件> / --game-data <目录> / --author-bundle <目录>\n"
            "存在多个直接候选时保留歧义并返回 3。"
        ),
        "batch": (
            "用法: gamexray batch <地图目录> --output <新目录> [选项]\n"
            "  --game-data <目录> / --description-cache <可信缓存目录>\n"
            "  --map-timeout-seconds <正数>    可选单图超时\n"
            "  --max-memory-bytes <正整数>    可选内存边界\n"
            "  --minimum-free-bytes <非负整数> 可选磁盘预留\n"
            "  --no-retry-failed              不重试之前失败的地图\n"
            "递归处理全部 .w3x/.w3m/.w3n；默认无单图超时或额外内存上限。"
        ),
        "integrity": (
            "用法: gamexray integrity <snapshot|verify|retained-cache> [选项]\n"
            "  snapshot --root LABEL=PATH [--root LABEL=PATH…] --output <报告.json>\n"
            "  verify --snapshot <报告.json>\n"
            "  retained-cache --active-root <缓存目录> --output <报告.json>\n"
            "返回 0=通过，1=发现差异，2=输入/平台/文件系统边界；"
            "需要 POSIX 目录描述符的操作在 Windows 保留证据并返回 2。"
        ),
        "description-cache": (
            "用法: gamexray description-cache migrate --legacy-output <历史输出>\n"
            "  --legacy-cache <历史缓存.tsv> --output <新可信缓存目录>\n"
            "显式迁移；历史输入只读。Windows 缺少所需 POSIX 能力时返回 2。"
        ),
        "wgc": "用法: gamexray wgc <游戏配置.wgc>\n读取配置摘要；文件错误返回 2。",
        "gameconfig": (
            "用法: gamexray gameconfig <游戏配置.wgc>\n读取配置摘要；文件错误返回 2。"
        ),
    }.get(command)


def _cli_options_error(prefix: str, exc: Exception) -> NoReturn:
    """参数错误: stderr 出 prefix+详情+--help 出路, 退出 2。"""
    print(f"{prefix}：{exc}", file=sys.stderr)
    print(
        "（带 --help/-h 重跑同命令可看用法; gamexray --help 查看全部模式）",
        file=sys.stderr,
    )
    raise SystemExit(2) from None


def main() -> None:
    """Dispatch legacy game-config, map CLI, or GUI startup modes."""
    multiprocessing.freeze_support()
    configure_cli_output()
    if len(sys.argv) >= 2 and sys.argv[1] == "--version":
        from gametool import __version__

        print("GameXRay " + __version__)
        raise SystemExit(0)
    if len(sys.argv) >= 2 and sys.argv[1] in {"--help", "-h"}:
        print(top_level_help())
        raise SystemExit(0)
    if len(sys.argv) >= 3 and any(
        argument in {"--help", "-h"} for argument in sys.argv[2:]
    ):
        help_text = _command_help(sys.argv[1])
        if help_text is not None:
            print(help_text)
            raise SystemExit(0)
    if sys.argv[1:] == ["pack-query"]:
        print(_command_help("pack-query"))
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
            _cli_options_error("批量参数错误", exc)
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
            _cli_options_error("当前地图参数错误", exc)
        raise SystemExit(run_current_map_cli(options))
    if len(sys.argv) >= 2 and sys.argv[1] in {"wgc", "gameconfig"}:
        from gametool.gameconfig import read_game_configuration_file
        from gametool.game_config_summary import iter_game_config_summary_lines
        from gametool.presentation_safety import format_user_exception, single_line_text

        if len(sys.argv) != 3 or sys.argv[2].startswith("-"):
            _cli_options_error(
                "游戏配置参数错误", ValueError("需要且仅接受一个配置文件路径")
            )
        try:
            config = read_game_configuration_file(sys.argv[2])
        except (OSError, ValueError) as exc:
            print(
                f"无法解析游戏配置：{format_user_exception(exc, paths=(sys.argv[2],))}",
                file=sys.stderr,
            )
            raise SystemExit(2) from None
        for line in iter_game_config_summary_lines(sys.argv[2], config):
            print(single_line_text(line))
        raise SystemExit(0)
    if len(sys.argv) >= 2 and sys.argv[1] == "guide":
        from gametool.guide_cli import (
            GuideCliOptionError,
            parse_guide_cli_options,
            run_guide_cli,
        )

        try:
            options = parse_guide_cli_options(tuple(sys.argv[2:]))
        except GuideCliOptionError as exc:
            _cli_options_error("攻略参数错误", exc)
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
            _cli_options_error("实时读取参数错误", exc)
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
            _cli_options_error("资料包查询参数错误", exc)
        raise SystemExit(run_pack_query_cli(options))
    if len(sys.argv) >= 2 and sys.argv[1] == "cli":
        from gametool.cli_options import CliOptionError, parse_cli_options, run_cli

        try:
            options = parse_cli_options(tuple(sys.argv[2:]))
        except CliOptionError as exc:
            _cli_options_error("CLI 参数错误", exc)
        raise SystemExit(run_cli(options))
    # 未知子命令: 不静默弹 GUI (脚本打错字会挂死在窗口上) — 给指引后退出 2
    if sys.argv[1:]:
        print(
            f"未知子命令或选项: {sys.argv[1]} — 运行 gamexray --help 查看全部模式",
            file=sys.stderr,
        )
        raise SystemExit(2)
    try:
        from gametool.single_instance import ensure_single_instance

        ensure_single_instance()
        from gametool.gui import main as gui_main

        gui_main()
    except Exception as exc:  # BROAD_EXCEPT_OK - GUI startup needs visible failure.
        import traceback

        traceback.print_exc()
        if sys.platform == "win32":
            import ctypes

            _ = ctypes.windll.user32.MessageBoxW(
                None,
                f"GameXRay 未能启动：{type(exc).__name__}: {exc}\n"
                "请从终端运行 gamexray 以查看完整错误。",
                "GameXRay 启动失败",
                0x10,
            )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
