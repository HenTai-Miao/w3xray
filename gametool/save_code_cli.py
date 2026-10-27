"""savecodes 子命令: 从导出知识包的文本载体提取存/读码。

用法: uv run main.py savecodes <知识包目录> [--limit N]

扫描全部命名 .j/.lua/.txt/.pld 文本, 用保留偏移的脚本视图提取载体与候选。
只读文本, 绝不执行任何内容。--json 保留完整原文、编码、偏移和来源哈希。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from gametool.bounded_file import read_bounded_regular_file
from gametool.pack_query_options import parse_query_limit
from gametool.save_codes import (
    decode_save_text,
    extract_save_codes_bytes,
    extract_save_text_carriers,
)
from gametool.script_sources import script_language
from gametool.save_source_paths import iter_save_source_files, save_source_path_error

__all__ = ("run_save_code_cli",)


def _stat_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_mode,
    )


def _iter_text_files(
    pack_dir: str, diagnostics: list[str] | None = None
) -> list[tuple[str, str]]:
    """Every named script/text carrier below the pack, without following links."""
    root = Path(pack_dir)
    files, notes = iter_save_source_files(
        root, suffixes=frozenset({".j", ".lua", ".txt", ".pld"})
    )
    if diagnostics is not None:
        diagnostics.extend(notes)
    return [(os.path.relpath(path, root), str(path)) for path in files]


def run_save_code_cli(argv: tuple[str, ...]) -> int:
    parser = argparse.ArgumentParser(
        prog="savecodes", description="从知识包文本载体提取存/读码模板"
    )
    parser.add_argument("pack", help="导出知识包目录 (含 脚本可读文本/)")
    parser.add_argument(
        "--limit",
        type=parse_query_limit,
        default=0,
        help="显式缩减首屏条数 (默认 0=全量输出; 达限披露余量)",
    )
    parser.add_argument(
        "--json", action="store_true", help="完整载体/候选/原始文本/字节偏移与诊断"
    )
    args = parser.parse_args(argv)
    pack = args.pack
    if not os.path.isdir(pack):
        print(f"包目录不存在: {pack}", file=sys.stderr)
        return 2
    found = []
    carriers = []
    diagnostics: list[str] = []
    identities: list[tuple[str, str, os.stat_result]] = []
    scanned = 0
    for rel, full in _iter_text_files(pack, diagnostics):
        try:
            problem = save_source_path_error(Path(full))
            if problem:
                diagnostics.append(problem)
                continue
            before = os.lstat(full)
            payload, _identity = read_bounded_regular_file(Path(full))
        except OSError as exc:
            diagnostics.append(f"{rel}: {exc}")
            continue
        scanned += 1
        identities.append((rel, full, before))
        decoded = decode_save_text(payload)
        if decoded is None:
            diagnostics.append(f"{rel}: 未识别完整文本编码；未替换或丢失源字节")
            continue
        text, encoding, bom = decoded
        lua = script_language(rel)
        carriers.extend(
            extract_save_text_carriers(
                text,
                rel,
                lua=lua,
                encoding=encoding,
                bom_bytes=bom,
                include_plain_prefixes=True,
                byte_source=payload,
            )
        )
        hits = extract_save_codes_bytes(payload, source=rel, lua=lua)
        for sc in hits:
            found.append((rel, sc))
    unstable: set[str] = set()
    for rel, full, before in identities:
        try:
            after = os.lstat(full)
            changed = bool(save_source_path_error(Path(full))) or _stat_identity(
                before
            ) != _stat_identity(after)
        except OSError:
            changed = True
        if changed:
            unstable.add(rel)
            diagnostics.append(f"{rel}: 来源在交付前改变；未交付旧读取结果")
    found = [(rel, code) for rel, code in found if rel not in unstable]
    carriers = [carrier for carrier in carriers if carrier.source not in unstable]
    diagnostics.extend(
        f"{carrier.source}:{carrier.line}: {note}"
        for carrier in carriers
        for note in carrier.diagnostics
    )
    shown = found[: args.limit] if args.limit else found
    if args.json:
        print(
            json.dumps(
                {
                    "scanned": scanned,
                    "total": len(found),
                    "omitted": len(found) - len(shown),
                    "codes": [sc.to_dict() for _rel, sc in shown],
                    "text_carriers": [carrier.to_dict() for carrier in carriers],
                    "diagnostics": diagnostics,
                    "map_validation": "not_performed",
                },
                ensure_ascii=False,
                allow_nan=False,
            )
        )
        return 2 if diagnostics else 0
    print(
        f"扫描 {scanned} 个文本文件, 提取到 {len(found)} 条存/读码；完整文本载体 {len(carriers)} 条"
    )
    for diagnostic in diagnostics:
        print(f"诊断：{diagnostic}")
    if not found:
        print(
            "未发现存/读码文本 — 非存档图属正常; 脚本被加密时此类分析不可得"
            " (提取阶梯静态层结论)"
        )
        return 2 if diagnostics else 0
    for rel, sc in shown:
        print(
            f"{rel}:{sc.line} [{sc.carrier}; {sc.state}; {sc.encoding}; 字符 {sc.offset}:{sc.end}; 字节 {sc.byte_offset}:{sc.byte_end}] {sc.code}"
        )
    if args.limit and len(found) > args.limit:
        print(f"... 其余 {len(found) - args.limit} 条省略 (--limit 提高上限)")
    return 2 if diagnostics else 0
