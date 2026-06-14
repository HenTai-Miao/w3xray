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

# 引用类型(FIELD_TYPES 的值) → 目标分类。仅列"值是对象 4cc 码/码列表"的类型；
# intList/unrealList/stringList/modelList/targetList/unitClass 等是数值/字符串/枚举，非引用。
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
        if t.isdigit():
            continue
        out.append(t)
    return out


def extract_refs_by_type(mods, field_type) -> list:
    """二进制对象：遍历原始 mods，类型属于 REF_TYPES 的字段即引用字段。

    mods: 可迭代的 Modification(有 .field_id / .value)。
    field_type: 形如 fields.field_type 的函数，field_id → 类型字符串。
    返回 [(field_id, [code…])]，去掉无码的。
    """
    refs = []
    for m in mods:
        if field_type(m.field_id) in REF_TYPES:
            codes = _split_codes(m.value)
            if codes:
                refs.append((m.field_id, codes))
    return refs


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

    references: dict = {}
    referenced_by: dict = {}
    obj_index = md.obj_index

    all_objects = [o for objs in md.objects.values() for o in objs]
    for o in all_objects:
        ref_fields = getattr(o, "ref_fields", None)
        if not ref_fields:
            continue
        entries = []
        for field_key, codes in ref_fields:
            label = label_for(field_key)        # 4cc→中文标签；文本列名查不到则原样
            resolved = []
            for code in codes:
                target = obj_index.get(code)
                resolved.append((code, target.name if target is not None else None))
                referenced_by.setdefault(code, []).append((o.obj_id, o.name, label))
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
