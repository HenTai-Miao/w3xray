"""Runtime lookups over the generated base-catalog tables.

统一 细类/英文名 的 base-first 查询语义，避免各消费点各写一份
`BASE_CATEGORIES.get(base_id) or get(obj_id)` 而发生漂移。
"""

from __future__ import annotations

from .base_names import BASE_CATEGORIES, BASE_NAMES, BASE_NAMES_EN
from .base_objects import BASE_OBJECTS


def fine_category_for(base_id: str, obj_id: str = "", *, category: str = "") -> str:
    """标准化细类中文名（基础码优先），未知返回空串。"""
    fine = fine_category_names_for(base_id, obj_id, category=category)
    return "" if fine is None else fine[0]


def english_name_for(base_id: str, obj_id: str = "", *, category: str = "") -> str:
    """英文名（基础码优先，自定义对象显示其原版基底），未知返回空串。"""
    return next(
        (
            BASE_NAMES_EN[code]
            for code in _catalog_codes(base_id, obj_id, category)
            if BASE_NAMES_EN.get(code)
        ),
        "",
    )


def base_name_for(base_id: str, obj_id: str = "", *, category: str = "") -> str:
    """Return a bundled name only from the requested physical object category."""
    return next(
        (
            BASE_NAMES[code]
            for code in _catalog_codes(base_id, obj_id, category)
            if BASE_NAMES.get(code)
        ),
        "",
    )


def fine_category_names_for(
    base_id: str, obj_id: str = "", *, category: str = ""
) -> tuple[str, str] | None:
    """Retain both language labels after checking the category declaration."""
    return next(
        (
            BASE_CATEGORIES[code]
            for code in _catalog_codes(base_id, obj_id, category)
            if code in BASE_CATEGORIES
        ),
        None,
    )


def _catalog_codes(base_id: str, obj_id: str, category: str) -> tuple[str, ...]:
    expected = "单位" if category == "英雄" else category
    return tuple(
        code
        for code in (base_id, obj_id)
        if not expected
        or (entry := BASE_OBJECTS.get(code)) is not None
        and entry[0] == expected
    )
