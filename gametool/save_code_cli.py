"""savecodes 子命令: 从导出知识包的文本载体提取存/读码。

用法: uv run main.py savecodes <知识包目录> [--limit N]

扫描 脚本可读文本/*.j (地图脚本可读形态) 与包内 Preload 相关 *.txt,
纯正则提取 -load/-save 类码模板。只读文本, 绝不执行任何内容。
"""

from __future__ import annotations

import argparse
import os
import sys

from gametool.save_codes import extract_save_codes, extract_script_save_codes

__all__ = ("run_save_code_cli",)


def _iter_text_files(pack_dir: str) -> list[tuple[str, str]]:
    """(相对路径, 绝对路径) 列表: 脚本可读文本/*.j + Preload 相关 *.txt。"""
    out: list[tuple[str, str]] = []
    script_dir = os.path.join(pack_dir, "脚本可读文本")
    if os.path.isdir(script_dir):
        for name in sorted(os.listdir(script_dir)):
            if name.lower().endswith(".j"):
                full = os.path.join(script_dir, name)
                if os.path.isfile(full):
                    out.append((os.path.join("脚本可读文本", name), full))
    for root, dirs, files in os.walk(pack_dir):
        rel_root = os.path.relpath(root, pack_dir)
        if rel_root != "." and "preload" not in rel_root.lower():
            dirs[:] = []
            continue
        for name in sorted(files):
            if name.lower().endswith(".txt"):
                full = os.path.join(root, name)
                if os.path.isfile(full):
                    rel = name if rel_root == "." else os.path.join(rel_root, name)
                    out.append((rel, full))
        if rel_root != ".":
            dirs[:] = []
    return out


def run_save_code_cli(argv: tuple[str, ...]) -> int:
    parser = argparse.ArgumentParser(
        prog="savecodes", description="从知识包文本载体提取存/读码模板"
    )
    parser.add_argument("pack", help="导出知识包目录 (含 脚本可读文本/)")
    parser.add_argument(
        "--limit", type=int, default=0, help="最多输出条数 (默认 0=全部输出)"
    )
    args = parser.parse_args(argv)
    pack = args.pack
    if not os.path.isdir(pack):
        print(f"包目录不存在: {pack}", file=sys.stderr)
        return 2
    found = []
    scanned = 0
    for rel, full in _iter_text_files(pack):
        try:
            with open(full, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        scanned += 1
        if rel.lower().endswith(".j"):
            hits = extract_script_save_codes(text)
        else:
            hits = extract_save_codes(text, source="preload-text")
        for sc in hits:
            found.append((rel, sc))
    print(f"扫描 {scanned} 个文本文件, 提取到 {len(found)} 条存/读码")
    if not found:
        print(
            "未发现存/读码文本 — 非存档图属正常; 脚本被加密时此类分析不可得"
            " (提取阶梯静态层结论)"
        )
        return 0
    shown = found[: args.limit] if args.limit else found  # 默认全量
    for rel, sc in shown:
        print(f"{rel}:{sc.line} [{sc.source}] {sc.command} {sc.code}")
    if args.limit and len(found) > args.limit:
        print(f"... 其余 {len(found) - args.limit} 条省略 (--limit 提高上限)")
    return 0
