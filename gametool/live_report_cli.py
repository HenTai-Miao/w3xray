"""Game-free structured live-report inspection and comparison CLI."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import sys

from .cli_output import configure_cli_output
from .live_report import (
    LiveReportError,
    compare_live_reports,
    format_live_report_diff,
    read_live_report,
)
from .live_report_io import verify_report_source, write_report_bytes
from .live_report_json import format_report_json


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="live-report",
        description="离线查看和比较实时探针报告；无需运行游戏。保存文件代表其原始采集时刻。",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser(
        "inspect", help="完整查看一份结构报告或旧版 live JSON"
    )
    inspect.add_argument("file", metavar="FILE")
    inspect.add_argument(
        "--json", action="store_true", help="输出完整精确 JSON（含来源与原报告）"
    )
    diff = commands.add_parser("diff", help="按物理实例/背包槽位比较两份报告")
    diff.add_argument("old", metavar="OLD")
    diff.add_argument("new", metavar="NEW")
    diff.add_argument("--json", action="store_true", help="输出完整结构比较 JSON")
    diff.add_argument(
        "--output", metavar="PATH", help="另存完整输出到新的文件名，拒绝覆盖已有文件"
    )
    return parser


def run_live_report_cli(argv: Sequence[str] | None = None) -> int:
    """Return 0 inspected/equal, 1 changed, 2 invalid or uncertain comparison."""
    configure_cli_output()
    try:
        options = _parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    try:
        if options.command == "inspect":
            report = read_live_report(options.file)
            if options.json:
                output = format_report_json(
                    {
                        "schema": "gamexray-live-report-inspection",
                        "schema_version": 1,
                        "input_error": False,
                        "source": report.source,
                        "document": report.metadata,
                        "report": report,
                    }
                )
            else:
                output = "\n".join(
                    (
                        "实时报告离线查看（历史读数）",
                        "来源: " + format_report_json(report.source),
                        "文档: " + format_report_json(report.metadata),
                        "完整原始报告:",
                        report.to_json(),
                    )
                )
            verify_report_source(report.source)
            print(output)
            return 0
        old = read_live_report(options.old)
        new = read_live_report(options.new)
        result = compare_live_reports(old, new)
        output = result.to_json() if options.json else format_live_report_diff(result)

        def verify_sources() -> None:
            verify_report_source(old.source)
            verify_report_source(new.source)

        verify_sources()
        if options.output is not None:
            write_report_bytes(
                options.output,
                (output + "\n").encode("utf-8", errors="strict"),
                verify_source=verify_sources,
            )
        verify_sources()
        print(output)
        if result["comparison_complete"] is not True:
            return 2
        return 1 if result["has_changes"] else 0
    except (LiveReportError, OSError) as exc:
        print(f"离线实时报告错误: {exc}", file=sys.stderr)
        return 2
