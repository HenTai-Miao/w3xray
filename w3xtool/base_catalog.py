"""Runtime lookups over the generated base-catalog tables.

统一 细类/英文名 的 base-first 查询语义，避免各消费点各写一份
`BASE_CATEGORIES.get(base_id) or get(obj_id)` 而发生漂移。
"""

from __future__ import annotations

from .base_names import BASE_CATEGORIES, BASE_NAMES_EN


def fine_category_for(base_id: str, obj_id: str = "") -> str:
    """标准化细类中文名（基础码优先），未知返回空串。"""
    fine = BASE_CATEGORIES.get(base_id) or BASE_CATEGORIES.get(obj_id)
    return "" if fine is None else fine[0]


def english_name_for(base_id: str, obj_id: str = "") -> str:
    """英文名（基础码优先，自定义对象显示其原版基底），未知返回空串。"""
    return BASE_NAMES_EN.get(base_id) or BASE_NAMES_EN.get(obj_id) or ""
