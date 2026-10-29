"""Explicit offline equipment-plan CLI; no game session or automatic discovery."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import replace
import json
from pathlib import Path
import sys

from .loadout_report import (
    LoadoutSelection,
    format_loadout_report,
    read_loadout_report,
    revalidate_loadout_source,
    select_loadout_report,
    write_loadout_export,
)
from .save_text_encoding import SAVE_TEXT_ENCODINGS


def _format_stdout(
    selection: LoadoutSelection, as_json: bool, operation_error: str
) -> str:
    if as_json:
        payload = selection.to_dict()
        if operation_error:
            payload.update(
                input_error=True, exit_code=2, operation_diagnostics=[operation_error]
            )
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    text = format_loadout_report(selection)
    if operation_error:
        text += "\n## 操作诊断\n\n" + operation_error + "\n"
    return text


def run_loadout_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gamexray loadout",
        description="离线查看明确选择的装备方案 JSON；完整保留槽位、数量、重复键与原始证据。",
    )
    parser.add_argument("path", help="明确选择的六槽或九槽方案文件")
    parser.add_argument(
        "--query", default="", help="按完整方案记录搜索；支持 &&、||、%%、括号"
    )
    parser.add_argument("--text-encoding", choices=SAVE_TEXT_ENCODINGS, default="auto")
    parser.add_argument("--json", action="store_true", help="输出完整结构化证据报告")
    parser.add_argument(
        "--export", type=Path, help="导出到不存在的新文件，保留全部原始证据"
    )
    parser.add_argument(
        "--format", choices=("json", "md", "tsv"), help="导出格式；默认由扩展名推定"
    )
    args = parser.parse_args(argv)
    try:
        report = read_loadout_report(args.path, text_encoding=args.text_encoding)
        selection = select_loadout_report(report, args.query)
        operation_error = ""
        if args.export is not None:
            format = args.format or args.export.suffix.lower().lstrip(".") or "json"
            try:
                destination = write_loadout_export(args.export, selection, format)
                print(f"已导出完整证据报告: {destination}", file=sys.stderr)
            except (OSError, ValueError) as exc:
                operation_error = f"导出失败：{exc}；已保留读取时完整证据，请刷新来源或选择独立的新文件名。"
        text = _format_stdout(selection, args.json, operation_error)
        if report.stable:
            try:
                # Query and full serialization can be lengthy. The last proof
                # belongs after both, immediately before stdout delivery.
                revalidate_loadout_source(report)
            except (OSError, ValueError) as exc:
                report = replace(
                    report,
                    stable=False,
                    source_diagnostics=(
                        *report.source_diagnostics,
                        f"最终交付前来源变化或不可读：{exc}；保留读取时全部记录与原始字节，需刷新。",
                    ),
                )
                selection = replace(selection, report=report)
                text = _format_stdout(selection, args.json, operation_error)
        print(text, end="")
        return 2 if operation_error else report.exit_code
    except (OSError, ValueError) as exc:
        message = f"离线装备方案读取或导出失败：{exc}；请选择稳定的原方案文件，导出请使用独立的新文件名。"
        if args.json:
            print(
                json.dumps(
                    {
                        "report_type": "offline-loadout-inspection",
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


__all__ = ("run_loadout_cli",)
