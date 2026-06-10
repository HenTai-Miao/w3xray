"""一次性脚本：从游戏数据提取 原版对象 码→中文名/默认字段，生成 w3xtool/*.py。

经典版（<=1.29，MPQ）：默认从 war3/{war3,War3x,War3Patch,War3xLocal}.mpq 读
    Units\\*Strings.txt / *Func.txt / *Data.slk。可用 --game 覆盖安装目录。
重制版（1.30+，CASC）：游戏数据改为 CASC，本脚本不内置 CASC 读取。先用 CascView
    或 wc3tools/casc-extract 把 war3.w3mod 下的 units/* 等导到一个文件夹，再：
        python build_base_names.py --from-dir <该文件夹>
    匹配大小写/斜杠不敏感、容忍 war3.w3mod\\ 前缀；--from-dir 会打印找到/未找到清单。
重装/换语言/升级后可重跑本脚本刷新。
"""
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from w3xtool.mpq import MPQArchive


class DirSource:
    """把一个普通文件夹伪装成与 MPQArchive 同接口的数据源（has_file/read_file）。

    用于读 CASC/重制版数据：先用 CascView 或 wc3tools/casc-extract 把游戏文件导到
    一个文件夹，再让本脚本从该文件夹读。匹配大小写不敏感、斜杠方向不敏感，并容忍
    war3.w3mod\\ 等命名空间前缀。
    """

    def __init__(self, root):
        if not os.path.isdir(root):
            raise FileNotFoundError(f"--from-dir 目录不存在: {root}")
        self.root = root
        self._by_rel = {}        # 规范化相对路径 -> 实际磁盘绝对路径
        self._by_base = {}       # 文件名(小写) -> [规范化相对路径, ...]
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                full = os.path.join(dirpath, fn)
                norm = os.path.relpath(full, root).replace("\\", "/").lower()
                self._by_rel[norm] = full
                self._by_base.setdefault(fn.lower(), []).append(norm)
        if not self._by_rel:
            raise FileNotFoundError(f"--from-dir 目录为空（无任何文件）: {root}")

    @staticmethod
    def _norm(name):
        return name.replace("\\", "/").lstrip("/").lower()

    def _resolve(self, name):
        q = self._norm(name)
        # 1. 精确相对路径
        if q in self._by_rel:
            return self._by_rel[q]
        # 2. 以查询路径结尾（吃掉 war3.w3mod/ 等命名空间前缀）
        cands = [r for r in self._by_rel if r.endswith("/" + q)]
        if cands:
            best = min(cands, key=len)
            if len(cands) > 1:
                print(f"  [warning] {name} 有 {len(cands)} 个候选，取最短: {best}")
            return self._by_rel[best]
        # 3. 文件名兜底
        bcands = self._by_base.get(q.rsplit("/", 1)[-1], [])
        if bcands:
            best = min(bcands, key=len)
            if len(bcands) > 1:
                print(f"  [warning] {name} 按文件名有 {len(bcands)} 个候选，取最短: {best}")
            return self._by_rel[best]
        return None

    def has_file(self, name):
        return self._resolve(name) is not None

    def read_file(self, name):
        path = self._resolve(name)
        if path is None:
            raise FileNotFoundError(name)
        with open(path, "rb") as f:
            return f.read()


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


WESTRING_FILES = [r"UI\WorldEditStrings.txt", r"UI\WorldEditGameStrings.txt"]


def report_dir_coverage(src):
    """文件夹模式：打印关键文件找到/未找到清单，便于排查重制版布局差异。"""
    slk = ["Units\\" + f for fs in SLK_GROUPS.values() for f in fs]
    groups = [("名称(Strings/Func)", FILES), ("基础字段(SLK)", slk),
              ("编辑器字符串", WESTRING_FILES)]
    print("\n[--from-dir 覆盖报告]")
    for label, files in groups:
        missing = [f for f in files if not src.has_file(f)]
        print(f"  {label}: 找到 {len(files) - len(missing)}/{len(files)}")
        for m in missing:
            print(f"    未找到 {m}")


def build_sources(args):
    """按 CLI 参数返回数据源列表。

    --from-dir: 单个 DirSource（CASC 已是当前 build 最终态，无需多层覆盖）。
    否则: 经典 MPQ 列表（低->高优先级，后者覆盖前者）。
    """
    if getattr(args, "from_dir", None):
        return [DirSource(args.from_dir)]
    game = getattr(args, "game", None) or GAME
    sources = []
    for mq in MPQS:
        try:
            sources.append(MPQArchive(f"{game}/{mq}"))
        except Exception as e:
            print("跳过", mq, e)
    return sources


def main(args):
    out_dir = getattr(args, "out_dir", None) or "w3xtool"
    names = {}
    total_files = 0
    archives = build_sources(args)
    if getattr(args, "from_dir", None):
        report_dir_coverage(archives[0])
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
    with open(os.path.join(out_dir, "base_names.py"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"已写出 {os.path.join(out_dir, 'base_names.py')}")
    # 抽查
    for c in ("hfoo", "nckb", "Hblm", "ratf", "Rhme"):
        print(f"  {c} -> {names.get(c, '(无)')}")

    # ---- 同时提取 WESTRING_ 编辑器字符串（地图对象常引用，如可破坏物名）----
    west = {}
    we_re = re.compile(r"^(WESTRING_\w+)\s*=\s*(.*)$")
    for a in archives:                      # 后面的(补丁/本地化)覆盖前面的
        for fn in WESTRING_FILES:
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
    with open(os.path.join(out_dir, "westrings.py"), "w", encoding="utf-8") as f:
        f.write("\n".join(wl) + "\n")
    print(f"已写出 {os.path.join(out_dir, 'westrings.py')}（{len(west)} 条）")

    build_base_objects(archives, out_dir)


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
SLK_GROUPS = {
    "单位": ["UnitData.slk", "UnitBalance.slk", "UnitUI.slk", "UnitWeapons.slk", "UnitAbilities.slk"],
    "物品": ["ItemData.slk"],
    "技能": ["AbilityData.slk"],
    "科技": ["UpgradeData.slk"],
}


def build_base_objects(archives, out_dir):
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

    out = {}
    for cat, files in SLK_GROUPS.items():
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
    with open(os.path.join(out_dir, "base_objects.py"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"已写出 {os.path.join(out_dir, 'base_objects.py')}（{len(out)} 个基础对象）")


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(
        description="从游戏数据生成原版对象内置数据（base_names/base_objects/westrings）")
    p.add_argument("--from-dir", dest="from_dir",
                   help="从已提取的散文件夹读（CASC/重制版：先用 CascView 或 "
                        "casc-extract 导出，再指向该文件夹）")
    p.add_argument("--game", help="经典 MPQ 安装目录（默认硬编码 GAME 路径）")
    p.add_argument("--out-dir", dest="out_dir", default="w3xtool",
                   help="生成的 .py 写到哪个目录（默认 w3xtool）")
    main(p.parse_args())
