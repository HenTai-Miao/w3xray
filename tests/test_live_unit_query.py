# -*- coding: utf-8 -*-
"""live --unit 过滤: 名字/四码匹配逻辑与 CLI 解析。"""

from __future__ import annotations

import pytest

from w3xtool.live_cli import LiveCliOptionError, parse_live_cli_options
from w3xtool.live_handle_chain import match_unit_entries

UNITS = [
    {"unit": "寒冰游侠", "code": "H004", "items": []},
    {"unit": "黑暗之源", "code": "N02A", "items": []},
    {"unit": "宝宝", "code": "h00X", "items": []},
]


def test_match_by_exact_code():
    assert [u["code"] for u in match_unit_entries(UNITS, "H004")] == ["H004"]
    assert [u["code"] for u in match_unit_entries(UNITS, "h00x")] == ["h00X"]


def test_match_by_name_substring():
    got = match_unit_entries(UNITS, "寒冰")
    assert [u["unit"] for u in got] == ["寒冰游侠"]
    got = match_unit_entries(UNITS, "黑暗之源")
    assert [u["unit"] for u in got] == ["黑暗之源"]


def test_match_full_name_query_over_short_unit():
    got = match_unit_entries(UNITS, "宝宝一号")
    assert [u["unit"] for u in got] == ["宝宝"]


def test_match_empty_and_miss():
    assert match_unit_entries(UNITS, "") == UNITS
    assert match_unit_entries(UNITS, "不存在的单位") == []


def test_parse_unit_option():
    opts = parse_live_cli_options(["地图.w3x", "--unit", "寒冰游侠"])
    assert opts.unit_query == "寒冰游侠"
    opts = parse_live_cli_options(["--pack", "p", "--unit", "H004"])
    assert opts.unit_query == "H004"


def test_parse_unit_requires_value():
    with pytest.raises(LiveCliOptionError):
        parse_live_cli_options(["地图.w3x", "--unit"])
    with pytest.raises(LiveCliOptionError):
        parse_live_cli_options(["地图.w3x", "--unit", "--strategy", "auto"])


def test_parse_unit_not_repeatable():
    with pytest.raises(LiveCliOptionError):
        parse_live_cli_options(["地图.w3x", "--unit", "A", "--unit", "B"])
