# -*- coding: utf-8 -*-
"""提取开关 (ExtractionProfile) 与游戏适配层测试。"""

from __future__ import annotations

import pytest

from gametool.extraction_profile import (
    ALL_CATEGORIES,
    CATEGORY_OBJECTS,
    CATEGORY_TRIGGERS,
    ExtractionProfile,
    normalize_profile,
    parse_profile_arg,
)
from gametool.games import get_adapter, list_adapters
from gametool.games.warcraft import WARCRAFT_ADAPTER  # noqa: F401 - 注册副作用
from gametool.knowledge_pack_contents import _allowed, _category_gate


class TestExtractionProfile:
    def test_default_all_enabled(self):
        p = ExtractionProfile()
        assert p.disabled_categories() == ()
        for cat in ALL_CATEGORIES:
            assert p.allows(cat)

    def test_normalize_partial_raw(self):
        p = normalize_profile({CATEGORY_TRIGGERS: False})
        assert not p.allows(CATEGORY_TRIGGERS)
        assert p.allows(CATEGORY_OBJECTS)

    def test_normalize_unknown_keys_ignored(self):
        p = normalize_profile({"nonexistent_key": False})
        for cat in ALL_CATEGORIES:
            assert p.allows(cat)

    def test_parse_all(self):
        assert parse_profile_arg("all").disabled_categories() == ()
        assert parse_profile_arg("").disabled_categories() == ()

    def test_parse_disable_single(self):
        p = parse_profile_arg("-triggers")
        assert not p.allows(CATEGORY_TRIGGERS)
        assert p.allows(CATEGORY_OBJECTS)

    def test_parse_mixed(self):
        p = parse_profile_arg("objects,units,-triggers,-world")
        assert not p.allows(CATEGORY_TRIGGERS)
        assert not p.allows("world")
        assert p.allows(CATEGORY_OBJECTS)
        assert p.allows("units")

    def test_parse_unknown_raises(self):
        with pytest.raises(ValueError, match="未知提取类目"):
            parse_profile_arg("-nonexistent")


class TestCategoryGate:
    def test_all_on_returns_none(self):
        gate = _category_gate(WARCRAFT_ADAPTER, ExtractionProfile())
        assert gate is None
        # gate=None 恒真
        assert _allowed(None, WARCRAFT_ADAPTER, CATEGORY_OBJECTS)

    def test_off_category_excluded(self):
        p = normalize_profile({CATEGORY_TRIGGERS: False})
        gate = _category_gate(WARCRAFT_ADAPTER, p)
        assert gate is not None
        assert CATEGORY_TRIGGERS not in gate
        assert CATEGORY_OBJECTS in gate
        assert not _allowed(gate, WARCRAFT_ADAPTER, CATEGORY_TRIGGERS)
        assert _allowed(gate, WARCRAFT_ADAPTER, CATEGORY_OBJECTS)

    def test_warcraft_groups_cover_all_categories(self):
        groups = {g.category for g in WARCRAFT_ADAPTER.export_groups}
        for cat in ALL_CATEGORIES:
            assert cat in groups, f"类目 {cat} 未登记导出组"


class TestGameRegistry:
    def test_warcraft_registered(self):
        adapter = get_adapter("warcraft")
        assert adapter.display_name == "Warcraft III"
        assert adapter.export_groups

    def test_unknown_falls_back_to_warcraft(self):
        # 未注册游戏回退魔兽适配 (MPQ 地图体系通用)
        adapter = get_adapter("some-future-game")
        assert adapter.display_name == "Warcraft III"

    def test_list_adapters_nonempty(self):
        assert list_adapters()
