"""一次性脚本：从 common.j / blizzard.j 提取派生事实表，生成 w3xtool/jass_natives.py。

只抽取派生事实（native 参数的对象类别、BJ 函数体里的对象码、bj_*_CODE 常量），
不复制 .j 本身——与 build_base_names.py 从游戏数据离线生成同一立场，运行时零依赖。

注意：.j 文件**不随仓库**（Blizzard 版权 + 体积），仓库里提交的是烤好的产物
`w3xtool/jass_natives.py`，那才是运行时唯一依赖。仅在需要**重新生成**该表时才用本脚本，
此时需自备 common.j / blizzard.j（如外部魔兽工具包/游戏目录）并用 --src 指向其目录。

用法：
    python build_jass_natives.py --src "D:/path/to/system"   # 目录含 ht/rb 或直接含 *.j
    python build_jass_natives.py                             # 用 DEFAULT_SRC（仅本机生成时方便）
"""
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DEFAULT_SRC = (r"C:/Users/zhongerbing/Downloads/魔兽ID拖入无反应解决方法/"
               r"拖入无反应解决方法/优化2/bin/system")

# native 的整数参数名 → 对象分类（精确名白名单）。
# 关键：order/orderId(命令串)、itemSlot(槽位号)、unitType(handle) 等是整数但非对象引用，不收。
PARAM_CAT = {
    "unitid": "单位", "unitId": "单位", "portraitUnitId": "单位",
    "itemid": "物品", "itemId": "物品",
    "abilcode": "技能", "abilityId": "技能", "abilid": "技能",
    "techid": "科技", "techId": "科技",
    "objectid": "可破坏物", "objectId": "可破坏物",
    "buffId": "增益",
}

# 参数名虽命中 PARAM_CAT，但函数本身是**泛型**（对任意对象 id 通用），按参数名归类会错。
# 如 GetObjectName(integer objectId) 是取任意对象本地化名，与 CreateDestructable 共用 objectId
# 参数名，会把技能/科技码误判成可破坏物。这类显式排除，不进 NATIVE_OBJ_FUNCS。
EXCLUDE_NATIVES = {"GetObjectName"}

# curated BJ：函数名 → 中文特征标签。生成器从 blizzard.j 各函数体抽 rawcode 当隐式引用码。
# 名单只取"能说明地图机制/用了哪些基础对象"的函数（缺失的自动跳过）。
CURATED_BJ = {
    "MeleeStartingUnitsHuman": "人族对战开局",
    "MeleeStartingUnitsOrc": "兽族对战开局",
    "MeleeStartingUnitsUndead": "亡灵对战开局",
    "MeleeStartingUnitsNightElf": "暗夜对战开局",
    "MeleeStartingUnitsHumanWithoutHeroes": "人族对战开局(无英雄)",
    "MeleeStartingUnitsOrcWithoutHeroes": "兽族对战开局(无英雄)",
    "MeleeStartingUnitsUndeadWithoutHeroes": "亡灵对战开局(无英雄)",
    "MeleeStartingUnitsNightElfWithoutHeroes": "暗夜对战开局(无英雄)",
    "MeleeStartingResources": "对战起始资源",
    "MeleeStartingHeroLimit": "对战英雄上限",
    "MeleeGrantItemsToHero": "对战英雄初始物品",
    "ChooseRandomItemBJ": "随机物品",
    "ChooseRandomItemExBJ": "随机物品(按等级)",
    "InitNeutralBuildings": "中立建筑(商店/酒馆等)",
}


def _read(path):
    with open(path, "r", encoding="latin-1") as f:
        return f.read()


def _find_src_files(src):
    """在 src 下找 common.j / blizzard.j（支持 ht/rb 子目录），返回路径列表（去重并集用）。"""
    found = []
    for root, _dirs, files in os.walk(src):
        for fn in files:
            if fn.lower() in ("common.j", "blizzard.j"):
                found.append(os.path.join(root, fn))
    return found


_NATIVE = re.compile(
    r"(?:constant\s+)?native\s+(\w+)\s+takes\s+(.*?)\s+returns\b", re.DOTALL)


def parse_native_obj_funcs(common_texts):
    """common.j → {native名: 分类|None}。仅收带对象码参数的 native；多类冲突→None。"""
    out = {}
    for text in common_texts:
        for m in _NATIVE.finditer(text):
            name, params = m.group(1), m.group(2).strip()
            if params == "nothing" or name in EXCLUDE_NATIVES:
                continue
            cats = set()
            for part in params.split(","):
                toks = part.split()
                if len(toks) < 2:
                    continue
                ptype, pname = toks[0], toks[1]
                if ptype == "integer" and pname in PARAM_CAT:
                    cats.add(PARAM_CAT[pname])
            if not cats:
                continue
            cat = next(iter(cats)) if len(cats) == 1 else None
            # 同名 native 在 ht/rb 都出现：分类一致则保留；冲突保守置 None
            if name in out and out[name] != cat:
                out[name] = None
            else:
                out[name] = cat
    return out


_FUNC_BODY = r"^function {name}\b.*?^endfunction"
_RAWCC = re.compile(r"'([A-Za-z0-9]{4})'")


def parse_bj_func_codes(blizzard_texts):
    """blizzard.j → {curated BJ名: [body 里的 rawcode]}（按 CURATED_BJ 名单）。"""
    out = {}
    for fname in CURATED_BJ:
        codes = []
        for text in blizzard_texts:
            m = re.search(_FUNC_BODY.format(name=re.escape(fname)), text,
                          re.DOTALL | re.MULTILINE)
            if not m:
                continue
            for cc in _RAWCC.findall(m.group(0)):
                if cc not in codes:
                    codes.append(cc)
        if codes:
            out[fname] = codes
    return out


_BJ_CODE_CONST = re.compile(
    r"constant\s+integer\s+(bj_\w*CODE\w*)\s*=\s*'([A-Za-z0-9]{4})'")


def parse_bj_code_constants(blizzard_texts):
    out = {}
    for text in blizzard_texts:
        for name, code in _BJ_CODE_CONST.findall(text):
            out.setdefault(name, code)
    return out


def _fmt_dict(d, valfmt):
    lines = []
    for k in d:
        lines.append(f"    {k!r}: {valfmt(d[k])},")
    return "\n".join(lines)


def main():
    src = DEFAULT_SRC
    if "--src" in sys.argv:
        src = sys.argv[sys.argv.index("--src") + 1]
    files = _find_src_files(src)
    commons = [_read(p) for p in files if os.path.basename(p).lower() == "common.j"]
    blizzards = [_read(p) for p in files if os.path.basename(p).lower() == "blizzard.j"]
    if not commons or not blizzards:
        print(f"[build_jass_natives] 在 {src} 未找到 common.j / blizzard.j", file=sys.stderr)
        print("  找到:", [os.path.basename(p) for p in files], file=sys.stderr)
        sys.exit(1)

    native_funcs = parse_native_obj_funcs(commons)
    bj_codes = parse_bj_func_codes(blizzards)
    bj_features = dict(CURATED_BJ)               # 特征标签全保留（即便某 BJ 体内无 rawcode 也算特征命中）
    bj_const = parse_bj_code_constants(blizzards)

    out_path = os.path.join("w3xtool", "jass_natives.py")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# 自动生成：从 common.j/blizzard.j 提取的 native 参数对象类别 & BJ 隐式引用码。\n")
        f.write("# 由 build_jass_natives.py 生成，重跑可刷新。请勿手改。\n\n")
        f.write("# native名 → 对象分类（None=有对象码参数但多类/不确定）\n")
        f.write("NATIVE_OBJ_FUNCS = {\n")
        f.write(_fmt_dict(native_funcs, lambda v: repr(v)))
        f.write("\n}\n\n")
        f.write("# 暴雪 BJ 函数 → 函数体里硬编码的对象码（脚本调用即隐式引用这些基础对象）\n")
        f.write("BJ_FUNC_CODES = {\n")
        f.write(_fmt_dict(bj_codes, lambda v: repr(v)))
        f.write("\n}\n\n")
        f.write("# BJ 函数名 → 中文地图特征标签（脚本命中即该图用了此机制）\n")
        f.write("BJ_FEATURES = {\n")
        f.write(_fmt_dict(bj_features, lambda v: repr(v)))
        f.write("\n}\n\n")
        f.write("# bj_*_CODE 命名常量 → 对象码（电梯等）\n")
        f.write("BJ_CODE_CONSTANTS = {\n")
        f.write(_fmt_dict(bj_const, lambda v: repr(v)))
        f.write("\n}\n")

    print(f"[build_jass_natives] 写出 {out_path}")
    print(f"  NATIVE_OBJ_FUNCS={len(native_funcs)}  BJ_FUNC_CODES={len(bj_codes)}"
          f"  BJ_FEATURES={len(bj_features)}  BJ_CODE_CONSTANTS={len(bj_const)}")


if __name__ == "__main__":
    main()
