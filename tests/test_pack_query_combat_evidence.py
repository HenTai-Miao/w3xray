"""Whole-object combat/skill evidence through the shared CLI/GUI query path."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.object_codes import encode_object_id_query
from gametool.pack_query_combat_evidence import combat_parameters
from gametool.pack_query_field_evidence import ObjectField
from gametool.pack_query_options import PackQueryCliOptions


_FIELD_HEADER = [
    "分类",
    "ID",
    "名称",
    "字段键",
    "字段名",
    "值",
    "来源",
    "证据状态",
    "附证",
]
_ID_HEADER = ["分类", "ID", "数值", "基础ID", "名称", "自定义", "说明"]


@pytest.fixture(autouse=True)
def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _write(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream, delimiter="\t", lineterminator="\n").writerows(rows)


def _field(
    category: str,
    code: str,
    key: str,
    value: str,
    *,
    name: str = "对象别名",
    source: str = "war3map.w3a",
    state: str = "confirmed",
    extra: str = "",
) -> list[str]:
    return [category, code, name, key, "原字段标签", value, source, state, extra]


def _pack(
    root: Path, fields: list[list[str]], category: str = "单位", count: int = 1
) -> Path:
    _write(
        root / "对象ID" / (category + ".tsv"),
        [
            _ID_HEADER,
            *[
                [category, f"U{i:03x}", "1", "zzzz", f"守卫{i}", "是", "地图说明"]
                for i in range(1, count + 1)
            ],
        ],
    )
    path = root / "对象字段.tsv"
    _write(path, [_FIELD_HEADER, *fields])
    return path


def _query(root: Path, mode: str, keyword: str = "", limit: int = 0):
    return queries.execute_pack_query(
        PackQueryCliOptions(str(root), mode, keyword, limit=limit)
    )


@pytest.mark.parametrize("mode,category", [("units", "单位"), ("heroes", "英雄")])
def test_unit_skill_query_searches_linked_fields_and_retains_every_source(
    tmp_path: Path,
    mode: str,
    category: str,
) -> None:
    path = _pack(
        tmp_path,
        [
            _field(
                category,
                "U001",
                "uabi",
                "A001,A001",
                source="war3map.w3u",
                extra="第一链接来源",
            ),
            _field(
                category,
                "U001",
                "uhab",
                "学习技能(A001)|A002",
                source="war3mapSkin.w3u",
                extra="第二链接来源",
            ),
            _field(
                "技能", "A001", "acdn:1", "2.500", name="寒霜术", extra="冷却编码证据"
            ),
            _field("技能", "A001", "aran:2", "765", name="寒霜术"),
            _field(
                "技能",
                "A001",
                "custom-tail",
                "完整自定义效果\n末尾",
                source="chapter.w3a",
                extra="扩展独有证据",
            ),
            _field("技能", "A002", "amcs:1", "80", name="风暴术"),
            _field("单位", "A001", "wrong-category", "不能串入的同码单位"),
        ],
        category,
    )
    before = path.read_bytes()
    result = _query(tmp_path, mode, '守卫1 && ="扩展独有证据"')
    text = result.render()
    assert result.exit_code == 0
    assert text.count("关联技能 [A001]") == 1
    assert text.count("关联技能 [A002]") == 1
    assert "默认技能" in text and "可学习英雄技能" in text
    assert "2.500 秒" in text and "等级 2" in text and "765" in text
    assert "完整自定义效果\n末尾" in text and "chapter.w3a" in text
    assert "第一链接来源" in text and "第二链接来源" in text
    assert "不能串入的同码单位" not in text
    assert path.read_bytes() == before
    data = json.loads(result.render(as_json=True))
    assert any("关联技能 [A001]" in line for line in data["lines"])
    assert _query(tmp_path, mode, "寒霜术 && 冷却编码证据").exit_code == 0
    assert (
        _query(tmp_path, "search", category + ":守卫1 && 扩展独有证据").exit_code == 0
    )


@pytest.mark.parametrize("custom", ["", "动态技能列表", "A002"])
@pytest.mark.parametrize(
    "key,base", [("uabi", "base:abilList"), ("uhab", "base:heroAbilList")]
)
def test_custom_link_overrides_base_even_when_empty_or_unresolved(
    tmp_path: Path,
    custom: str,
    key: str,
    base: str,
) -> None:
    _pack(
        tmp_path,
        [
            _field("单位", "U001", base, "A001", source="base:hfoo"),
            _field("单位", "U001", key, custom),
            _field("技能", "A001", "acdn:1", "999", name="继承技能独有词"),
            _field("技能", "A002", "acdn:1", "2", name="地图新技能"),
        ],
    )
    text = _query(tmp_path, "units", "U001").render()
    assert "关联技能 [A001]" not in text and "已被自定义声明" in text
    assert _query(tmp_path, "units", "继承技能独有词").exit_code == 2
    if custom == "A002":
        assert "关联技能 [A002]" in text and "2 秒" in text
    elif not custom:
        assert "显式空值" in text
    else:
        assert "未确认可展开四码" in text and custom in text


@pytest.mark.parametrize("state", ["overridden", "conflict", "unknown"])
def test_unconfirmed_custom_links_do_not_expand_or_unlock_inheritance(
    tmp_path: Path, state: str
) -> None:
    _pack(
        tmp_path,
        [
            _field("单位", "U001", "uabi", "A002", state=state),
            _field("单位", "U001", "base:uabi", "A001"),
            _field("技能", "A001", "acdn:1", "10"),
            _field("技能", "A002", "acdn:1", "20"),
        ],
    )
    text = _query(tmp_path, "units").render()
    assert "关联技能 [" not in text
    assert state in text and "base:uabi" in text


def test_different_declared_links_preserve_independent_alternatives_and_missing_fields(
    tmp_path: Path,
) -> None:
    _pack(
        tmp_path,
        [
            _field("单位", "U001", "uabi", "A001", source="first.w3u"),
            _field("单位", "U001", "abilList", "A002", source="second.slk"),
            _field("技能", "A001", "acdn:1", "10"),
        ],
    )
    text = _query(tmp_path, "units").render()
    assert "不能据此认定同时生效" in text
    assert "关联技能 [A001]" in text and "关联技能 [A002]" in text
    assert "字段未记录" in text and 'skills id:="A002"' in text
    assert "first.w3u" in text and "second.slk" in text


@pytest.mark.parametrize("code", ["a001", "0+!?", "=abc", " A1 ", "A|01"])
def test_shared_fourcc_parser_keeps_case_punctuation_and_whitespace(
    tmp_path: Path, code: str
) -> None:
    _pack(
        tmp_path,
        [
            _field("单位", "U001", "uabi", "技能名称(" + code + ")"),
            _field("技能", code, "acdn:1", "12", name="准确技能"),
            _field("技能", "A001", "acdn:1", "999", name="同字母不同大小写"),
        ],
    )
    text = _query(tmp_path, "units", "准确技能").render()
    assert f"关联技能 [{code}]" in text and "12 秒" in text
    assert "同字母不同大小写" not in text
    assert _query(tmp_path, "skills", encode_object_id_query(code)).exit_code == 0


def test_ambiguous_link_spelling_remains_raw_without_guessing(tmp_path: Path) -> None:
    _pack(
        tmp_path,
        [
            _field("单位", "U001", "uabi", "abc(,I01)"),
            _field("技能", ",I01", "acdn:1", "5"),
        ],
    )
    text = _query(tmp_path, "units").render()
    assert "abc(,I01)" in text and "未确认可展开四码" in text
    assert "关联技能 [" not in text


def test_skill_summary_retains_every_encoded_level_column_conflict_and_raw_value(
    tmp_path: Path,
) -> None:
    huge = "9" * 5000
    fields = [
        _field("技能", "A001", "acdn:2", "7.50", source="one.w3a"),
        _field("技能", "A001", "acdn2", "8", source="two.w3a"),
        _field("技能", "A001", "acdn:1:column:7", "1e-99"),
        _field("技能", "A001", "aran:" + huge, "123.45678901234567890123456789"),
        _field("技能", "A001", "alev", huge),
        _field("技能", "A001", "amcs:0", "-0.000"),
        _field("技能", "A001", "ahky", "Q"),
        _field("技能", "A001", "aare:2", "100"),
        _field("技能", "A001", "unrecognized", "未知原字段完整尾部"),
    ]
    _pack(tmp_path, fields)
    text = _query(tmp_path, "skills", "A001").render()
    assert "逐级保留" in text and "不代表当前冷却" in text
    assert "等级 1，数据列 7" in text and "等级 7" not in text
    assert "7.50 秒" in text and "8 秒" in text and "有冲突" in text
    assert "one.w3a" in text and "two.w3a" in text
    assert "等级 " + huge in text and "1e-99 秒" in text
    assert "123.45678901234567890123456789" in text and "-0.000" in text
    assert "普通热键" in text and "作用范围" in text and "未知原字段完整尾部" in text


@pytest.mark.parametrize("value", ["NaN", "Infinity", "12+3", "'12", "", "动态变量"])
def test_invalid_summary_value_never_falls_back_to_base(
    tmp_path: Path, value: str
) -> None:
    _pack(
        tmp_path,
        [
            _field("技能", "A001", "acdn:1", value),
            _field("技能", "A001", "base:acdn:1", "99", source="base:AHbz"),
        ],
    )
    text = _query(tmp_path, "skills", "A001").render()
    summary, raw = text.split("  完整对象字段:", 1)
    assert "未确认" in summary and "99 秒" not in summary
    assert "base:AHbz" in raw and "99" in raw


def test_overridden_combat_values_are_raw_evidence_only(tmp_path: Path) -> None:
    _pack(
        tmp_path,
        [
            _field(
                "技能", "A001", "acdn:1", "99", state="overridden", source="old.w3a"
            ),
            _field("技能", "A001", "acdn:1", "4.0", source="war3mapSkin.w3a"),
            _field("技能", "A001", "base:acdn:1", "88", source="base:AHbz"),
        ],
    )
    text = _query(tmp_path, "skills", "A001").render()
    summary, raw = text.split("  完整对象字段:", 1)
    assert "4.0 秒" in summary and "99 秒" not in summary and "88 秒" not in summary
    assert "old.w3a" in raw and "base:AHbz" in raw and "overridden" in raw


def test_static_unit_summary_preserves_two_attacks_and_does_not_calculate_dps(
    tmp_path: Path,
) -> None:
    _pack(
        tmp_path,
        [
            _field("单位", "U001", "ua1b", "10"),
            _field("单位", "U001", "ua1c", "1.50"),
            _field("单位", "U001", "ua1r", "100"),
            _field("单位", "U001", "ua2c", "2.75"),
            _field("单位", "U001", "ua2r", "650"),
            _field("单位", "U001", "udef", "-2"),
            _field("单位", "U001", "umvs", "320"),
            _field("单位", "U001", "usid", "1800"),
            _field("单位", "U001", "usin", "800"),
        ],
    )
    text = _query(tmp_path, "units").render()
    assert "攻击 1 间隔" in text and "1.50 秒" in text
    assert "攻击 2 射程" in text and "650" in text
    assert "基础护甲" in text and "-2" in text
    assert "移动速度" in text and "白天视野" in text and "夜晚视野" in text
    assert "不代表局内加成、当前攻防或实战 DPS" in text
    assert "DPS:" not in text and "每秒伤害" not in text


def test_summary_never_guesses_roles_from_labels_or_unqualified_data_fields() -> None:
    fields = (
        ObjectField("DataA1", "冷却", "5", "base:family"),
        ObjectField("ACDN:1", "冷却", "7", "map"),
        ObjectField("acdn:1", "冷却", "9", "map"),
    )
    assert [row.key for row in combat_parameters("技能", fields)] == ["acdn"]
    assert combat_parameters("物品", fields) == ()
    assert combat_parameters("单位", fields) == ()


def test_limit_keeps_complete_unit_and_every_linked_skill_without_repeated_field_scans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    count = 1100
    codes = [f"A{i:03x}" for i in range(count)]
    fields = [
        _field("单位", "U001", "uabi", ",".join(codes)),
        _field("单位", "U002", "uabi", "Z999"),
        *[_field("技能", code, "private", "尾部" + code) for code in codes],
        _field("技能", "Z999", "private", "未选单位的字段"),
    ]
    _pack(tmp_path, fields, count=2)
    loaded: list[str] = []
    rendered: list[str] = []
    original_load, original_render = queries._named_table, ObjectField.render_lines

    def load(pack: Path, relative: str, table: str = ""):
        loaded.append(relative)
        return original_load(pack, relative, table)

    def render(self: ObjectField, indent: str = "    "):
        rendered.append(self.value)
        return original_render(self, indent)

    monkeypatch.setattr(queries, "_named_table", load)
    monkeypatch.setattr(ObjectField, "render_lines", render)
    text = _query(tmp_path, "units", "守卫", limit=1).render()
    assert loaded.count("对象字段.tsv") == 1
    assert text.count("关联技能 [") == count
    assert "尾部" + codes[-1] in text and "其余 1 条未显示" in text
    assert "未选单位的字段" not in rendered and "关联技能 [Z999]" not in text


def test_linked_source_refreshes_same_size_same_mtime_and_stays_in_campaign_scope(
    tmp_path: Path,
) -> None:
    first = tmp_path / "子地图" / "001"
    second = tmp_path / "子地图" / "002"
    fields = [
        _field("单位", "U001", "uabi", "A001"),
        _field("技能", "A001", "acdn:1", "10", name="第一章技能"),
    ]
    path = _pack(first, fields)
    _pack(
        second,
        [
            _field("单位", "U001", "uabi", "A001"),
            _field("技能", "A001", "acdn:1", "99", name="第二章技能"),
        ],
    )
    result = _query(tmp_path, "units", "第一章技能")
    assert (
        result.exit_code == 0
        and "10 秒" in result.render()
        and "99 秒" not in result.render()
    )
    stat = path.stat()
    path.write_bytes(path.read_bytes().replace(b"\t10\t", b"\t11\t"))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    refreshed = _query(first, "units", "第一章技能")
    assert "11 秒" in refreshed.render() and "10 秒" not in refreshed.render()
    assert (
        path.stat().st_size == stat.st_size
        and path.stat().st_mtime_ns == stat.st_mtime_ns
    )


def test_linked_skill_field_boundaries_are_not_joined_for_boolean_matching(
    tmp_path: Path,
) -> None:
    _pack(
        tmp_path,
        [
            _field("单位", "U001", "uabi", "A001,A002"),
            _field("技能", "A001", "arbitrary", "火焰"),
            _field("技能", "A002", "arbitrary", "寒冰"),
        ],
    )
    assert _query(tmp_path, "units", "火焰 && 寒冰").exit_code == 0
    assert _query(tmp_path, "units", '="火焰寒冰"').exit_code == 2
