"""Complete object-text searches and scalable Boolean query evaluation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool import search
from gametool.pack_query_options import PackQueryCliOptions


@pytest.fixture(autouse=True)
def isolated_query_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _table(pack: Path, category: str, rows: list[tuple[str, str, str]]) -> None:
    folder = pack / "对象ID"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{category}.tsv").write_text(
        "分类\tID\t数值\t基础ID\t名称\t自定义\t说明\t英文名\n"
        + "".join(
            f"{category}\t{code}\t1\t{code}\t{name}\t是\t{desc}\tFlame Sword\n"
            for code, name, desc in rows
        ),
        encoding="utf-8",
    )


def test_search_matches_description_and_retains_complete_evidence(
    tmp_path: Path,
) -> None:
    description = "火焰攻击 " + "完整效果" * 2000
    _table(tmp_path, "物品", [("I001", "无关名称", description)])
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "search", "火焰 && 攻击")
    )
    assert result.exit_code == 0
    assert description in result.render()


def test_search_category_prefix_and_expression(tmp_path: Path) -> None:
    _table(tmp_path, "物品", [("I001", "烈焰剑", "攻击增加")])
    _table(tmp_path, "单位", [("n001", "烈焰剑", "攻击增加")])
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "search", "物品: 烈焰 && 攻击")
    )
    assert result.exit_code == 0
    assert "[I001]" in result.render() and "[n001]" not in result.render()


def test_failed_and_condition_short_circuits_without_scanning_remaining_terms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original = search._like_score

    def scored(*args):
        nonlocal calls
        calls += 1
        return original(*args)

    monkeypatch.setattr(search, "_like_score", scored)
    query = search.compile_query(" && ".join(["absent"] + ["present"] * 5000))
    assert query.score("present") is None
    assert calls == 1


@pytest.mark.parametrize(
    "query",
    [
        "items：烈焰 && 攻击",
        "物品:烈焰% && %增加",
        '物品:="Flame" && 攻击',
        "物品:I001 && 攻击",
        "物品:不存在 || 攻击",
        "物品:STRASSE",
    ],
)
def test_search_scoped_field_expressions(tmp_path: Path, query: str) -> None:
    _table(tmp_path, "物品", [("I001", "烈焰剑 Straße", "攻击增加")])
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "search", query)
    )
    assert result.exit_code == 0
    assert "[I001]" in result.render()


def test_exact_search_cannot_cross_field_boundaries_or_change_case(
    tmp_path: Path,
) -> None:
    _table(tmp_path, "物品", [("I001", "烈焰剑", "攻击增加")])
    for query in ('物品:="烈焰剑 攻击增加"', '物品:="flame"'):
        result = queries.execute_pack_query(
            PackQueryCliOptions(str(tmp_path), "search", query)
        )
        assert result.exit_code == 2
        assert "完整搜索物品表 1 项" in result.render()


def test_category_without_words_lists_every_object_and_explicit_limit_reports_count(
    tmp_path: Path,
) -> None:
    _table(tmp_path, "物品", [(f"I{i:03}", f"物品{i}", "说明") for i in range(30)])
    full = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "search", "物品:")
    )
    limited = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "search", "物品:", limit=1)
    )
    assert full.exit_code == limited.exit_code == 0
    assert full.render().count("  [I") == 30
    assert limited.render().count("  [I") == 1
    assert "其余 29 条未显示" in limited.render()


def test_numeric_base_and_extended_fields_are_searchable(tmp_path: Path) -> None:
    _table(tmp_path, "物品", [("I001", "烈焰剑", "攻击增加")])
    path = tmp_path / "对象ID" / "物品.tsv"
    path.write_text(
        path.read_text(encoding="utf-8").replace("\t1\tI001\t", "\t123456\tswor\t"),
        encoding="utf-8",
    )
    for query in ("123456", "swor", '="Flame Sword"'):
        result = queries.execute_pack_query(
            PackQueryCliOptions(str(tmp_path), "search", query)
        )
        assert result.exit_code == 0
        assert "基础ID: swor" in result.render()
        assert "数值: 123456" in result.render()
        assert "英文名: Flame Sword" in result.render()


def test_scoped_campaign_search_json_and_again_keep_each_map(tmp_path: Path) -> None:
    for index in range(3):
        _table(
            tmp_path / "子地图" / f"{index:03}",
            "物品",
            [(f"I{index:03}", "烈焰剑", "攻击增加")],
        )
    query = "物品:烈焰% && 攻击"
    first = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "search", query)
    )
    again = queries.execute_pack_query(PackQueryCliOptions(str(tmp_path), "again", ""))
    for result in (first, again):
        payload = json.loads(result.render(as_json=True))
        assert result.exit_code == 0 and result.campaign
        assert len(payload["sections"]) == 3
        assert payload["query"] == query
        assert all(
            "说明: 攻击增加" in "\n".join(s["lines"]) for s in payload["sections"]
        )


@pytest.mark.parametrize("query", ["", "&& || ()", "物品:&& || ()"])
def test_empty_expression_cannot_match_every_record(tmp_path: Path, query: str) -> None:
    _table(tmp_path, "物品", [("I001", "烈焰剑", "攻击增加")])
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "search", query)
    )
    assert result.exit_code == 2
    assert "[I001]" not in result.render()


def test_malformed_row_is_diagnosed_without_claiming_a_hit(tmp_path: Path) -> None:
    _table(tmp_path, "物品", [("I001", "烈焰剑", "攻击增加")])
    with (tmp_path / "对象ID" / "物品.tsv").open("a", encoding="utf-8") as handle:
        handle.write("物品\t坏行\n")
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "search", "未出现的词")
    )
    assert result.exit_code == 2
    assert "1 行字段不完整" in result.render()


def test_or_keeps_best_score_and_field_wildcards_keep_their_anchors() -> None:
    query = search.compile_query("late || early")
    assert query.score("early late") == 1000
    query = search.compile_query("剑% && %增加")
    assert query.score_fields(("剑盾", "攻击增加")) == 1998
    assert query.score_fields(("短剑盾", "攻击增加")) is None


def test_flat_and_right_nested_chains_preserve_all_terms() -> None:
    assert search.compile_query(" && ".join(["a"] * 10000)).score("a") == 10000000
    query = "(".join(["a && "] * 3000) + "absent" + ")" * 2999
    assert search.compile_query(query).score("a") is None
