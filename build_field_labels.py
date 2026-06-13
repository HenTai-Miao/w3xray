"""离线生成 w3xtool/field_meta.py —— 对象字段 4 字符码 → 中文标签 + 字段类型。

数据源：魔兽对象编辑器的 MetaData.slk 系列（每个字段码 → displayName(WESTRING_*) + type），
WESTRING_* 经本项目已内置的 westrings.py 还原成中文。一次性生成，运行时零开销、不读游戏。

用法：
    uv run build_field_labels.py --meta-dir <含 *metadata.slk 的目录>
默认指向 KKWE 自带 w3x2lni 的 meta 目录（首次生成用）。换语言/升级后想刷新就重指 --meta-dir。

字段元数据文件（8 个）：
    units/{unit,ability,upgrade,misc,destructable,abilitybuff,upgradeeffect}metadata.slk
    doodads/DoodadMetaData.slk
"""
from __future__ import annotations

import argparse
import os
import re
import sys

from w3xtool.slk import parse_slk

try:
    from w3xtool.westrings import WESTRINGS
except Exception:
    WESTRINGS = {}

_DEFAULT_META = ("C:/Users/zhongerbing/Desktop/KKWE插件/plugin/"
                 "w3x2lni_zhCN_v2.7.3/script/meta")

_META_FILES = [
    "units/unitmetadata.slk", "units/abilitymetadata.slk",
    "units/upgrademetadata.slk", "units/miscmetadata.slk",
    "units/destructablemetadata.slk", "units/abilitybuffmetadata.slk",
    "units/upgradeeffectmetadata.slk", "doodads/DoodadMetaData.slk",
]

_CTRL = re.compile(r"[\x00-\x1f]+")


def resolve_westring(key: str) -> str:
    """链式解 WESTRING_*（WESTRING_A→WESTRING_B→真文本），防环，去控制符。

    不是 WESTRING_ 开头直接原样；解不到则回退原 key。
    """
    if not isinstance(key, str) or not key.upper().startswith("WESTRING_"):
        return _CTRL.sub("", key) if isinstance(key, str) else key
    seen = set()
    k = key
    while isinstance(k, str) and k.upper().startswith("WESTRING_") and k not in seen:
        seen.add(k)
        nxt = WESTRINGS.get(k) or WESTRINGS.get(k.upper())
        if nxt is None:
            break
        k = nxt
    return _CTRL.sub("", k) if isinstance(k, str) else k


def build(meta_dir: str):
    labels = {}
    types = {}
    found = unresolved = 0
    for rel in _META_FILES:
        path = os.path.join(meta_dir, rel)
        if not os.path.isfile(path):
            print(f"[跳过] 未找到 {rel}", file=sys.stderr)
            continue
        rows = parse_slk(open(path, encoding="latin-1").read())
        for code, row in rows.items():
            found += 1
            dn = row.get("displayName", "")
            lab = resolve_westring(dn)
            typ = row.get("type", "")
            if typ and code not in types:
                types[code] = typ
            if not lab or lab.upper().startswith("WESTRING_"):
                unresolved += 1
                continue
            labels.setdefault(code, lab)
    return labels, types, found, unresolved


def write_module(labels, types, out_path):
    lines = [
        '"""对象字段 4 字符码 → 中文标签 / 字段类型（由 build_field_labels.py 离线生成）。',
        "",
        "数据源：魔兽 MetaData.slk 系列 + 内置 westrings.py 还原。请勿手改——重生成会覆盖。",
        '运行时只查表、零开销。手工精选标签在 fields.py 的 FIELD_LABELS 里（优先级更高）。"""',
        "",
        "GENERATED_FIELD_LABELS = {",
    ]
    for code in sorted(labels):
        lines.append(f"    {code!r}: {labels[code]!r},")
    lines.append("}")
    lines.append("")
    lines.append("FIELD_TYPES = {")
    for code in sorted(types):
        lines.append(f"    {code!r}: {types[code]!r},")
    lines.append("}")
    lines.append("")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta-dir", default=_DEFAULT_META)
    ap.add_argument("--out", default=os.path.join("w3xtool", "field_meta.py"))
    args = ap.parse_args()
    labels, types, found, unresolved = build(args.meta_dir)
    write_module(labels, types, args.out)
    print(f"字段总数 {found}，标签 {len(labels)} 个（未解 {unresolved}），类型 {len(types)} 个")
    print(f"已写入 {args.out}")


if __name__ == "__main__":
    main()
