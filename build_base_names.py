"""一次性脚本：从游戏 MPQ 提取 原版对象 码→中文名，生成 w3xtool/base_names.py。

数据来源：war3/{war3,War3x,War3Patch,War3xLocal}.mpq 里的 Units\\*Strings.txt。
重装/换语言后可重跑本脚本刷新。
"""
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
from w3xtool.mpq import MPQArchive

GAME = r"C:/Program Files (x86)/Warcraft III/war3"
# 优先级从低到高（后者覆盖前者）：基础 < 资料片 < 补丁 < 本地化
MPQS = ["war3.mpq", "War3x.mpq", "War3Patch.mpq", "War3xLocal.mpq"]

RACES = ["Human", "Orc", "NightElf", "Undead", "Neutral", "Campaign"]
FILES = []
FILES += [f"Units\\{r}UnitStrings.txt" for r in RACES]
FILES += [f"Units\\{r}UnitFunc.txt" for r in RACES]
FILES += ["Units\\ItemStrings.txt", "Units\\ItemFunc.txt"]
FILES += [f"Units\\{r}AbilityStrings.txt" for r in (RACES + ["Common", "Item"])]
FILES += [f"Units\\{r}AbilityFunc.txt" for r in (RACES + ["Common", "Item"])]
FILES += [f"Units\\{r}UpgradeStrings.txt" for r in RACES]
FILES += [f"Units\\{r}UpgradeFunc.txt" for r in RACES]

_COLOR = re.compile(r"\|c[0-9a-fA-F]{8}|\|r", re.IGNORECASE)


def clean(name: str) -> str:
    name = _COLOR.sub("", name).strip().strip('"').strip()
    # 取逗号前主名（部分条目是 "名,变体"）
    if "," in name and not name.startswith("-"):
        name = name.split(",")[0].strip()
    return name


def parse_strings(text: str, out: dict, fill_only=False):
    text = text.lstrip("﻿")
    section = None
    cur_name = None
    cur_suffix = None

    def flush(sec):
        if not sec:
            return
        if fill_only and sec in out:
            return                               # 只补缺，不覆盖已有(中文)名
        v = cur_name or (cur_suffix.strip(" ()（）") if cur_suffix else None)
        if v:
            out[sec] = v

    for line in text.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            flush(section)
            section = line[1:-1].strip()
            cur_name = cur_suffix = None
            continue
        if not line or line.startswith("//") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        k = key.strip().lower()
        if k == "name" and cur_name is None:
            cur_name = clean(val)
        elif k == "editorsuffix" and cur_suffix is None:
            cur_suffix = clean(val)
    flush(section)


def main():
    names = {}
    total_files = 0
    archives = []
    for mq in MPQS:
        try:
            archives.append(MPQArchive(f"{GAME}/{mq}"))
        except Exception as e:
            print("跳过", mq, e)
    strings_files = [f for f in FILES if "Strings" in f]
    func_files = [f for f in FILES if "Func" in f]
    # 第一遍：*Strings.txt（中文名，补丁包覆盖基础包）
    for a in archives:
        for fn in strings_files:
            if a.has_file(fn):
                try:
                    parse_strings(a.read_file(fn).decode("utf-8", "replace"), names)
                    total_files += 1
                except Exception as e:
                    print("  读取失败", fn, e)
    # 第二遍：*Func.txt（只补缺，不覆盖已有中文名）
    for a in archives:
        for fn in func_files:
            if a.has_file(fn):
                try:
                    parse_strings(a.read_file(fn).decode("utf-8", "replace"), names, fill_only=True)
                    total_files += 1
                except Exception as e:
                    print("  读取失败", fn, e)
    print(f"解析 {total_files} 个文件，共 {len(names)} 个名称")
    # 写出 base_names.py
    lines = ["# 自动生成：游戏原版对象 码→中文名。由 build_base_names.py 提取。",
             "# 重跑该脚本可刷新。请勿手改。", "", "BASE_NAMES = {"]
    for code in sorted(names):
        nm = names[code].replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'    {code!r}: "{nm}",')
    lines.append("}")
    with open("w3xtool/base_names.py", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("已写出 w3xtool/base_names.py")
    # 抽查
    for c in ("hfoo", "nckb", "Hblm", "ratf", "Rhme"):
        print(f"  {c} -> {names.get(c, '(无)')}")

    # ---- 同时提取 WESTRING_ 编辑器字符串（地图对象常引用，如可破坏物名）----
    west = {}
    we_re = re.compile(r"^(WESTRING_\w+)\s*=\s*(.*)$")
    for a in archives:                      # 后面的(补丁/本地化)覆盖前面的
        for fn in (r"UI\WorldEditStrings.txt", r"UI\WorldEditGameStrings.txt"):
            if not a.has_file(fn):
                continue
            txt = a.read_file(fn).decode("utf-8", "replace")
            for line in txt.replace("\r\n", "\n").split("\n"):
                m = we_re.match(line.strip())
                if m:
                    v = clean(m.group(2))
                    if v:
                        west[m.group(1)] = v
    wl = ["# 自动生成：游戏编辑器字符串 WESTRING_xxx→文本。由 build_base_names.py 提取。",
          "# 请勿手改。", "", "WESTRINGS = {"]
    for k in sorted(west):
        v = west[k].replace("\\", "\\\\").replace('"', '\\"')
        wl.append(f'    "{k}": "{v}",')
    wl.append("}")
    with open("w3xtool/westrings.py", "w", encoding="utf-8") as f:
        f.write("\n".join(wl) + "\n")
    print(f"已写出 w3xtool/westrings.py（{len(west)} 条）")

    build_base_objects(archives)


# ---- 基础对象字段库（解析游戏 *Data.slk，jass.slk 同款数据层）----
SLK_NOISE = {"comment", "comments", "comment(s)", "sort", "version", "prio", "threat",
             "valid", "useineditor", "inbeta", "code", "scriptname", "editorsuffix",
             "editorname", "dependencyequivalents", "tilesets", "names", "ubertip",
             "tip", "untip", "unubertip", "art", "missileart", "buttonpos"}
SLK_LABEL = {
    "race": "种族", "def": "护甲", "deftype": "护甲类型", "hp": "生命", "realhp": "生命",
    "mann": "魔法", "manan": "魔法", "regenhp": "生命回复", "regenmana": "魔法回复",
    "goldcost": "金币", "lumbercost": "木材", "fmade": "提供人口", "fused": "占用人口",
    "level": "等级", "spd": "移动速度", "sight": "白天视野", "nsight": "夜晚视野",
    "movetp": "移动类型", "bountydice": "赏金骰子", "bountyplus": "赏金基础",
    "dmgplus1": "攻击力", "dice1": "攻击骰子", "sides1": "骰面", "cool1": "攻击间隔",
    "rangen1": "攻击距离", "atktype1": "攻击类型", "targs1": "可攻击目标",
    "class": "分类", "cooldownid": "冷却组", "stockmax": "库存上限", "uses": "使用次数",
    "abillist": "技能", "hero": "英雄技能", "item": "物品技能", "levels": "等级数",
    "maxlevel": "最大等级", "goldbase": "基础金", "goldmod": "金增量",
    "lumberbase": "基础木", "lumbermod": "木增量", "global": "全局",
}


def build_base_objects(archives):
    from w3xtool.slk import parse_slk

    def read(fn):
        for a in archives:
            if a.has_file(fn):
                return a.read_file(fn).decode("utf-8", "replace")
        return None

    def load_merge(files):
        merged = {}
        for fn in files:
            t = read("Units\\" + fn)
            if not t:
                continue
            for code, row in parse_slk(t).items():
                merged.setdefault(code, {}).update(row)
        return merged

    groups = {
        "单位": ["UnitData.slk", "UnitBalance.slk", "UnitUI.slk", "UnitWeapons.slk", "UnitAbilities.slk"],
        "物品": ["ItemData.slk"],
        "技能": ["AbilityData.slk"],
        "科技": ["UpgradeData.slk"],
    }
    out = {}
    for cat, files in groups.items():
        for code, row in load_merge(files).items():
            fields = []
            for k, v in row.items():
                if k.lower() in SLK_NOISE or not str(v).strip() or str(v) == "0":
                    continue
                fields.append((SLK_LABEL.get(k.lower(), k), str(v)))
            out[code] = (cat, fields[:24])
    lines = ["# 自动生成：游戏基础对象默认字段(来自 *Data.slk)。由 build_base_names.py 提取。",
             "# 请勿手改。", "", "BASE_OBJECTS = {"]
    for code in sorted(out):
        cat, fields = out[code]
        fl = ", ".join(f'("{lab}", {val!r})' for lab, val in fields)
        lines.append(f'    {code!r}: ({cat!r}, [{fl}]),')
    lines.append("}")
    with open("w3xtool/base_objects.py", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"已写出 w3xtool/base_objects.py（{len(out)} 个基础对象）")


if __name__ == "__main__":
    main()
