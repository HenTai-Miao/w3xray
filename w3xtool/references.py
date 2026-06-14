"""对象引用分析（只读）：谁引用了谁、谁没人引用。

把「魔兽ID拖入无反应解决方法」工具包(Wc3SLKOpt / Wc3MapMax++)里
`Config.ini [SearchObjectData]` 那张"哪些字段指向别的对象"的知识，落成本工具的
**只读**分析——不照搬它的改图/重打包/裁剪未用对象功能（与本工具定位不符）。

两条取边路线，汇进同一份引用边：
- 二进制对象(w3u/w3t/…)：**类型驱动**——字段类型(FIELD_TYPES)属于引用类即视为引用字段。
- 文本格式对象档(textobj，键是 abilList 这类 SLK 列名)：**列名驱动**——用取自优化器的列名表。

接口：
- extract_refs_by_type(mods)  → [(field_id, [code…])]  给二进制对象用
- extract_refs_by_column(fields, category) → [(column, [code…])]  给文本对象用
- build_reference_graph(md)    填 md.references / md.referenced_by / md.orphans
"""
from __future__ import annotations

import re

_LEVEL_LABEL_RE = re.compile(r" \(等级\d+\)$")   # 反向去重时剥掉标签里的"(等级N)"

# 引用类型(FIELD_TYPES 的值) → 目标分类。仅列"值是对象 4cc 码/码列表"的类型；
# intList/unrealList/stringList/modelList/targetList/unitClass 等是数值/字符串/枚举，非引用。
# 注意：value(目标分类)仅作**说明性**——代码只用 `in REF_TYPES`(成员判定)，实际归类靠
# 引用码在 obj_index 里查到的真实对象，故个别 value 不精确(如 effectList)不影响正确性。
REF_TYPES = {
    "abilCode": "技能", "abilityList": "技能", "heroAbilityList": "技能",
    "unitCode": "单位", "unitList": "单位",
    "itemList": "物品",
    "upgradeCode": "科技", "upgradeList": "科技", "techList": "科技",
    "buffList": "增益", "effectList": "增益",
}

# 文本格式对象档(SLK 列名)引用列 → 目标分类。取自优化器 [SearchObjectData]。
# 键是中文分类(与 EXT_CATEGORY 对齐)，值是 {列名: 目标分类}。
REF_COLUMNS = {
    "单位": {
        "abilList": "技能", "heroAbilList": "技能",
        "Makeitems": "物品", "Sellitems": "物品",
        "Builds": "单位", "Sellunits": "单位", "Trains": "单位", "Reviveat": "单位",
        "Upgrade": "单位", "DependencyOr": "单位",
        "Researches": "科技", "upgrades": "科技", "Requires": "科技",
        "Requires1": "科技", "Requires2": "科技", "Requires3": "科技", "Requires4": "科技",
        "Requires5": "科技", "Requires6": "科技", "Requires7": "科技", "Requires8": "科技",
    },
    "物品": {
        "abilList": "技能", "cooldownID": "技能", "Requires": "科技",
    },
    "技能": {
        "BuffID": "增益", "EfctID": "增益", "Requires": "科技",
        # SLK 技能数据按等级后缀分列：BuffID1..4(buff)、EfctID1..4(效果)、UnitID1..4(召唤/创建单位)
        "BuffID1": "增益", "BuffID2": "增益", "BuffID3": "增益", "BuffID4": "增益",
        "EfctID1": "增益", "EfctID2": "增益", "EfctID3": "增益", "EfctID4": "增益",
        "UnitID1": "单位", "UnitID2": "单位", "UnitID3": "单位", "UnitID4": "单位",
    },
    "科技": {
        "Requires": "科技",
        "code1": "科技", "code2": "科技", "code3": "科技", "code4": "科技",
    },
}


# 4 字符但绝非对象码的"词/枚举/标志"值（targs 等字段里常见），防御性剔除。
# 仅收明确不会与真实对象码(如 hpea/ngol/A001)冲突的词；宁缺勿滥，避免误删真码。
_NOT_A_CODE = {"self", "none", "true", "null", "dead", "tree", "both", "item"}


def _split_codes(value) -> list:
    """把字段值拆成 4cc 码列表。单值(单 4cc)与逗号列表都走这里；过滤空/占位/非码。"""
    if not isinstance(value, str):
        return []
    out = []
    for tok in value.replace("|", ",").split(","):
        t = tok.strip().strip("\x00")
        # 对象码恒为 4 字符；剔除 _ / - / 0 这类"空"占位与纯数字(多为计数而非码)
        if len(t) != 4 or t in ("____", "----", "0000"):
            continue
        if t.isdigit() or t in _NOT_A_CODE:
            continue
        out.append(t)
    return out


def extract_refs_by_type(mods, field_type) -> list:
    """二进制对象：遍历原始 mods，类型属于 REF_TYPES 的字段即引用字段。

    mods: 可迭代的 Modification(有 .field_id / .value)。
    field_type: 形如 fields.field_type 的函数，field_id → 类型字符串。
    返回 [(field_id, [code…])]，去掉无码的。
    """
    # 按 field_id 聚合并去重：w3a/w3q 的引用字段会逐等级各出现一次(同 field_id 多条)，
    # 若不聚合，同一引用会重复成边(反向"被谁引用"里出现多条相同项)。这里按 field_id 合并去重。
    agg: dict = {}
    order = []
    for m in mods:
        if field_type(m.field_id) in REF_TYPES:
            for c in _split_codes(m.value):
                lst = agg.get(m.field_id)
                if lst is None:
                    lst = agg[m.field_id] = []
                    order.append(m.field_id)
                if c not in lst:
                    lst.append(c)
    return [(fid, agg[fid]) for fid in order]


def extract_refs_by_column(fields: dict, category: str) -> list:
    """文本对象：按 category 的引用列名表取引用列。

    fields: {列名: 值字符串}。category: 中文分类。
    返回 [(列名, [code…])]。
    """
    cols = REF_COLUMNS.get(category)
    if not cols:
        return []
    refs = []
    for col in cols:
        if col in fields:
            codes = _split_codes(fields[col])
            if codes:
                refs.append((col, codes))
    return refs


def _best_script(md) -> str:
    for name in ("war3map.j", "war3map.lua"):
        text = md.scripts.get(name)
        if text and text.strip("\x00\r\n\t "):
            return text
    return ""


def build_reference_graph(md) -> None:
    """计算引用图并填到 md：references(正向) / referenced_by(反向) / orphans(孤立自定义对象)。

    只读分析，不改对象。对象的原始引用字段已在 _build_objects/_add_text_objects 抓到
    GameObject.ref_fields = [(字段标签, [code…])]；这里建图、还原名字、算孤立。
    """
    from .fields import label_for
    from .slk_objects import slk_col_label
    try:
        from .base_names import BASE_NAMES      # 引用到的原版对象(如标准 buff)未作为对象加载时，回退取原版名
    except Exception:
        BASE_NAMES = {}

    def _label(field_key):
        # 二进制对象字段是 4cc → label_for 直接译；SLK/文本对象字段是列名，
        # label_for 查不到会原样返回，此时再用 slk_col_label(含等级后缀中文化)。
        lab = label_for(field_key)
        return lab if lab != field_key else slk_col_label(field_key)

    references: dict = {}
    referenced_by: dict = {}
    seen_edges: set = set()                     # (被引码, 引用者id, 标签) 去重，防重复边
    obj_index = md.obj_index

    all_objects = [o for objs in md.objects.values() for o in objs]
    for o in all_objects:
        ref_fields = getattr(o, "ref_fields", None)
        if not ref_fields:
            continue
        entries = []
        for field_key, codes in ref_fields:
            label = _label(field_key)
            resolved = []
            seen_codes = set()
            for code in codes:
                if code in seen_codes:
                    continue
                seen_codes.add(code)
                target = obj_index.get(code)
                # 名字：已加载对象优先；否则回退原版名(标准 buff/单位等未当对象加载时也有名)
                name = target.name if target is not None else BASE_NAMES.get(code)
                resolved.append((code, name))
                if code == o.obj_id:            # 跳过自引用：否则对象会被自己挡在"孤立"之外
                    continue
                # 反向"被谁引用"按去等级的基础标签去重：SLK 的 BuffID1..4 等逐级列
                # 否则会让同一引用者重复 4 条；正向 references 仍保留逐级明细。
                base_label = _LEVEL_LABEL_RE.sub("", label)
                key = (code, o.obj_id, base_label)
                if key not in seen_edges:
                    seen_edges.add(key)
                    referenced_by.setdefault(code, []).append((o.obj_id, o.name, base_label))
            if resolved:
                entries.append((label, resolved))
        if entries:
            references[o.obj_id] = entries

    # 根集合：被脚本引用 / 预放置在地图上的类型 —— 这些即便没被别的对象引用也不算"孤立"。
    roots = set(referenced_by.keys())
    try:
        from .script_scan import scan_all_referenced_codes
        script_text = _best_script(md)
        if script_text:
            # 全类 native 提码 + 所有 'xxxx' 字面量 + BJ 隐式码，孤立判定宁滥勿缺
            roots.update(scan_all_referenced_codes(script_text))
    except Exception:
        pass
    for u in getattr(md, "units", []) or []:
        roots.add(getattr(u, "type_id", ""))
    for d in getattr(md, "doodads", []) or []:
        roots.add(getattr(d, "type_id", ""))

    # 孤立：自定义、且其 ID 不在根集合里（没被任何对象/脚本/预放置引用）。
    orphans = [o for o in all_objects
               if o.is_custom and o.obj_id not in roots]

    # 引用覆盖度自检：SLK 优化图(如 U9)把单位→技能这类**入边**放进未解析/缺失的 .slk，
    # 导致整类对象"看起来"无人引用。两条判据任一成立即判低覆盖（孤立不可全信）：
    #   (a) 自定义对象很多、却几乎没有对象暴露引用字段（连出边都没有）；
    #   (b) 某类(≥50 自定义)孤立率过高（>40%）——正常图各类孤立率远低于此(实测 6~15%)，
    #       某类半数都孤立通常是该类的入边来源(如单位的 abilList)整体缺失。
    custom = [o for o in all_objects if o.is_custom]
    with_refs = sum(1 for o in all_objects if getattr(o, "ref_fields", None))
    low = len(custom) >= 50 and with_refs < 0.15 * len(custom)
    if not low and custom:
        from collections import Counter
        cust_by_cat = Counter(o.category for o in custom)
        orph_by_cat = Counter(o.category for o in orphans)
        for cat, ncust in cust_by_cat.items():
            if ncust >= 50 and orph_by_cat.get(cat, 0) > 0.40 * ncust:
                low = True
                break
    md.ref_low_coverage = bool(low)

    md.references = references
    md.referenced_by = referenced_by
    md.orphans = orphans
