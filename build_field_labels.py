"""离线生成 w3xtool/field_meta.py —— 对象字段 4 字符码 → 中文标签 + 字段类型 + 适用性/值域/常量。

数据源：魔兽对象编辑器的 MetaData.slk 系列（每个字段码 → displayName(WESTRING_*) + type
+ useSpecific/notSpecific + minVal/maxVal），WESTRING_* 经本项目已内置的 westrings.py
还原成中文。可选 --common-j（Reforged 版 jass common.j）解析
`constant ability*field NAME = ConvertAbility*Field('code')` 得到 码→常量名。
一次性生成，运行时零开销、不读游戏。

用法：
    uv run build_field_labels.py --meta-dir <含 *metadata.slk 的目录> [--common-j <common.j>]
默认指向 KKWE 自带 w3x2lni 的 meta 目录（首次生成用）。换语言/升级后想刷新就重指 --meta-dir。

合并语义：标签/类型保留 field_meta.py 现有值、只补新码（保证重跑 diff 最小）；
适用性/值域/常量表每次从输入全量重建。meta 目录也可以用 war3-objectdata 快照的
objectdata 目录（WESTRING 键与语言无关，中文标签仍由 westrings.py 还原）。

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
    from w3xtool import westrings as _west_module
except Exception:
    _west_module = None

_WESTRINGS: dict[str, str] = (
    dict(getattr(_west_module, "WESTRINGS", {})) if _west_module is not None else {}
)

_DEFAULT_META = (
    "C:/Users/zhongerbing/Desktop/KKWE插件/plugin/w3x2lni_zhCN_v2.7.3/script/meta"
)

_META_FILES = [
    "units/unitmetadata.slk",
    "units/abilitymetadata.slk",
    "units/upgrademetadata.slk",
    "units/miscmetadata.slk",
    "units/destructablemetadata.slk",
    "units/abilitybuffmetadata.slk",
    "units/upgradeeffectmetadata.slk",
    "doodads/DoodadMetaData.slk",
]

_CTRL = re.compile(r"[\x00-\x1f]+")
_ABILITY_FIELD_CONST = re.compile(
    r"constant\s+ability\w*field\s+(\w+)\s*=\s*ConvertAbility\w+\(\s*'(\w{4})'\s*\)"
)


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
        nxt = _WESTRINGS.get(k) or _WESTRINGS.get(k.upper())
        if nxt is None:
            break
        k = nxt
    return _CTRL.sub("", k) if isinstance(k, str) else k


def _split_codes(value: str) -> tuple[str, ...]:
    """逗号分隔的 useSpecific/notSpecific 码列表（容忍双逗号空段）。"""
    return tuple(part.strip() for part in value.split(",") if part.strip())


def build_constants(common_j_path: str) -> dict[str, str]:
    """从 Reforged common.j 解析 ability 字段码 → 常量名（如 Efk1→…_EFK1）。"""
    text = open(common_j_path, encoding="utf-8", errors="replace").read()
    constants: dict[str, str] = {}
    for name, code in _ABILITY_FIELD_CONST.findall(text):
        constants.setdefault(code, name)
    return constants


def build(meta_dir: str, common_j_path: str | None = None):
    """返回 (labels, types, applicability, bounds, constants, found, unresolved)。

    labels/types 先载入现有 field_meta.py 再补缺；applicability/bounds/constants
    每次全量重建。
    """
    from w3xtool.field_meta import FIELD_TYPES, GENERATED_FIELD_LABELS

    labels: dict[str, str] = dict(GENERATED_FIELD_LABELS)
    types: dict[str, str] = dict(FIELD_TYPES)
    applicability: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
    bounds: dict[str, tuple[str | None, str | None]] = {}
    constants: dict[str, str] = {}
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
            if typ:
                types.setdefault(code, typ)
            if not lab or lab.upper().startswith("WESTRING_"):
                unresolved += 1
            else:
                labels.setdefault(code, lab)
            use = _split_codes(row.get("useSpecific", "") or "")
            not_specific = _split_codes(row.get("notSpecific", "") or "")
            if use or not_specific:
                applicability.setdefault(code, (use, not_specific))
            lo = row.get("minVal") or None
            hi = row.get("maxVal") or None
            if lo or hi:
                bounds.setdefault(code, (lo, hi))
    constants = build_constants(common_j_path) if common_j_path else {}
    return labels, types, applicability, bounds, constants, found, unresolved


def write_module(labels, types, applicability, bounds, constants, out_path):
    lines = [
        '"""对象字段 4 字符码 → 中文标签 / 字段类型 / 适用性 / 值域 / 常量名'
        "（由 build_field_labels.py 离线生成）。",
        "",
        "数据源：魔兽 MetaData.slk 系列 + 内置 westrings.py 还原；常量名来自 jass common.j"
        "（--common-j）。请勿手改——重生成会覆盖。",
        '运行时只查表、零开销。手工精选标签在 fields.py 的 FIELD_LABELS 里（优先级更高）。"""',
        "",
        "GENERATED_FIELD_LABELS = {",
    ]
    for code in sorted(labels):
        lines.append(f"    {code!r}: {labels[code]!r},")
    lines.append("}")
    lines += ["", "FIELD_TYPES = {"]
    for code in sorted(types):
        lines.append(f"    {code!r}: {types[code]!r},")
    lines.append("}")
    lines += [
        "",
        "# 字段适用性：码 → (useSpecific, notSpecific)，仅技能系 MetaData 提供。",
        "GENERATED_FIELD_APPLICABILITY = {",
    ]
    for code in sorted(applicability):
        use, not_specific = applicability[code]
        lines.append(f"    {code!r}: ({use!r}, {not_specific!r}),")
    lines.append("}")
    lines += [
        "",
        "# 字段值域：码 → (minVal, maxVal)，None 表示该侧未限定（原始字符串，可能非数值）。",
        "GENERATED_FIELD_BOUNDS = {",
    ]
    for code in sorted(bounds):
        lo, hi = bounds[code]
        lines.append(f"    {code!r}: ({lo!r}, {hi!r}),")
    lines.append("}")
    if constants:
        lines += [
            "",
            "# common.j 常量名：ability 字段码 → 常量（如 'Hbz1' → ABILITY_ILF_NUMBER_OF_WAVES）。",
            "GENERATED_FIELD_CONSTANTS = {",
        ]
        for code in sorted(constants):
            lines.append(f"    {code!r}: {constants[code]!r},")
        lines.append("}")
    lines.append("")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta-dir", default=_DEFAULT_META)
    ap.add_argument(
        "--common-j",
        default=None,
        help="Reforged 版 jass common.j 路径（可选；用于生成码→常量名表）",
    )
    ap.add_argument("--out", default=os.path.join("w3xtool", "field_meta.py"))
    args = ap.parse_args()
    labels, types, applicability, bounds, constants, found, unresolved = build(
        args.meta_dir, args.common_j
    )
    write_module(labels, types, applicability, bounds, constants, args.out)
    print(
        f"字段总数 {found}，标签 {len(labels)} 个（未解 {unresolved}），类型 {len(types)} 个，"
        f"适用性 {len(applicability)} 个，值域 {len(bounds)} 个，常量 {len(constants)} 个"
    )
    print(f"已写入 {args.out}")


if __name__ == "__main__":
    main()
