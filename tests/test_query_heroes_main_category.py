"""Hero queries include catalog-proved W3U units without changing identities."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_options import PackQueryCliOptions


_IDS = ["分类", "ID", "数值", "基础ID", "名称", "自定义", "说明", "原始附证"]
_FIELDS = ["分类", "ID", "名称", "字段键", "字段名", "值", "来源"]


@pytest.fixture(autouse=True)
def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _write(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream, delimiter="\t", lineterminator="\n").writerows(rows)


def _unit(code: str, base: str, name: str = "地图英雄") -> list[str]:
    return ["单位", code, "1", base, name, "是", "完整说明", "单位尾部附证"]


def _query(pack: Path, command: str = "heroes", query: str = "", limit: int = 0):
    return queries.execute_pack_query(
        PackQueryCliOptions(str(pack), command, query, limit)
    )


@pytest.mark.parametrize("command,query", [("heroes", "寒霜"), ("search", "hero:寒霜")])
def test_unit_hero_keeps_complete_original_category_fields_and_linked_abilities(
    tmp_path: Path, command: str, query: str
) -> None:
    path = tmp_path / "对象ID" / "单位.tsv"
    _write(path, [_IDS, _unit("x001", "Hamg")])
    _write(
        tmp_path / "对象字段.tsv",
        [
            _FIELDS,
            ["单位", "x001", "单位英雄别名", "uhab", "技能", "A001", "war3map.w3u"],
            ["技能", "A001", "寒霜", "acdn:7", "冷却", "9.5", "chapter.w3a"],
            ["物品", "x001", "不能串入的物品", "other", "", "物品独有附证", "map"],
        ],
    )
    before = path.read_bytes()
    result = _query(tmp_path, command, query)
    text = result.render()
    assert result.exit_code == 0
    assert "[x001] 地图英雄" in text and "单位尾部附证" in text
    assert "原始分类仍为单位" in text and "基础 ID Hamg" in text
    assert "不证明当前可选" in text and "[A001]" in text and "9.5 秒" in text
    assert "war3map.w3u" in text and "chapter.w3a" in text
    assert "物品独有附证" not in text
    assert path.read_bytes() == before
    assert "[x001]" in _query(tmp_path, "units").render()


def test_dedicated_and_unit_hero_same_code_keep_independent_fields_and_headers(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "对象ID" / "单位.tsv", [_IDS, _unit("x001", "Hamg")])
    _write(
        tmp_path / "对象ID" / "英雄.tsv",
        [
            [*_IDS[:7], "英雄表来源"],
            ["英雄", "x001", "2", "Hpal", "独立英雄记录", "是", "", "专属来源"],
        ],
    )
    _write(
        tmp_path / "对象字段.tsv",
        [
            _FIELDS,
            ["单位", "x001", "单位别名", "one", "", "单位证据", "units"],
            ["英雄", "x001", "英雄别名", "two", "", "英雄证据", "heroes"],
        ],
    )
    result = _query(tmp_path)
    first, second = result.render().split("[x001]")[1:]
    assert "英雄证据" in first and "单位证据" not in first
    assert "单位证据" in second and "英雄证据" not in second
    assert "英雄表来源: 专属来源" in first and "原始附证: 单位尾部附证" in second
    limited = _query(tmp_path, limit=1).render()
    assert limited.count("[x001]") == 1 and "其余 1 条未显示" in limited


@pytest.mark.parametrize("base", ["", "hfoo", "hamg", "unknown", "HAMG"])
def test_hero_names_uppercase_codes_or_stats_do_not_replace_base_identity(
    tmp_path: Path, base: str
) -> None:
    _write(tmp_path / "对象ID" / "单位.tsv", [_IDS, _unit("Hpal", base, "英雄圣骑士")])
    _write(
        tmp_path / "对象字段.tsv",
        [_FIELDS, ["单位", "Hpal", "英雄", "ustr", "力量", "99", "map.w3u"]],
    )
    result = _query(tmp_path)
    assert result.exit_code == 2 and "本次可确认英雄对象记录共 0 项" in result.render()
    assert "units" in result.render()
    assert _query(tmp_path, "units", "Hpal").exit_code == 0


def test_conflicting_unit_base_declarations_do_not_choose_the_hero_row(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "对象ID" / "单位.tsv",
        [_IDS, _unit("x001", "Hamg"), _unit("x001", "hfoo")],
    )
    assert _query(tmp_path).exit_code == 2
    units = _query(tmp_path, "units").render()
    assert units.count("[x001]") == 2 and "Hamg" in units and "hfoo" in units


def test_field_only_hero_identity_is_retained_without_inventing_a_unit_base(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "对象字段.tsv",
        [
            _FIELDS,
            ["英雄", "x001", "明确英雄", "ustr", "", "10", "map"],
            ["单位", "Hamg", "单位未记录基础", "ustr", "", "20", "map"],
        ],
    )
    text = _query(tmp_path).render()
    assert (
        "[x001]" in text
        and "[Hamg]" not in text
        and "基础 ID 及自定义标记未记录" in text
    )


def test_global_search_lists_unit_hero_once_and_keeps_both_source_categories(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "对象ID" / "单位.tsv", [_IDS, _unit("x001", "Hamg")])
    text = _query(tmp_path, "search", "地图英雄").render()
    assert text.count("[x001]") == 1 and "== 单位 (1 个)==" in text
    assert "== 英雄" not in text


def test_campaign_hero_query_preserves_unit_scope_and_diagnostic_only_child(
    tmp_path: Path,
) -> None:
    good, bad = tmp_path / "子地图" / "001", tmp_path / "子地图" / "002"
    _write(good / "对象ID" / "单位.tsv", [_IDS, _unit("x001", "Hamg")])
    _write(
        bad / "对象ID" / "单位.tsv", [["ID", "ID", "名称"], ["x001", "x002", "冲突"]]
    )
    result = _query(tmp_path)
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 0 and result.campaign
    assert any(
        section["pack"] == str(good) and "[x001]" in "\n".join(section["lines"])
        for section in data["sections"]
    )
    assert any(
        section["pack"] == str(bad) and "重复语义列" in "\n".join(section["lines"])
        for section in data["sections"]
    )


def test_hero_selection_loads_fields_once_and_never_truncates_unit_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(
        tmp_path / "对象ID" / "单位.tsv",
        [_IDS, *[_unit(f"x{i:03x}", "Hamg") for i in range(1200)]],
    )
    calls: list[str] = []
    original = queries._named_table

    def load(pack: Path, relative: str, table: str = ""):
        calls.append(relative)
        return original(pack, relative, table)

    monkeypatch.setattr(queries, "_named_table", load)
    text = _query(tmp_path).render()
    assert calls.count("对象字段.tsv") == 1
    assert sum(line.startswith("[x") for line in text.splitlines()) == 1200
    assert "[x4af]" in text and "未显示" not in text
