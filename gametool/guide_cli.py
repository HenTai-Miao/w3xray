"""guide 子命令：一张地图一键输出玩家攻略骨架。

用法：
    uv run main.py guide <地图路径> [--section basic|commands|quests|heroes|recipes|shops|drops|loot|clues] [--refresh]
        [--minimap-marks [输出.png | 点位.json]]

对源地图只读；同一地图版本的重复查询走磁盘缓存（地图改动自动失效），
--refresh 强制重算。GAMEXRAY_GUIDE_CACHE=0 可整体关闭。
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from .api import load_map
from .archive_diagnostics import diagnose_archive_open
from .cli_output import configure_cli_output
from .guide_cache import load_cached_report, report_cache_path, store_cached_report
from .guide_report import GUIDE_SECTION_TITLES, format_guide_report
from .load_context import build_map_load_context
from .presentation_safety import single_line_text

__all__ = (
    "GuideCliOptionError",
    "GuideCliOptions",
    "parse_guide_cli_options",
    "run_guide_cli",
)


@dataclass(frozen=True, slots=True)
class GuideCliOptions:
    """guide 子命令的已解析参数。"""

    map_path: str
    section: str | None = None
    refresh: bool = False
    minimap_marks: str | None = None  # 请求小地图标注图; "" = 自动命名


@dataclass(frozen=True, slots=True)
class GuideCliOptionError(ValueError):
    """guide 参数错误，message 面向命令行用户。"""

    detail: str

    def __str__(self) -> str:
        return single_line_text(self.detail)


def parse_guide_cli_options(argv: Sequence[str]) -> GuideCliOptions:
    """解析 guide 后的参数：地图路径 + 可选 --section 段落键与 --refresh。"""
    if not argv or argv[0].startswith("--"):
        raise GuideCliOptionError("缺少地图路径")
    map_path = argv[0]
    section: str | None = None
    refresh = False
    minimap_marks: str | None = None
    index = 1
    while index < len(argv):
        option = argv[index]
        if option == "--refresh":
            if refresh:
                raise GuideCliOptionError("参数不能重复：--refresh")
            refresh = True
            index += 1
            continue
        if option == "--minimap-marks":
            if minimap_marks is not None:
                raise GuideCliOptionError("参数不能重复：--minimap-marks")
            value_index = index + 1
            if value_index < len(argv) and not argv[value_index].startswith("--"):
                minimap_marks = argv[value_index]
                index += 2
            else:
                minimap_marks = ""  # 请求了但未给路径 → 运行时自动命名
                index += 1
            continue
        if option != "--section":
            raise GuideCliOptionError(f"不支持的参数：{option}")
        if section is not None:
            raise GuideCliOptionError("参数不能重复：--section")
        value_index = index + 1
        if value_index >= len(argv) or argv[value_index].startswith("--"):
            raise GuideCliOptionError("参数缺少段落值：--section")
        value = argv[value_index]
        if value not in GUIDE_SECTION_TITLES:
            valid = "、".join(GUIDE_SECTION_TITLES)
            raise GuideCliOptionError(f"未知段落：{value}（可选：{valid}）")
        section = value
        index += 2
    return GuideCliOptions(map_path, section, refresh, minimap_marks)


def _print_report_lines(text: str, section: str | None, map_path: str) -> None:
    """打印报告行; 战役容器 (.w3n) 的 --section 空段给逐关指引。

    CLI 的 --section 是从完整报告文本切段 (缓存也存完整报告), 空段旧版
    什么都不印, 玩家会以为命令失效——.w3n 时输出与全量报告同一指引。"""
    lines = list(_display_lines(text, section))
    if section is not None and not lines and map_path.lower().endswith(".w3n"):
        print(
            "- 战役容器：该段在各任务关里，用 `pack-query <战役包> <命令> <词>` "
            "逐关查询（自动聚合）"
        )
        return
    for line in lines:
        print(single_line_text(line))


def run_guide_cli(options: GuideCliOptions) -> int:
    """加载地图并打印攻略速查；缓存命中时跳过解析；失败返回 2。"""
    configure_cli_output()
    # 首次分析一张大图时物化是主要开销；默认吃满可用核（用户可显式覆盖）。
    os.environ.setdefault("GAMEXRAY_MATERIALIZE_WORKERS", str(os.cpu_count() or 1))
    cache_path = report_cache_path(options.map_path)
    # --minimap-marks 需要完整 MapData (底图/对象表/w3i), 有它就不走缓存早退。
    if not options.refresh and options.minimap_marks is None:
        cached = load_cached_report(cache_path)
        if cached is not None:
            print("（命中攻略缓存；--refresh 强制重算）", file=sys.stderr)
            _print_report_lines(cached, options.section, options.map_path)
            return 0
    context = build_map_load_context()
    try:
        map_data = load_map(options.map_path, load_context=context)
    except Exception as exc:
        diagnosis = diagnose_archive_open(options.map_path, exc)
        print(f"无法解析地图：{diagnosis.message}", file=sys.stderr)
        return 2
    # 缓存永远存完整报告，避免 --section 查询把残缺结果留给后续全量查询。
    full_report = format_guide_report(map_data, None)
    store_cached_report(cache_path, full_report)
    _print_report_lines(full_report, options.section, options.map_path)
    if options.minimap_marks is not None:
        requested = options.minimap_marks
        stem = os.path.splitext(os.path.basename(options.map_path))[0]
        extra_json: str | None = None
        if requested.lower().endswith(".json"):
            extra_json = requested
            out_path = stem + "-minimap.png"
        elif requested:
            out_path = requested
        else:
            out_path = stem + "-minimap.png"
        try:
            from .guide_minimap import write_guide_minimap

            for line in write_guide_minimap(map_data, out_path, extra_json):
                print(single_line_text(line))
        except Exception as exc:
            print(f"小地图标注图生成失败：{exc}", file=sys.stderr)
            hint = _minimap_error_hint(options.map_path)
            if hint:
                print(hint, file=sys.stderr)
            return 2
    return 0


def _minimap_error_hint(map_path: str) -> str:
    """小地图失败时的补充指引: 战役容器没有单张小地图 (各关独立)。"""
    if map_path.lower().endswith(".w3n"):
        return (
            "（战役容器不含任务关小地图：请对具体任务关 .w3x 生成，或先用 "
            "cli <.w3n> --pack 导出后，用 pack-query near <x> <y> 按坐标定位）"
        )
    return ""


def _display_lines(full_report: str, section: str | None) -> list[str]:
    """完整报告 → 展示行；指定段落键时只保留该段。"""
    if section is None:
        return full_report.splitlines()
    header = f"【{GUIDE_SECTION_TITLES[section]}】"
    lines = full_report.splitlines()
    picked: list[str] = []
    inside = False
    for line in lines:
        if line.startswith("【"):
            inside = line == header
            if inside:
                picked.append(line)
        elif inside:
            picked.append(line)
    while picked and picked[-1] == "":
        picked.pop()
    return picked
