"""Explicit offline War3Tools configuration inspection, search and export."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys

from .save_text_encoding import SAVE_TEXT_ENCODINGS
from .war3tools_config import inspect_war3tools_config
from .war3tools_config_report import (
    War3ToolsSelection,
    format_war3tools_report,
    revalidate_war3tools_selection,
    select_war3tools_report,
    write_war3tools_export,
)


def _format_stdout(
    selection: War3ToolsSelection, as_json: bool, operation_error: str
) -> str:
    if as_json:
        payload = selection.to_dict()
        if operation_error:
            payload.update(exit_code=2, operation_diagnostics=[operation_error])
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    text = format_war3tools_report(selection)
    if operation_error:
        text += "\n== 操作诊断 ==\n" + operation_error + "\n"
    return text


def run_war3tools_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gamexray war3tools",
        description="离线检查明确选择的 War3Tools INI 或配置目录，完整保留配置、按键与诊断。",
    )
    parser.add_argument("path", help="单个 INI 文件或递归读取全部 INI 的配置目录")
    parser.add_argument(
        "--query",
        default="",
        help="按文件、功能、节、键、值搜索；支持 &&、||、%% 与括号",
    )
    parser.add_argument("--text-encoding", choices=SAVE_TEXT_ENCODINGS, default="auto")
    parser.add_argument("--json", action="store_true", help="输出完整结构化证据")
    parser.add_argument("--export", type=Path, help="导出到来源目录之外的独立新文件")
    parser.add_argument(
        "--format", choices=("json", "md", "tsv"), help="默认由导出扩展名决定"
    )
    args = parser.parse_args(argv)
    try:
        inspection = inspect_war3tools_config(
            args.path, text_encoding=args.text_encoding
        )
        selection = select_war3tools_report(inspection, args.query)
        operation_error = ""
        if args.export is not None:
            chosen_format = (
                args.format or args.export.suffix.lower().lstrip(".") or "json"
            )
            try:
                destination = write_war3tools_export(
                    args.export, selection, chosen_format
                )
                print(f"已导出完整配置证据报告: {destination}", file=sys.stderr)
            except (OSError, ValueError) as exc:
                operation_error = f"导出失败：{exc}；已保留读取时的完整证据。"
        text = _format_stdout(selection, args.json, operation_error)
        checked = revalidate_war3tools_selection(selection)
        if checked.inspection != selection.inspection:
            selection = checked
            text = _format_stdout(selection, args.json, operation_error)
        print(text, end="")
        return 2 if operation_error else selection.exit_code
    except (OSError, ValueError) as exc:
        message = f"配置检查失败：{exc}；请选择实际 INI 或其配置目录，编码不确定时请明确选择 --text-encoding。"
        if args.json:
            print(
                json.dumps(
                    {
                        "report_type": "war3tools_configuration_inspection",
                        "input_error": True,
                        "exit_code": 2,
                        "diagnostics": [message],
                    },
                    ensure_ascii=False,
                )
            )
        else:
            print(message, file=sys.stderr)
        return 2


__all__ = ("run_war3tools_cli",)
