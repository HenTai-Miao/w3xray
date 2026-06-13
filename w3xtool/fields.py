"""对象字段 4 字符码 → 中文标签。

两层：下面手工精选的常用字段（标签更口语、优先用）；其余回退到
`field_meta.py` 的全量生成表（1400+ 字段，由 build_field_labels.py 从
MetaData.slk + westrings 离线生成）。两层都没有才显示原始 4 字符。
"""
from __future__ import annotations

try:
    from .field_meta import GENERATED_FIELD_LABELS, FIELD_TYPES
except Exception:                       # 生成数据缺失时退化为仅精选表
    GENERATED_FIELD_LABELS = {}
    FIELD_TYPES = {}

# 每类对象的"名称"字段码
NAME_FIELD = {
    "w3u": "unam",   # 单位
    "w3t": "unam",   # 物品
    "w3a": "anam",   # 技能
    "w3q": "gnam",   # 科技/升级
    "w3b": "bnam",   # 可破坏物
    "w3d": "dnam",   # 装饰物
    "w3h": "fnam",   # 增益
}

# 常用字段标签
FIELD_LABELS = {
    # 通用 / 单位
    "unam": "名称", "unsf": "后缀名", "upra": "主属性", "urac": "种族",
    "umdl": "模型", "ussc": "缩放", "uico": "图标",
    "uhpm": "生命上限", "umpm": "魔法上限", "uhpr": "生命回复", "umpr": "魔法回复",
    "ustr": "力量", "uagi": "敏捷", "uint": "智力",
    "ustp": "力量成长", "uagp": "敏捷成长", "uinp": "智力成长",
    "ulev": "等级", "uhos": "占用人口", "ufoo": "提供人口",
    "ua1d": "攻击间隔", "ua1b": "基础攻击", "ua1c": "攻击次数",
    "udp1": "攻击力骰子", "usi1": "骰子面数", "udef": "护甲",
    "umvs": "移动速度", "uspe": "移动类型", "usin": "视野(白天)", "usip": "视野(夜晚)",
    "ucol": "碰撞体积", "uabi": "技能列表", "uhab": "英雄技能",
    "upgr": "可升级科技", "ucbs": "选择圈大小",
    "ugol": "金币花费", "ulum": "木材花费", "ubld": "建造时间",
    # 物品
    "ides": "描述", "utub": "提示文本", "utip": "工具提示", "iabi": "携带技能",
    "igol": "金币价值", "ilum": "木材价值", "ilev": "物品等级", "iico": "图标",
    "icla": "物品分类", "ipri": "优先级", "iperD": "完美", "idrop": "可掉落",
    "ilvo": "等级(隐藏)", "iusn": "使用次数", "icid": "冷却组",
    "ifil": "替换列表", "iclb": "战利品掉落",
    # 技能
    "anam": "名称", "ansf": "后缀", "arac": "种族", "aret": "学习提示",
    "arut": "未学习提示", "atp1": "提示", "aub1": "扩展提示", "aical": "图标",
    "adur": "持续时间", "ahdu": "英雄持续", "acdn": "冷却", "amcs": "魔法消耗",
    "aare": "作用范围", "aran": "施法距离", "acas": "施法次数", "alev": "等级数",
    "abuf": "buff效果", "aeff": "效果", "Hbz1": "数据",
    # 科技 / 升级
    "gnam": "名称", "gtp1": "提示", "gub1": "扩展提示", "glvl": "等级数",
    "gef1": "效果", "gglb": "基础金币", "gglm": "金币增量",
    "gtib": "基础木材", "gtim": "木材增量", "greq": "依赖科技", "gico": "图标",
}


# 多值（逗号/竖线分隔的码或词列表）字段类型——展示时拆开逐项还原（借鉴 w3x2lni concat_types）
CONCAT_TYPES = {
    "abilityList", "unitList", "buffList", "techList", "itemList",
    "targetList", "effectList", "stringList", "unitClass", "modelList",
    "lightningList", "intList", "unrealList", "upgradeList",
    "pathingListPrevent", "pathingListRequire", "tilesetList",
    "abilCodeList", "abilSkinList",
}


def is_concat_type(field_id: str) -> bool:
    return field_type(field_id) in CONCAT_TYPES


def label_for(field_id: str) -> str:
    """精选标签优先 → 全量生成标签兜底 → 都没有则原样返回 4 字符码。"""
    return (FIELD_LABELS.get(field_id)
            or GENERATED_FIELD_LABELS.get(field_id)
            or field_id)


def field_type(field_id: str) -> str:
    """字段类型（int/real/string/abilityList…），来自 MetaData.slk；未知返回空串。"""
    return FIELD_TYPES.get(field_id, "")
