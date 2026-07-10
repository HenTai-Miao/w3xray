"""CLI boundary for read-only real save evidence analysis."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .api import load_map
from .load_context import MapLoadContext
from .real_save_files import analyze_real_save_path, format_real_save_report_tsv
from .safe_output import write_text_safely
from .safe_output_models import SafeWriteStatus


def run_real_save_cli(argv: tuple[str, ...]) -> int:
    """Analyze one save path against a map and write a deterministic TSV."""
    parser = argparse.ArgumentParser(prog="w3xray save")
    parser.add_argument("--map", required=True, type=Path)
    parser.add_argument("--save", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--author-bundle", type=Path)
    args = parser.parse_args(argv)
    context = MapLoadContext(
        author_bundle_path=str(args.author_bundle) if args.author_bundle is not None else None,
    )
    try:
        md = load_map(str(args.map), load_context=context)
        report = analyze_real_save_path(args.save, md)
        result = write_text_safely(
            str(args.output.parent),
            args.output.name,
            format_real_save_report_tsv(report),
        )
    except (OSError, ValueError) as exc:
        print(f"真实存档分析失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if result.status is not SafeWriteStatus.WRITTEN:
        print(f"真实存档报告写入失败：{result.error or result.status.value}", file=sys.stderr)
        return 1
    print(f"真实存档只读分析：{len(report.files)} 个文件 -> {result.path}")
    for warning in report.warnings:
        print(f"警告：{warning}")
    return 0
