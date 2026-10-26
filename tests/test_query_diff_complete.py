"""Diff covers every object family and complete per-product recipe evidence."""

import csv
import json
import re
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_options import PackQueryCliOptions

_TABLES = ("物品", "单位", "技能", "英雄", "增益", "科技", "装饰物", "可破坏物")
_HEADER = ["分类", "ID", "数值", "基础ID", "名称", "自定义", "说明"]


@pytest.fixture(autouse=True)
def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _write(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t", lineterminator="\n").writerows(rows)


def _objects(pack: Path, table: str, rows: list[tuple[str, str]]) -> None:
    _write(
        pack / "对象ID" / f"{table}.tsv",
        [
            _HEADER,
            *[
                [table, code, "1", "zzzz", name, "是", "完整说明"]
                for code, name in rows
            ],
        ],
    )


def _recipes(pack: Path, rows: list[tuple[str, str, str, str]]) -> None:
    _write(
        pack / "掉落与获取关系.tsv",
        [
            [str(index), "", "合成", code, name, *("" for _ in range(12)), ids, text]
            for index, (code, name, ids, text) in enumerate(rows)
        ],
    )


def _run(old: Path, new: Path, *, query: str = "", limit: int = 0):
    return queries.execute_pack_query(
        PackQueryCliOptions(str(new), "diff", query, limit=limit, pack_dir_b=str(old))
    )


@pytest.mark.parametrize("table", _TABLES)
@pytest.mark.parametrize("kind", ["added", "removed", "summary", "field"])
def test_all_eight_object_tables_detect_every_change_kind(
    tmp_path: Path, table: str, kind: str
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    before = [] if kind == "added" else [("X001", "原名称")]
    after = (
        []
        if kind == "removed"
        else [("X001", "新名称" if kind == "summary" else "原名称")]
    )
    _objects(old, table, before)
    _objects(new, table, after)
    if kind == "field":
        for pack, value in [(old, "123"), (new, "456")]:
            _write(
                pack / "对象字段.tsv",
                [["分类", "ID", "字段键", "值"], [table, "X001", "cost", value]],
            )
    result = _run(old, new)
    text = result.render()
    assert result.exit_code == 0 and f"== {table}:" in text and "[X001]" in text
    if kind == "field":
        assert "cost: 123 -> 456" in text
    assert not json.loads(result.render(as_json=True))["warnings"]


@pytest.mark.parametrize("table", _TABLES)
@pytest.mark.parametrize("limit", [0, 1, 3, 4, 9])
def test_explicit_diff_limits_count_added_removed_and_changed_objects_together(
    tmp_path: Path, table: str, limit: int
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    _objects(
        old,
        table,
        [(f"D00{i}", "删除") for i in range(1, 4)]
        + [(f"C00{i}", "旧名称") for i in range(1, 4)],
    )
    _objects(
        new,
        table,
        [(f"N00{i}", "新增") for i in range(1, 4)]
        + [(f"C00{i}", "新名称") for i in range(1, 4)],
    )
    result = _run(old, new, limit=limit)
    text = result.render()
    shown = len(re.findall(r"^  [+~-] \[", text, re.MULTILINE))
    assert result.exit_code == 0 and shown == (min(limit, 9) if limit else 9)
    assert "新增 3 / 删除 3 / 变更 3" in text and "合计 9 项变化" in text
    if limit and limit < 9:
        assert f"其余 {9 - limit} 条未显示" in text
    else:
        assert "未显示" not in text


@pytest.mark.parametrize("table", _TABLES)
def test_table_filter_excludes_unrelated_tables_and_recipe_changes(
    tmp_path: Path, table: str
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    for current in _TABLES:
        _objects(old, current, [])
        _objects(new, current, [("X001", "新增")])
    if table != "物品":
        _recipes(old, [])
        _recipes(new, [("I001", "合成成品", "M001", "材料×1")])
    result = _run(old, new, query=table)
    titles = re.findall(r"^== (.*?):", result.render(), re.MULTILINE)
    assert result.exit_code == 0 and titles == [table]


def test_changed_object_keeps_all_field_differences_under_limit_one(
    tmp_path: Path,
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    for pack, value in [(old, "旧"), (new, "新")]:
        _objects(pack, "科技", [("R001", "科技")])
        _write(
            pack / "对象字段.tsv",
            [
                ["分类", "ID", "字段键", "值"],
                *[["科技", "R001", f"level{i}", f"{value}{i}"] for i in range(5000)],
            ],
        )
    text = _run(old, new, limit=1).render()
    assert len(re.findall(r"^      level", text, re.MULTILINE)) == 5000
    assert "level4999: 旧4999 -> 新4999" in text and "未显示" not in text


def test_second_recipe_of_the_same_product_is_not_hidden_by_the_first(
    tmp_path: Path,
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    _recipes(
        old,
        [
            ("I001", "旧成品", "M001", "稳定材料"),
            ("I001", "旧成品", "M002", "旧替代材料"),
        ],
    )
    _recipes(
        new,
        [
            ("I001", "新成品", "M001", "稳定材料"),
            ("I001", "新成品", "M003", "新替代材料"),
        ],
    )
    text = _run(old, new, limit=1).render()
    assert "== 合成:" in text and "旧替代材料" in text and "新替代材料" in text
    assert "M002" in text and "M003" in text and text.count("稳定材料") == 2


def test_recipe_order_and_mirrored_rows_do_not_create_false_changes(
    tmp_path: Path,
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    recipes = [("I001", "成品", "M001", "材料甲"), ("I001", "成品", "M002", "材料乙")]
    _recipes(old, recipes)
    _recipes(new, [recipes[1], recipes[0], recipes[1]])
    assert _run(old, new).render() == "两包对象表无差异"


def test_material_ids_participate_when_names_are_equal_or_empty(tmp_path: Path) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    _recipes(
        old, [("I001", "成品", "M001", "同名材料"), ("I002", "仅有码配方", "M003", "")]
    )
    _recipes(
        new, [("I001", "成品", "M002", "同名材料"), ("I002", "仅有码配方", "M004", "")]
    )
    text = _run(old, new).render()
    assert "变更 2" in text and all(
        code in text for code in ["M001", "M002", "M003", "M004"]
    )


def test_removed_recipe_names_come_from_the_old_pack(tmp_path: Path) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    _objects(old, "物品", [("I001", "旧成品名称")])
    _objects(new, "物品", [])
    _recipes(old, [("I001", "关系行旧名", "M001", "材料")])
    text = _run(old, new, query="合成").render()
    assert "旧成品名称" in text and "== 物品:" not in text


@pytest.mark.parametrize("limit", [0, 1, 2, 3])
def test_recipe_limits_count_complete_product_groups(
    tmp_path: Path, limit: int
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    _recipes(old, [])
    _recipes(
        new,
        [
            (f"I00{i}", f"成品{i}", f"M00{j}", f"材料{i}/{j}")
            for i in range(1, 4)
            for j in range(1, 4)
        ],
    )
    text = _run(old, new, limit=limit).render()
    shown = min(limit, 3) if limit else 3
    assert len(re.findall(r"^  \+ \[", text, re.MULTILINE)) == shown
    assert (
        sum(f"材料{i}/{j}" in text for i in range(1, 4) for j in range(1, 4))
        == shown * 3
    )
    if 0 < limit < 3:
        assert f"其余 {3 - limit} 条未显示" in text
    else:
        assert "未显示" not in text


def test_invalid_table_filter_has_an_actionable_error(tmp_path: Path) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    result = _run(old, new, query="不存在的表")
    assert (
        result.exit_code == 2
        and "可用" in result.render()
        and "可破坏物" in result.render()
    )


def test_an_arbitrarily_large_explicit_limit_does_not_impose_machine_word_limits(
    tmp_path: Path,
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    _objects(old, "物品", [])
    _objects(new, "物品", [("I001", "新增")])
    result = _run(old, new, limit=10**10000)
    assert (
        result.exit_code == 0
        and "[I001]" in result.render()
        and "未显示" not in result.render()
    )


def test_a_pack_directory_named_after_a_category_is_still_a_full_diff(
    tmp_path: Path,
) -> None:
    old, new = tmp_path / "物品", tmp_path / "new"
    _objects(old, "科技", [])
    _objects(new, "科技", [("R001", "新增科技")])
    result = queries.execute_pack_query(PackQueryCliOptions(str(new), "diff", str(old)))
    assert result.exit_code == 0 and "== 科技:" in result.render()
