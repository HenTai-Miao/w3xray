"""一次性脚本：把社区 enUS 快照的英文名与细类并入 w3xtool/base_names.py。

数据源：flowtsohg/war3-objectdata（MIT）检出的 objectdata 目录
    https://github.com/flowtsohg/war3-objectdata/tree/dc5e2da21217dba8e5f750c1e867d691ab193ec1
    - 英文名：_locales/enus.w3mod/units/*Strings.txt（根目录 *Func.txt 只补缺）
    - 物品细类：units/ItemData.slk 的 class 列
    - 技能细类：units/AbilityData.slk 的 hero/item 列
    - 单位细类：units/UnitBalance.slk 的 Primary（英雄主属性）/isbldg（建筑）列

用法：
    python build_base_catalog.py --objectdata-dir <objectdata 目录> [--out-dir w3xtool]

只重写 base_names.py：BASE_NAMES（中文名）原样保留，追加/刷新
BASE_NAMES_EN 与 BASE_CATEGORIES。rawcode 大小写以现有 BASE_NAMES 为准。
"""

from __future__ import annotations

import pathlib
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from build_base_names import FILES, DirSource, parse_strings


OBJECTDATA_SOURCE_URL = (
    "https://github.com/flowtsohg/war3-objectdata"
    "/tree/dc5e2da21217dba8e5f750c1e867d691ab193ec1 (MIT)"
)

ITEM_CLASS_CATEGORIES = {
    "Permanent": ("永久物品", "Permanent"),
    "Charged": ("充能物品", "Charged"),
    "Artifact": ("神器", "Artifact"),
    "PowerUp": ("增益物品", "Power-up"),
    "Purchasable": ("可购买物品", "Purchasable"),
    "Campaign": ("战役物品", "Campaign"),
}
ITEM_DEFAULT_CATEGORY = ("其他物品", "Item")
ABILITY_HERO_CATEGORY = ("英雄技能", "Hero Ability")
ABILITY_ITEM_CATEGORY = ("物品技能", "Item Ability")
ABILITY_DEFAULT_CATEGORY = ("普通技能", "Standard Ability")
UNIT_HERO_CATEGORY = ("英雄", "Hero")
UNIT_BUILDING_CATEGORY = ("建筑", "Building")
UNIT_DEFAULT_CATEGORY = ("单位", "Unit")


def _enus_source(objectdata_dir: str) -> DirSource:
    return DirSource(str(pathlib.Path(objectdata_dir, "_locales", "enus.w3mod")))


def parse_en_names(objectdata_dir: str) -> dict[str, str]:
    """读 enUS 名称：enus 的 *Strings.txt 为主，快照根目录 *Func.txt 只补缺。"""
    enus = _enus_source(objectdata_dir)
    try:
        root = DirSource(objectdata_dir)
    except FileNotFoundError:
        root = enus
    names_en: dict[str, str] = {}
    for kind in ("Strings", "Func"):
        for fn in FILES:
            if kind not in fn:
                continue
            for src in (enus, root):
                if src is root and kind == "Strings":
                    continue  # 根目录没有语言相关 strings，只有无语言的 func/slk
                if src.has_file(fn):
                    try:
                        parse_strings(
                            src.read_file(fn).decode("utf-8", "replace"),
                            names_en,
                            fill_only=(kind == "Func"),
                        )
                    except Exception as e:
                        print("  读取失败", fn, e)
                    break
    return names_en


def parse_object_categories(objectdata_dir: str) -> dict[str, tuple[str, str]]:
    """从快照 SLK 推导细类：物品 class / 技能 hero+item / 单位 Primary+isbldg。"""
    from w3xtool.slk import parse_slk

    src = DirSource(objectdata_dir)

    def rows(fn: str) -> dict[str, dict[str, str]]:
        text = src.read_file("Units\\" + fn).decode("utf-8", "replace")
        return parse_slk(text)

    categories: dict[str, tuple[str, str]] = {}
    for code, row in rows("AbilityData.slk").items():
        if str(row.get("hero", "0")) == "1":
            categories[code] = ABILITY_HERO_CATEGORY
        elif str(row.get("item", "0")) == "1":
            categories[code] = ABILITY_ITEM_CATEGORY
        else:
            categories[code] = ABILITY_DEFAULT_CATEGORY
    for code, row in rows("ItemData.slk").items():
        categories[code] = ITEM_CLASS_CATEGORIES.get(
            row.get("class", ""), ITEM_DEFAULT_CATEGORY
        )
    for code, row in rows("UnitBalance.slk").items():
        primary = str(row.get("Primary", "_"))
        if primary not in ("_", "-", ""):
            categories[code] = UNIT_HERO_CATEGORY
        elif str(row.get("isbldg", "0")) == "1":
            categories[code] = UNIT_BUILDING_CATEGORY
        else:
            categories[code] = UNIT_DEFAULT_CATEGORY
    return categories


def _prefer_existing_casing(
    table: dict, existing_names: dict[str, str], label: str
) -> dict:
    """rawcode 大小写以现有 BASE_NAMES 为准，避免同码异形键。"""
    known = {code.casefold(): code for code in existing_names}
    out: dict = {}
    collisions = []
    for code, value in sorted(table.items()):
        key = known.get(code.casefold(), code)
        if key in out and out[key] != value:
            collisions.append(key)
            continue
        out[key] = value
    if collisions:
        print(f"  [warning] {label} 大小写归并冲突 {len(collisions)} 个，保留先到值")
    return out


def _safe_output_path(out_dir: str, filename: str) -> str:
    """输出文件路径：解析后必须仍在 out_dir 内，拒绝越界。"""
    root = pathlib.Path(out_dir).resolve()
    target = (root / filename).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"输出路径越界: {filename}")
    return str(target)


def _load_current_tables() -> tuple[dict, dict, dict]:
    """读包内当前 base_names.py 的三张表（缺项返回空）。"""
    try:
        from w3xtool import base_names as module
    except Exception:
        return {}, {}, {}
    names = dict(getattr(module, "BASE_NAMES", None) or {})
    en_names = dict(getattr(module, "BASE_NAMES_EN", None) or {})
    categories = {
        code: tuple(value)
        for code, value in (getattr(module, "BASE_CATEGORIES", None) or {}).items()
    }
    return names, en_names, categories


def append_extra_tables(lines: list[str]) -> None:
    """把包内现有的 BASE_NAMES_EN / BASE_CATEGORIES 追加到待写模块行。

    供 build_base_names.py 在整表重写 base_names.py 时调用，避免英文名/细类
    在刷新中文名时被静默丢弃（无表时是空操作）。
    """
    _names, en_names, categories = _load_current_tables()
    if en_names or categories:
        lines += [
            "",
            "# 英文名与细类来自社区 enUS 快照（build_base_catalog.py --objectdata-dir）：",
            f"# {OBJECTDATA_SOURCE_URL}",
        ]
    if en_names:
        lines += ["", "BASE_NAMES_EN = {"]
        for code in sorted(en_names):
            nm = en_names[code].replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'    {code!r}: "{nm}",')
        lines.append("}")
    if categories:
        lines += ["", "BASE_CATEGORIES = {"]
        for code in sorted(categories):
            zh, en = categories[code]
            lines.append(f"    {code!r}: ({zh!r}, {en!r}),")
        lines.append("}")


def write_base_names_module(
    names: dict,
    en_names: dict | None,
    categories: dict | None,
    out_dir: str,
) -> None:
    """写出 base_names.py：BASE_NAMES 必有，英文名/细类表存在时一并写入。"""
    lines = [
        "# 自动生成：游戏原版对象 码→中文名。由 build_base_names.py 提取。",
        "# 重跑该脚本可刷新。请勿手改。",
        "",
        "BASE_NAMES = {",
    ]
    for code in sorted(names):
        nm = names[code].replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'    {code!r}: "{nm}",')
    lines.append("}")
    if en_names or categories:
        lines += [
            "",
            "# 英文名与细类来自社区 enUS 快照（build_base_catalog.py --objectdata-dir）：",
            f"# {OBJECTDATA_SOURCE_URL}",
        ]
    if en_names:
        lines += ["", "BASE_NAMES_EN = {"]
        for code in sorted(en_names):
            nm = en_names[code].replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'    {code!r}: "{nm}",')
        lines.append("}")
    if categories:
        lines += ["", "BASE_CATEGORIES = {"]
        for code in sorted(categories):
            zh, en = categories[code]
            lines.append(f"    {code!r}: ({zh!r}, {en!r}),")
        lines.append("}")
    path = _safe_output_path(out_dir, "base_names.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"已写出 {path}")


def merge_objectdata(objectdata_dir: str, out_dir: str = "w3xtool") -> None:
    """把 enUS 快照的英文名/细类并入 base_names.py，中文名原样保留。"""
    names, _old_en, _old_categories = _load_current_tables()
    if not names:
        raise SystemExit(
            "当前 w3xtool/base_names.py 缺少 BASE_NAMES：先运行 build_base_names.py 完成中文名生成"
        )
    names_en = _prefer_existing_casing(parse_en_names(objectdata_dir), names, "英文名")
    categories = _prefer_existing_casing(
        parse_object_categories(objectdata_dir), names, "细类"
    )
    write_base_names_module(names, names_en, categories, out_dir)
    covered = sum(1 for code in names_en if code in names)
    print(f"英文名 {len(names_en)} 条（其中 {covered} 条与现有中文名对应）")
    from collections import Counter

    dist = Counter(value[0] for value in categories.values())
    print("细类分布:", dict(dist))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="把社区 enUS 快照的英文名/细类并入 w3xtool/base_names.py"
    )
    parser.add_argument(
        "--objectdata-dir",
        dest="objectdata_dir",
        required=True,
        help="flowtsohg/war3-objectdata 检出的 objectdata 目录",
    )
    parser.add_argument(
        "--out-dir",
        dest="out_dir",
        default="w3xtool",
        help="base_names.py 所在目录（默认 w3xtool）",
    )
    args = parser.parse_args()
    merge_objectdata(args.objectdata_dir, args.out_dir)
