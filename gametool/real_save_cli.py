"""CLI boundary for read-only real save evidence analysis."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .api import load_map
from .load_context import MapLoadContext
from .pack_query_options import parse_query_limit
from .real_save_files import RealSaveReport, SaveFileKind, analyze_real_save_path
from .safe_output_models import SafeWriteStatus
from .save_report_query import (
    select_save_report,
    verify_save_report_sources,
    write_save_report,
)


def run_real_save_cli(argv: tuple[str, ...]) -> int:
    """Analyze a local save independently, with optional static map correlation."""
    parser = argparse.ArgumentParser(prog="gamexray save")
    parser.add_argument("--map", type=Path, help="可选：关联地图中的存档键和对象")
    parser.add_argument("--save", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--author-bundle", type=Path)
    parser.add_argument(
        "--query", default="", help="按完整文件搜索；支持 &&、||、%%、括号和精准词"
    )
    parser.add_argument(
        "--kind", choices=tuple(kind.value for kind in SaveFileKind), default=""
    )
    parser.add_argument(
        "--limit",
        type=parse_query_limit,
        default=0,
        help="匹配文件数；0/all/全部=全量，完整诊断始终保留",
    )
    parser.add_argument(
        "--format",
        choices=("tsv", "json", "md"),
        default="tsv",
        help="完整来源/记录/偏移证据格式 (默认 tsv)",
    )
    args = parser.parse_args(argv)
    if args.author_bundle is not None and args.map is None:
        parser.error("--author-bundle 需要同时指定 --map")
    context = MapLoadContext(
        author_bundle_path=str(args.author_bundle)
        if args.author_bundle is not None
        else None,
    )
    try:
        # Validate the query before loading a map or touching source evidence.
        _ = select_save_report(
            RealSaveReport("", (), ()), args.query, args.kind, args.limit
        )
        md = (
            load_map(str(args.map), load_context=context)
            if args.map is not None
            else None
        )
        report = analyze_real_save_path(args.save, md)
        report = verify_save_report_sources(report)
        selection = select_save_report(report, args.query, args.kind, args.limit)
        result = write_save_report(selection, args.output, args.format)
        selection = result.selection
        report = selection.report
    except (OSError, ValueError) as exc:
        print(f"真实存档分析失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if result.status is not SafeWriteStatus.WRITTEN:
        print(
            f"真实存档报告写入失败：{result.error or result.status.value}",
            file=sys.stderr,
        )
        return 1
    state = "完整" if report.complete else "未完成，见完整诊断"
    print(
        f"真实存档只读分析：{state}；{selection.matched_files} 个匹配文件，导出 {len(selection.files)} 个 -> {result.path}"
    )
    print(
        "地图关联："
        + (
            report.map_path
            if report.map_associated
            else "未做地图关联；可用 --map 追加静态关联。"
        )
    )
    if selection.omitted_files:
        print(
            f"显式 --limit {args.limit} 省略 {selection.omitted_files} 个完整文件记录。"
        )
    if not selection.files:
        print("没有匹配文件；可清空 --query/--kind，或选择其他存档文件/目录。")
    for warning in selection.diagnostics:
        print(f"警告：{warning}")
    return 0 if report.complete else 2
