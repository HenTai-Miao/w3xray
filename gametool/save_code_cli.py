"""savecodes 子命令: 从导出知识包的文本载体提取存/读码。

用法: uv run main.py savecodes <知识包目录> [--limit N]

扫描全部命名 .j/.lua/.txt/.pld/.log 文本，也可指定一个文本文件或 --text/--stdin。
只读文本, 绝不执行任何内容。--json 保留完整原文、编码、偏移和来源哈希。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from gametool.bounded_file import read_bounded_regular_file, sha256_regular_file
from gametool.pack_query_options import parse_query_limit
from gametool.save_codes import (
    extract_save_codes_bytes,
    extract_save_text_carriers,
)
from gametool.script_sources import script_language
from gametool.save_source_paths import iter_save_source_files, save_source_path_error
from gametool.save_text_encoding import (
    SAVE_TEXT_ENCODINGS,
    inspect_save_text,
    normalize_save_text_encoding,
)

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
    directory = root.is_dir()
    files, notes = iter_save_source_files(
        root,
        suffixes=frozenset({".j", ".lua", ".txt", ".pld", ".log"})
        if directory
        else None,
    )
    if diagnostics is not None:
        diagnostics.extend(notes)
    base = root if directory else root.parent
    return [(os.path.relpath(path, base), str(path)) for path in files]


def run_save_code_cli(argv: tuple[str, ...]) -> int:
    parser = argparse.ArgumentParser(
        prog="savecodes",
        description="从本地目录、文本文件或明确提供的文本提取存/读码候选",
    )
    parser.add_argument(
        "pack", nargs="?", help="知识包/存档目录或单个文本文件（含 .log）"
    )
    inline = parser.add_mutually_exclusive_group()
    inline.add_argument(
        "--text", help="直接分析明确提供的文本；语言保持未知，不执行内容"
    )
    inline.add_argument(
        "--stdin",
        action="store_true",
        help="明确请求从标准输入读取完整字节；不会默认等待输入",
    )
    parser.add_argument(
        "--limit",
        type=parse_query_limit,
        default=0,
        help="显式缩减首屏条数 (默认 0=全量输出; 达限披露余量)",
    )
    parser.add_argument(
        "--json", action="store_true", help="完整载体/候选/原始文本/字节偏移与诊断"
    )
    parser.add_argument(
        "--text-encoding",
        "--encoding",
        type=normalize_save_text_encoding,
        choices=SAVE_TEXT_ENCODINGS,
        default="auto",
        help="文件/标准输入的文本编码；auto 不猜测无 BOM UTF-16，可明确选择 utf-16-le/utf-16-be",
    )
    args = parser.parse_args(argv)
    pack = args.pack
    if (pack is not None) == (args.text is not None or args.stdin):
        parser.error("请指定一个目录/文件，或使用 --text/--stdin；三种来源只能选择一种")
    if args.text is not None and args.text_encoding not in ("auto", "utf-8"):
        parser.error("--text 已是 Unicode 文本；编码选项用于文件或 --stdin 原始字节")
    found = []
    carriers = []
    diagnostics: list[str] = []
    identities: list[tuple[str, str, os.stat_result, str]] = []
    source_records: list[tuple[str, dict[str, object]]] = []
    scanned = 0
    if pack is not None:
        sources: list[tuple[str, str | None, bytes | None]] = [
            (rel, full, None) for rel, full in _iter_text_files(pack, diagnostics)
        ]
        if not sources and not diagnostics:
            diagnostics.append(
                "来源中没有可读取的命名文本文件；可指定存档文本文件或包含 .log/.txt/.pld/.j/.lua 的目录。"
            )
    else:
        if args.text is not None:
            inline_bytes = args.text.encode("utf-8")
            source_label = "<text>"
        else:
            stream = getattr(sys.stdin, "buffer", sys.stdin)
            content = stream.read()
            if isinstance(content, str) and args.text_encoding not in ("auto", "utf-8"):
                parser.error("标准输入未提供原始字节；无法按指定编码重新解释已解码文本")
            inline_bytes = (
                content.encode("utf-8") if isinstance(content, str) else content
            )
            source_label = "<stdin>"
        sources = [(source_label, None, inline_bytes)]
    for rel, full, inline_payload in sources:
        try:
            if full is not None:
                problem = save_source_path_error(Path(full))
                if problem:
                    diagnostics.append(problem)
                    continue
                before = os.lstat(full)
                payload, _identity = read_bounded_regular_file(Path(full))
                identities.append(
                    (rel, full, before, hashlib.sha256(payload).hexdigest())
                )
            else:
                assert inline_payload is not None
                payload = inline_payload
        except OSError as exc:
            diagnostics.append(f"{rel}: {exc}")
            continue
        scanned += 1
        decoded = inspect_save_text(payload, args.text_encoding)
        source_records.append(
            (
                rel,
                {
                    "source": rel,
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "raw_hex": payload.hex(),
                    "raw_text": decoded.text,
                    "text_decoding": decoded.to_dict(payload),
                },
            )
        )
        if decoded.text is None:
            diagnostics.extend(f"{rel}: {note}" for note in decoded.diagnostics)
            continue
        text, encoding, bom = decoded.text, decoded.encoding, decoded.bom_bytes
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
        hits = extract_save_codes_bytes(
            payload, source=rel, lua=lua, text_encoding=args.text_encoding
        )
        for sc in hits:
            found.append((rel, sc))
    unstable: set[str] = set()
    for rel, full, before, expected_sha in identities:
        try:
            after = os.lstat(full)
            changed = bool(save_source_path_error(Path(full))) or _stat_identity(
                before
            ) != _stat_identity(after)
            if not changed:
                actual_sha, _identity = sha256_regular_file(Path(full))
                changed = actual_sha != expected_sha
        except OSError:
            changed = True
        if changed:
            unstable.add(rel)
            diagnostics.append(f"{rel}: 来源在交付前改变；未交付旧读取结果")
    found = [(rel, code) for rel, code in found if rel not in unstable]
    carriers = [carrier for carrier in carriers if carrier.source not in unstable]
    source_records = [entry for entry in source_records if entry[0] not in unstable]
    diagnostics.extend(
        f"{carrier.source}:{carrier.line}: {note}"
        for carrier in carriers
        for note in carrier.diagnostics
    )
    if pack is not None:
        after_diagnostics: list[str] = []
        after_sources = _iter_text_files(pack, after_diagnostics)
        if [(rel, full) for rel, full, _payload in sources] != after_sources:
            diagnostics.append("来源文本文件清单在分析期间改变；请刷新后重试。")
        diagnostics.extend(
            note for note in after_diagnostics if note not in diagnostics
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
                    "text_encoding": args.text_encoding,
                    "sources": [record for _rel, record in source_records],
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
