"""Typed builders for complete-text priority tests."""

from __future__ import annotations

from w3xtool.client_object_data import ClientBaseObject
from w3xtool.description_cache import EMPTY_DESCRIPTION_CACHE, DescriptionCache
from w3xtool.map_data import GameObject
from w3xtool.object_candidates import (
    ObjectCandidate,
    ObjectFieldValue,
    ObjectSourceKind,
)
from w3xtool.object_text_index import build_object_text_index
from w3xtool.object_text_models import ObjectTextIndex


def build_text_index(
    category: str,
    object_id: str,
    base_id: str,
    fields: tuple[ObjectFieldValue, ...],
    *,
    client_objects: tuple[ClientBaseObject, ...] = (),
    cache: DescriptionCache = EMPTY_DESCRIPTION_CACHE,
    client_text_available: bool = False,
) -> ObjectTextIndex:
    """Build one object index from exact test evidence."""
    ext = "w3u" if category == "单位" else "w3t" if category == "物品" else "w3a"
    obj = GameObject(category, ext, object_id, base_id, object_id, True)
    candidate = ObjectCandidate(category, object_id, base_id, True, ext, fields, ())
    return build_object_text_index(
        (obj,),
        (candidate,),
        client_objects,
        cache,
        client_text_available=client_text_available,
    )


def text_field(
    key: str,
    label: str,
    value: str,
    source: str,
    source_kind: ObjectSourceKind,
) -> ObjectFieldValue:
    """Create one metadata-confirmed string field."""
    return ObjectFieldValue(
        key,
        label,
        value,
        source,
        source_kind,
        value_type="string",
    )


def index_with_name_sources() -> ObjectTextIndex:
    """Build one unit name with Strings, binary, and SLK variants."""
    return build_text_index(
        "单位",
        "H001",
        "Hpal",
        (
            text_field(
                "unam",
                "名称",
                "地图文本名称",
                "war3map.wts",
                ObjectSourceKind.TEXT_STRINGS,
            ),
            text_field(
                "unam",
                "名称",
                "地图二进制名称",
                "war3map.w3u",
                ObjectSourceKind.BINARY,
            ),
            text_field(
                "unam",
                "名称",
                "地图SLK名称",
                "UnitData.slk",
                ObjectSourceKind.SLK,
            ),
        ),
    )


def index_with_binary_conflict_and_slk_value() -> ObjectTextIndex:
    """Build a binary conflict with one lower-priority SLK value."""
    return build_text_index(
        "技能",
        "A001",
        "AHbz",
        (
            text_field(
                "aub1:1",
                "提示工具 - 扩展的 (等级1)",
                "二进制甲",
                "map.w3a#1",
                ObjectSourceKind.BINARY,
            ),
            text_field(
                "aub1:1",
                "提示工具 - 扩展的 (等级1)",
                "二进制乙",
                "map.w3a#2",
                ObjectSourceKind.BINARY,
            ),
            text_field(
                "aub1:1",
                "提示工具 - 扩展的 (等级1)",
                "SLK旧值",
                "AbilityData.slk",
                ObjectSourceKind.SLK,
            ),
        ),
    )


__all__ = (
    "build_text_index",
    "index_with_binary_conflict_and_slk_value",
    "index_with_name_sources",
    "text_field",
)
