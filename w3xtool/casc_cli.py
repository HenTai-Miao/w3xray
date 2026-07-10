"""CASC full-root inventory and selected-entry extraction CLI."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import override

from .casc_inventory import write_casc_inventory
from .casclib_source import CascLibDataSource
from .safe_output import safe_relative_path, write_bytes_safely
from .safe_output_models import SafeWriteStatus


@dataclass(frozen=True, slots=True)
class CascCliError(ValueError):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


def run_casc_cli(argv: tuple[str, ...]) -> int:
    """Run a native CASC inventory or selected-entry extraction command."""
    args = _parser().parse_args(argv)
    try:
        if args.command == "inventory":
            return _run_inventory(args)
        return _run_extract(args)
    except (OSError, ValueError) as exc:
        print(f"CASC 操作失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="w3xray casc")
    commands = parser.add_subparsers(dest="command", required=True)
    inventory = commands.add_parser("inventory", help="枚举完整 Root 并写入 TSV")
    inventory.add_argument("--game-dir", required=True, type=Path)
    inventory.add_argument("--output", required=True, type=Path)
    inventory.add_argument("--mask", default="*")
    inventory.add_argument("--listfile")
    inventory.add_argument("--limit", type=_positive_int)
    extract = commands.add_parser("extract", help="按路径、FileDataID、CKey 或 EKey 导出单文件")
    extract.add_argument("--game-dir", required=True, type=Path)
    extract.add_argument("--entry", required=True)
    extract.add_argument("--output-dir", required=True, type=Path)
    return parser


def _run_inventory(args: argparse.Namespace) -> int:
    with CascLibDataSource(str(args.game_dir)) as source:
        summary = write_casc_inventory(
            source,
            args.output,
            mask=args.mask,
            listfile=args.listfile,
            limit=args.limit,
        )
    completeness = "截断预览" if summary.was_limited else "完整"
    print(
        f"CASC Root {completeness}：{summary.total} 条，"
        f"真实路径 {summary.resolved_paths}，未知路径 {summary.unknown_paths}；"
        f"{summary.output_path}"
    )
    return 0


def _run_extract(args: argparse.Namespace) -> int:
    relative = safe_relative_path(args.entry)
    if relative is None:
        raise CascCliError("unsafe CASC entry name")
    relative_name = str(relative) if len(relative.parts) > 1 else f"UnknownCASC/{relative}"
    with CascLibDataSource(str(args.game_dir)) as source:
        payload = source.read_file(args.entry)
    result = write_bytes_safely(str(args.output_dir), relative_name, payload)
    if result.status is not SafeWriteStatus.WRITTEN:
        raise OSError(result.error or result.status.value)
    print(f"已导出 {args.entry} -> {result.path} ({result.size} bytes)")
    return 0


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed
