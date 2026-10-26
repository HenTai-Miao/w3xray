"""Dedicated object queries retain field evidence and field-only identities."""

import csv
import json
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_options import PackQueryCliOptions

_COMMANDS = [
    ("skills", "技能"),
    ("units", "单位"),
    ("heroes", "英雄"),
    ("buffs", "增益"),
]
_ID_HEADER = ["分类", "ID", "数值", "基础ID", "名称", "自定义", "说明"]
_FIELD_HEADER = ["分类", "ID", "名称", "字段键", "字段名", "值", "来源"]


def _write(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t", lineterminator="\n").writerows(rows)


@pytest.fixture(autouse=True)
def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _pack(pack: Path, table: str, *, ids: bool = True, count: int = 1) -> Path:
    if ids:
        _write(
            pack / "对象ID" / f"{table}.tsv",
            [
                _ID_HEADER,
                *[
                    [
                        table,
                        f"X{i:03x}",
                        "123",
                        "hfoo",
                        f"主表对象{i}",
                        "是",
                        "完整说明",
                    ]
                    for i in range(1, count + 1)
                ],
            ],
        )
    rows = [_FIELD_HEADER]
    for i in range(1, count + 1):
        rows.extend(
            [
                [
                    table,
                    f"X{i:03x}",
                    f"对象别名{i}",
                    "DataA:1",
                    "火焰标签",
                    "独有火焰",
                    "map.w3a",
                ],
                [
                    table,
                    f"X{i:03x}",
                    f"对象别名{i}",
                    "DataB:30000",
                    "尾部标签",
                    "完整尾部",
                    "map.w3a",
                ],
                [
                    table,
                    f"X{i:03x}",
                    f"对象别名{i}",
                    "base:DataC1",
                    "继承值",
                    "987",
                    "base:prototype",
                ],
            ]
        )
    path = pack / "对象字段.tsv"
    _write(path, rows)
    return path


def _run(pack: Path, command: str, query: str, limit: int = 0):
    return queries.execute_pack_query(
        PackQueryCliOptions(str(pack), command, query, limit=limit)
    )


@pytest.mark.parametrize("command,table", _COMMANDS)
@pytest.mark.parametrize("ids", [False, True])
@pytest.mark.parametrize(
    "query", ["X001", "对象别名1", "完整尾部", "独有火焰 && 完整尾部"]
)
def test_dedicated_queries_find_and_render_all_known_field_evidence(
    tmp_path: Path, command: str, table: str, ids: bool, query: str
) -> None:
    path = _pack(tmp_path, table, ids=ids)
    original = path.read_bytes()
    result = _run(tmp_path, command, query)
    text = result.render()
    assert result.exit_code == 0 and "[X001]" in text and "对象别名1" in text
    assert "DataA:1" in text and "DataB:30000" in text and "完整尾部" in text
    assert "base:DataC1" in text and "base:prototype" in text and "map.w3a" in text
    assert (
        not json.loads(result.render(as_json=True))["warnings"]
        and path.read_bytes() == original
    )
    if ids:
        assert "主表对象1" in text
    else:
        assert "对象字段.tsv" in text and "来源未记录" in text


@pytest.mark.parametrize("command,table", _COMMANDS)
@pytest.mark.parametrize("query", ["DataA:1", "火焰标签", "map.w3a", "123", "hfoo"])
def test_queries_search_keys_labels_values_sources_and_identity_details(
    tmp_path: Path, command: str, table: str, query: str
) -> None:
    _pack(tmp_path, table)
    result = _run(tmp_path, command, query)
    assert result.exit_code == 0 and "[X001]" in result.render()


@pytest.mark.parametrize("command,table", _COMMANDS)
def test_boolean_terms_keep_field_boundaries_and_exact_case(
    tmp_path: Path, command: str, table: str
) -> None:
    path = _pack(tmp_path, table)
    with path.open("a", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t").writerow(
            [table, "X001", "对象别名1", "ExactKey", "标记", "ExactCase", "map"]
        )
    assert _run(tmp_path, command, '="ExactCase" && 完整尾部').exit_code == 0
    assert _run(tmp_path, command, '="exactcase"').exit_code == 2
    assert _run(tmp_path, command, "独有火焰完整尾部").exit_code == 2


@pytest.mark.parametrize("command,table", _COMMANDS)
@pytest.mark.parametrize("limit", [0, 1, 3])
def test_object_limits_keep_each_selected_objects_fields_complete(
    tmp_path: Path, command: str, table: str, limit: int
) -> None:
    path = _pack(tmp_path, table, count=3)
    with path.open("a", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t").writerows(
            [
                [table, "X001", "对象别名1", f"level{i}", "字段", f"完整值{i}", "map"]
                for i in range(5000)
            ]
        )
    text = _run(tmp_path, command, "", limit).render()
    shown = limit if limit else 3
    assert sum(line.startswith("[X") for line in text.splitlines()) == shown
    assert "完整值4999" in text
    if limit == 1:
        assert "其余 2 条未显示" in text and "[X002]" not in text
    else:
        assert "未显示" not in text


@pytest.mark.parametrize("command,table", _COMMANDS)
def test_field_records_never_cross_categories_with_the_same_code(
    tmp_path: Path, command: str, table: str
) -> None:
    _pack(tmp_path, table)
    other = "技能" if table != "技能" else "单位"
    with (tmp_path / "对象字段.tsv").open("a", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t").writerow(
            [other, "X001", "其他类别", "OnlyOther", "无关", "其他类别独有值", "map"]
        )
    assert _run(tmp_path, command, "其他类别独有值").exit_code == 2
    assert "其他类别独有值" not in _run(tmp_path, command, "X001").render()


@pytest.mark.parametrize("command,table", _COMMANDS)
def test_field_only_names_do_not_invent_base_ids_or_custom_flags(
    tmp_path: Path, command: str, table: str
) -> None:
    _pack(tmp_path, table, ids=False)
    text = _run(tmp_path, command, "X001").render()
    assert "ID 清单未收录" in text and "自定义标记未记录" in text
    assert "(自定义)" not in text and "(继承基础)" not in text


@pytest.mark.parametrize("command,table", _COMMANDS)
def test_bad_id_headers_keep_known_field_objects_and_the_original_diagnostic(
    tmp_path: Path, command: str, table: str
) -> None:
    _pack(tmp_path, table)
    _write(
        tmp_path / "对象ID" / f"{table}.tsv",
        [["ID", "ID", "名称"], ["X001", "X002", "冲突"]],
    )
    result = _run(tmp_path, command, "X001")
    assert (
        result.exit_code == 0
        and "完整尾部" in result.render()
        and "重复语义列" in result.render()
    )


@pytest.mark.parametrize("command,table", _COMMANDS)
def test_a_missing_object_has_a_count_and_data_source_recovery_paths(
    tmp_path: Path, command: str, table: str
) -> None:
    result = _run(tmp_path, command, "不存在")
    text = result.render()
    assert result.exit_code == 2 and "0 项" in text
    assert (
        "对象字段.tsv" in text
        and "重新导出" in text
        and "near" in text
        and "search" in text
    )
    assert "地图未自定义" not in text


def test_extra_columns_and_multi_line_values_are_not_shortened(tmp_path: Path) -> None:
    path = _pack(tmp_path, "技能")
    value = "完整\n\t文本" * 5000 + "最终尾部"
    _write(
        path,
        [
            [*_FIELD_HEADER, "", "扩展字段8", *[f"声明{i}" for i in range(2000)]],
            [
                "技能",
                "X001",
                "对象别名",
                "UnknownKey",
                "字段",
                value,
                "map",
                "无名附证",
                "有名附证",
            ],
        ],
    )
    text = _run(tmp_path, "skills", "最终尾部", limit=1).render()
    assert value in text and "无名附证" in text and "有名附证" in text


def test_id_table_extra_fields_participate_and_remain_visible(tmp_path: Path) -> None:
    _pack(tmp_path, "技能")
    _write(
        tmp_path / "对象ID" / "技能.tsv",
        [
            [*_ID_HEADER, "英文名"],
            ["技能", "X001", "1", "zzzz", "主名称", "是", "完整说明", "OriginalName"],
        ],
    )
    assert "OriginalName" in _run(tmp_path, "skills", "OriginalName").render()


def test_field_only_name_aliases_are_all_preserved(tmp_path: Path) -> None:
    path = _pack(tmp_path, "技能", ids=False)
    with path.open("a", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t").writerow(
            ["技能", "X001", "第二别名", "other", "字段", "另值", "map"]
        )
    text = _run(tmp_path, "skills", "第二别名").render()
    assert (
        "对象别名1" in text
        and "第二别名" in text
        and sum(line.startswith("[X001]") for line in text.splitlines()) == 1
    )


def test_long_compiled_expressions_have_no_recursive_nesting_ceiling(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, "技能")
    assert _run(tmp_path, "skills", "(" * 5000 + "完整尾部" + ")" * 5000).exit_code == 0


def test_name_aliases_keep_their_original_field_boundaries(tmp_path: Path) -> None:
    path = _pack(tmp_path, "技能", ids=False)
    with path.open("a", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t").writerow(
            ["技能", "X001", "第二别名", "other", "字段", "另值", "map"]
        )
    assert _run(tmp_path, "skills", '="对象别名1 / 第二别名"').exit_code == 2
    assert _run(tmp_path, "skills", "对象别名1 && 第二别名").exit_code == 0


def test_only_selected_object_fields_are_rendered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool.pack_query_field_evidence import ObjectField

    _pack(tmp_path, "单位", count=3)
    rendered: list[str] = []
    real = ObjectField.render_lines

    def track(self: ObjectField, indent: str = "    "):
        rendered.append(self.key)
        return real(self, indent)

    monkeypatch.setattr(ObjectField, "render_lines", track)
    assert _run(tmp_path, "units", "", limit=1).exit_code == 0
    assert len(rendered) == 3


def test_field_details_refresh_after_same_size_same_mtime_edits(tmp_path: Path) -> None:
    import os

    path = _pack(tmp_path, "技能")
    first = _run(tmp_path, "skills", "完整尾部")
    stat = path.stat()
    path.write_bytes(
        path.read_bytes().replace("完整尾部".encode(), "更新尾部".encode())
    )
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    second = _run(tmp_path, "skills", "更新尾部")
    assert first.exit_code == second.exit_code == 0 and "更新尾部" in second.render()
    assert (
        path.stat().st_size == stat.st_size
        and path.stat().st_mtime_ns == stat.st_mtime_ns
    )


def test_bad_field_record_indices_stay_complete_under_limit_one(tmp_path: Path) -> None:
    path = _pack(tmp_path, "技能")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("技能\tbad\n" * 5000)
    result = _run(tmp_path, "skills", "X001", limit=1)
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 0 and "完整尾部" in result.render()
    assert any(
        ", ".join(map(str, range(5, 5005))) in warning for warning in data["warnings"]
    )


@pytest.mark.parametrize("command,table", _COMMANDS)
def test_campaigns_include_children_with_only_object_field_evidence(
    tmp_path: Path, command: str, table: str
) -> None:
    child = tmp_path / "子地图" / "001"
    _pack(child, table, ids=False)
    result = _run(tmp_path, command, "完整尾部")
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 0 and result.campaign and len(data["sections"]) == 1
    assert data["sections"][0]["pack"] == str(child) and "[X001]" in result.render()
