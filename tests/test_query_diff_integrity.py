"""Incomplete sources cannot become invented additions, removals or equality."""

import csv
import json
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_options import PackQueryCliOptions

_TABLES = ("物品", "单位", "技能", "英雄", "增益", "科技", "装饰物", "可破坏物")
_HEADER = ["分类", "ID", "数值", "基础ID", "名称", "自定义", "说明"]


def _write(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t", lineterminator="\n").writerows(rows)


def _objects(pack: Path, table: str, name: str = "相同名称") -> Path:
    path = pack / "对象ID" / f"{table}.tsv"
    _write(path, [_HEADER, [table, "X001", "1", "zzzz", name, "是", "说明"]])
    return path


def _fields(pack: Path, value: str) -> Path:
    path = pack / "对象字段.tsv"
    _write(path, [["分类", "ID", "字段键", "值"], ["单位", "X001", "cost", value]])
    return path


def _recipes(pack: Path, code: str = "I001") -> Path:
    path = pack / "掉落与获取关系.tsv"
    _write(
        path,
        [["r1", "", "合成", code, "成品", *("" for _ in range(12)), "M001", "材料×1"]],
    )
    return path


def _run(old: Path, new: Path, *, limit: int = 0):
    return queries.execute_pack_query(
        PackQueryCliOptions(str(new), "diff", str(old), limit=limit)
    )


@pytest.fixture(autouse=True)
def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    monkeypatch.setattr(queries, "_LOCKED_FILES", set())


@pytest.mark.parametrize("table", _TABLES)
@pytest.mark.parametrize("side", ["old", "new"])
def test_a_bad_identity_header_cannot_invent_an_addition_or_removal(
    tmp_path: Path, table: str, side: str
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    _objects(old, table)
    _objects(new, table)
    damaged = old if side == "old" else new
    _write(
        damaged / "对象ID" / f"{table}.tsv",
        [["ID", "ID", "名称"], ["X001", "X002", "冲突"]],
    )
    result = _run(old, new)
    data = json.loads(result.render(as_json=True))
    assert (
        result.exit_code == 2
        and not data["comparison_complete"]
        and not data["has_changes"]
    )
    assert not data["input_error"] and data["checked_packs"] == [str(new), str(old)]
    assert "  + [X001]" not in result.render() and "  - [X001]" not in result.render()
    assert data["comparison_diagnostics"][0]["pack"] == str(damaged)


@pytest.mark.parametrize("table", _TABLES)
@pytest.mark.parametrize("side", ["old", "new"])
def test_partial_object_rows_keep_confirmed_changes_and_suppress_unknown_absence(
    tmp_path: Path, table: str, side: str
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    old_path = _objects(old, table, "旧名称")
    new_path = _objects(new, table, "新名称")
    with old_path.open("a", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t").writerow(
            [table, "D001", "1", "zzzz", "被删除", "是", ""]
        )
    with new_path.open("a", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t").writerow(
            [table, "N001", "1", "zzzz", "被新增", "是", ""]
        )
    damaged = old_path if side == "old" else new_path
    with damaged.open("a", encoding="utf-8") as handle:
        handle.write(table + "\tbad\n")
    result = _run(old, new)
    data = json.loads(result.render(as_json=True))
    assert (
        result.exit_code == 0
        and data["has_changes"]
        and not data["comparison_complete"]
    )
    assert "  ~ [X001]" in result.render()
    if side == "old":
        assert "  + [N001]" not in result.render() and "  - [D001]" in result.render()
    else:
        assert "  - [D001]" not in result.render() and "  + [N001]" in result.render()


def test_two_bad_tables_never_report_equality(tmp_path: Path) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    for pack in (old, new):
        _objects(pack, "单位")
        _write(
            pack / "对象ID" / "单位.tsv",
            [["ID", "ID", "名称"], ["X001", "X002", "冲突"]],
        )
    result = _run(old, new)
    assert result.exit_code == 2 and "两包对象表无差异" not in result.render()


@pytest.mark.parametrize("side", ["old", "new"])
def test_bad_field_schema_cannot_invent_field_additions_or_deletions(
    tmp_path: Path, side: str
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    for pack in (old, new):
        _objects(pack, "单位")
        _fields(pack, "123")
    damaged = old if side == "old" else new
    _write(
        damaged / "对象字段.tsv",
        [["分类", "ID", "字段键", "值", "值"], ["单位", "X001", "cost", "123", "456"]],
    )
    result = _run(old, new)
    data = json.loads(result.render(as_json=True))
    assert (
        result.exit_code == 2
        and not data["has_changes"]
        and not data["comparison_complete"]
    )
    assert "cost:" not in result.render() and "两包对象表无差异" not in result.render()


@pytest.mark.parametrize("side", ["old", "new"])
def test_partial_fields_keep_known_value_changes_but_not_unknown_absence(
    tmp_path: Path, side: str
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    for pack, value in ((old, "123"), (new, "456")):
        _objects(pack, "单位")
        _fields(pack, value)
    with (old / "对象字段.tsv").open("a", encoding="utf-8") as handle:
        handle.write("单位\tX001\tremoved\told\n")
    with (new / "对象字段.tsv").open("a", encoding="utf-8") as handle:
        handle.write("单位\tX001\tadded\tnew\n")
    damaged = old if side == "old" else new
    with (damaged / "对象字段.tsv").open("a", encoding="utf-8") as handle:
        handle.write("单位\tbad\n")
    result = _run(old, new)
    assert result.exit_code == 0 and "cost: 123 -> 456" in result.render()
    assert json.loads(result.render(as_json=True))["comparison_complete"] is False
    if side == "old":
        assert (
            "added:" not in result.render()
            and "removed: old -> (删)" in result.render()
        )
    else:
        assert (
            "removed:" not in result.render()
            and "added: (无) -> new" in result.render()
        )


@pytest.mark.parametrize("side", ["old", "new"])
@pytest.mark.parametrize(
    "relative", ["对象ID/单位.tsv", "对象字段.tsv", "掉落与获取关系.tsv"]
)
@pytest.mark.parametrize("failure", ["directory", "encoding"])
def test_read_failures_in_either_pack_are_attributed_and_never_inferred_as_empty(
    tmp_path: Path, side: str, relative: str, failure: str
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    for pack in (old, new):
        _objects(pack, "单位")
        _fields(pack, "123")
        _recipes(pack)
    damaged = old if side == "old" else new
    path = damaged / relative
    if failure == "directory":
        path.unlink()
        path.mkdir()
    else:
        path.write_bytes(b"\xff")
    result = _run(old, new)
    data = json.loads(result.render(as_json=True))
    assert (
        result.exit_code == 2
        and not data["comparison_complete"]
        and not data["has_changes"]
    )
    assert any(
        str(damaged) in warning and relative in warning for warning in data["warnings"]
    )
    assert "两包对象表无差异" not in result.render() and data["comparison_diagnostics"]


def test_repaired_source_recovers_without_leaking_failure_state(tmp_path: Path) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    path = _objects(old, "单位", "旧名称")
    _objects(new, "单位", "新名称")
    path.write_bytes(b"\xff")
    assert _run(old, new).exit_code == 2
    _objects(old, "单位", "旧名称")
    result = _run(old, new)
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 0 and data["comparison_complete"] and data["has_changes"]
    assert (
        not data["warnings"]
        and not data["comparison_diagnostics"]
        and "  ~ [X001]" in result.render()
    )


def test_valid_equal_packs_have_an_explicit_complete_no_change_state(
    tmp_path: Path,
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    for pack in (old, new):
        _objects(pack, "单位")
        _fields(pack, "123")
        _recipes(pack)
    result = _run(old, new)
    data = json.loads(result.render(as_json=True))
    assert (
        result.exit_code == 0
        and data["comparison_complete"]
        and not data["has_changes"]
    )
    assert not data["comparison_diagnostics"] and data["checked_packs"] == [
        str(new),
        str(old),
    ]
    assert result.render() == "两包对象表无差异"


def test_limit_does_not_cut_any_bad_record_indices_or_coverage_diagnostics(
    tmp_path: Path,
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    path = _objects(old, "单位", "旧名称")
    _objects(new, "单位", "新名称")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("单位\tbad\n" * 5000)
    data = json.loads(_run(old, new, limit=1).render(as_json=True))
    assert data["has_changes"] and not data["comparison_complete"]
    assert any(
        ", ".join(map(str, range(3, 5003))) in warning for warning in data["warnings"]
    )
    assert len(data["comparison_diagnostics"]) == 1


@pytest.mark.parametrize("side", ["old", "new"])
def test_incomplete_recipes_do_not_invent_missing_products(
    tmp_path: Path, side: str
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    for pack in (old, new):
        _objects(pack, "物品")
        _recipes(pack)
    _recipes(old, "I003")
    _recipes(new, "I002")
    damaged = old if side == "old" else new
    with (damaged / "掉落与获取关系.tsv").open("a", encoding="utf-8") as handle:
        handle.write("r2\t\t合成\tbad\n")
    result = _run(old, new)
    data = json.loads(result.render(as_json=True))
    assert data["has_changes"] and not data["comparison_complete"]
    if side == "old":
        assert "  + [I002]" not in result.render() and "  - [I003]" in result.render()
    else:
        assert "  - [I003]" not in result.render() and "  + [I002]" in result.render()


@pytest.mark.parametrize(
    "layout", ["canonical", "reordered", "english", "ids_only", "text_only", "bom"]
)
def test_recipe_completeness_uses_declared_columns_and_preserves_valid_variants(
    tmp_path: Path, layout: str
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    for pack, amount in ((old, "1"), (new, "2")):
        _objects(pack, "物品")
        header = ["关系类型", "装备ID", "装备名称", "合成材料ID", "合成材料名称与数量"]
        row = ["合成", "I001", "成品", "M00" + amount, "材料×" + amount]
        if layout == "reordered":
            header, row = list(reversed(header)), list(reversed(row))
        elif layout == "english":
            header = [
                "kind",
                "product_id",
                "product_name",
                "material_ids",
                "material_text",
            ]
        elif layout == "ids_only":
            header, row = header[:2] + header[3:4], row[:2] + row[3:4]
        elif layout == "text_only":
            header, row = header[:2] + header[4:], row[:2] + row[4:]
        rows = [header, row]
        _write(pack / "掉落与获取关系.tsv", rows)
        if layout == "bom":
            path = pack / "掉落与获取关系.tsv"
            path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    result = _run(old, new)
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 0 and data["comparison_complete"] and data["has_changes"]
    assert not data["comparison_diagnostics"]
    assert "M002" in result.render() or "材料×2" in result.render()


@pytest.mark.parametrize("side", ["old", "new"])
@pytest.mark.parametrize(
    "header",
    [
        ["关系类型", "装备ID", "装备ID", "合成材料ID"],
        ["装备ID", "合成材料ID"],
        ["关系类型", "装备ID"],
    ],
)
def test_recipe_schema_gaps_never_become_invented_product_changes(
    tmp_path: Path, side: str, header: list[str]
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    for pack in (old, new):
        _objects(pack, "物品")
        _recipes(pack)
    damaged = old if side == "old" else new
    _write(damaged / "掉落与获取关系.tsv", [header, ["合成", "I001", "I002", "M001"]])
    result = _run(old, new)
    data = json.loads(result.render(as_json=True))
    assert (
        result.exit_code == 2
        and not data["comparison_complete"]
        and not data["has_changes"]
    )
    assert len(data["comparison_diagnostics"]) == 1 and "未猜测" in result.render()


def test_recipe_bad_record_indices_are_not_clipped_by_the_result_limit(
    tmp_path: Path,
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    for pack in (old, new):
        _objects(pack, "物品")
        _recipes(pack)
    with (old / "掉落与获取关系.tsv").open("a", encoding="utf-8") as handle:
        handle.write("r2\t\t合成\tbad\n" * 5000)
    data = json.loads(_run(old, new, limit=1).render(as_json=True))
    assert not data["comparison_complete"] and not data["has_changes"]
    assert (
        ", ".join(map(str, range(2, 5002)))
        in data["comparison_diagnostics"][0]["message"]
    )


@pytest.mark.parametrize(
    "complete,has_changes,line,code",
    [(False, False, "共 1 个差异段", 2), (True, False, "未找到变化", 0)],
)
def test_diff_success_is_typed_and_does_not_depend_on_rendered_words(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    complete: bool,
    has_changes: bool,
    line: str,
    code: int,
) -> None:
    from gametool.pack_query_diff import DiffQueryResult

    monkeypatch.setattr(
        queries,
        "_query_diff_result",
        lambda *args: DiffQueryResult(
            (line,), has_changes=has_changes, complete=complete
        ),
    )
    result = queries.execute_pack_query(PackQueryCliOptions(str(tmp_path), "diff", ""))
    assert (
        result.exit_code == code
        and result.comparison_complete == complete
        and result.has_changes == has_changes
    )


@pytest.mark.parametrize(
    "query,against", [("", ""), ("单位", "missing"), ("不存在的表", "old")]
)
def test_diff_input_errors_are_distinct_from_incomplete_evidence(
    tmp_path: Path, query: str, against: str
) -> None:
    (tmp_path / "old").mkdir()
    result = queries.execute_pack_query(
        PackQueryCliOptions(
            str(tmp_path),
            "diff",
            query,
            pack_dir_b=str(tmp_path / against) if against else "",
        )
    )
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 2 and data["input_error"] and not data["has_changes"]
    assert data["checked_packs"] == [] and data["comparison_diagnostics"] == []
