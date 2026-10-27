"""Global search covers category-qualified object fields and field-only records."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_options import PackQueryCliOptions
from gametool.pack_query_objects import OBJECT_TABLES

_ID_HEADER = ["分类", "ID", "数值", "基础ID", "名称", "自定义", "说明"]
_FIELD_HEADER = ["分类", "ID", "名称", "字段键", "字段名", "值", "来源", "扩展说明"]


@pytest.fixture(autouse=True)
def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _write(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream, delimiter="\t", lineterminator="\n").writerows(rows)


def _pack(
    pack: Path,
    *,
    tables: tuple[str, ...] = OBJECT_TABLES,
    ids: bool = True,
    count: int = 1,
) -> None:
    fields = [_FIELD_HEADER]
    for category in tables:
        if ids:
            _write(
                pack / "对象ID" / (category + ".tsv"),
                [
                    _ID_HEADER,
                    *[
                        [
                            category,
                            f"X{i:03x}",
                            str(i),
                            "hfoo",
                            category + "主表对象",
                            "是",
                            "ID清单说明",
                        ]
                        for i in range(1, count + 1)
                    ],
                ],
            )
        for i in range(1, count + 1):
            fields.extend(
                [
                    [
                        category,
                        f"X{i:03x}",
                        category + "字段别名",
                        "DataA:1",
                        "攻击标签",
                        "火焰",
                        category + ".map",
                        "类别附证" + category,
                    ],
                    [
                        category,
                        f"X{i:03x}",
                        category + "字段别名",
                        "DataB:2",
                        "防御标签",
                        "寒冰",
                        category + ".map",
                        "尾部完整",
                    ],
                ]
            )
    _write(pack / "对象字段.tsv", fields)


def _search(pack: Path, query: str, limit: int = 0):
    return queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "search", query, limit=limit)
    )


@pytest.mark.parametrize("category", OBJECT_TABLES)
@pytest.mark.parametrize("ids", [False, True])
def test_search_keeps_complete_own_fields_and_field_only_identities(
    tmp_path: Path, category: str, ids: bool
) -> None:
    _pack(tmp_path, ids=ids)
    for keyword in [
        "X001",
        "字段别名",
        "火焰 && 寒冰",
        "尾部完整",
        category + ".map",
        "",
    ]:
        result = _search(tmp_path, category + ":" + keyword)
        text = result.render()
        assert result.exit_code == 0
        assert [line for line in result.sections[0].lines if line.startswith("==")] == [
            f"== {category} (1 个)=="
        ]
        assert "DataA:1" in text and "DataB:2" in text and "类别附证" + category in text
        assert ("ID 清单未收录" in text) == (not ids)
        assert ("基础ID: hfoo" in text) == ids


@pytest.mark.parametrize(
    "alias,category",
    list(
        zip(
            [
                "item",
                "unit",
                "ability",
                "hero",
                "buff",
                "upgrade",
                "doodad",
                "destructible",
            ],
            OBJECT_TABLES,
        )
    ),
)
def test_search_category_aliases_share_declared_object_categories(
    tmp_path: Path, alias: str, category: str
) -> None:
    _pack(tmp_path, ids=False)
    result = _search(tmp_path, alias + ":火焰 && 寒冰")
    assert result.exit_code == 0 and f"== {category} (1 个)==" in result.render()
    assert sum(line.startswith("==") for line in result.sections[0].lines) == 1


@pytest.mark.parametrize("query", ["火焰 && 寒冰", '="火焰寒冰"'])
def test_search_never_combines_different_objects_or_categories(
    tmp_path: Path, query: str
) -> None:
    _write(
        tmp_path / "对象字段.tsv",
        [
            _FIELD_HEADER,
            ["物品", "X001", "甲", "A", "", "火焰", "map", ""],
            ["单位", "X001", "乙", "B", "", "寒冰", "map", ""],
            ["物品", "X002", "丙", "B", "", "寒冰", "map", ""],
        ],
    )
    result = _search(tmp_path, query)
    assert result.exit_code == 2 and "[X001]" not in result.render()


def test_limits_select_whole_records_in_each_section_and_render_selected_fields_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool.pack_query_field_evidence import ObjectField

    _pack(tmp_path, ids=False, count=3)
    rendered: list[str] = []
    real = ObjectField.render_lines

    def track(self: ObjectField, indent: str = "    "):
        rendered.append(self.key)
        return real(self, indent)

    monkeypatch.setattr(ObjectField, "render_lines", track)
    result = _search(tmp_path, "火焰", limit=1)
    assert result.exit_code == 0 and len(rendered) == 16
    assert result.render().count("其余 2 条") == 8
    assert result.render().count("尾部完整") == 8


def test_field_table_is_loaded_once_and_expression_is_evaluated_once_per_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool.search import CompiledQuery

    _pack(tmp_path, ids=False, count=2)
    loads, scores = [], []
    real_load, real_score = queries._named_table, CompiledQuery.score_fields

    def load(pack: Path, relative: str, table: str = ""):
        if relative == "对象字段.tsv":
            loads.append(relative)
        return real_load(pack, relative, table)

    def score(self, fields):
        scores.append(1)
        return real_score(self, fields)

    monkeypatch.setattr(queries, "_named_table", load)
    monkeypatch.setattr(CompiledQuery, "score_fields", score)
    assert _search(tmp_path, "火焰").exit_code == 0
    assert len(loads) == 1 and len(scores) == 16


def test_search_retains_complete_long_quoted_fields_and_original_bytes(
    tmp_path: Path,
) -> None:
    value = '完整长文\ufeff"引用"\r\n' * 10000
    path = tmp_path / "对象字段.tsv"
    _write(
        path,
        [
            _FIELD_HEADER,
            ["物品", "X001", "长字段物品", "Long", "正文", value, "map", "尾部证据"],
        ],
    )
    before = path.read_bytes()
    result = _search(tmp_path, "长字段物品", limit=1)
    assert (
        result.exit_code == 0
        and value in result.render()
        and "尾部证据" in result.render()
    )
    assert before == path.read_bytes()


def test_search_same_size_same_mtime_field_updates_refresh_results(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, ids=False, tables=("物品",))
    path = tmp_path / "对象字段.tsv"
    assert _search(tmp_path, "火焰").exit_code == 0
    info = path.stat()
    path.write_bytes(path.read_bytes().replace("火焰".encode(), "雷电".encode()))
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
    assert _search(tmp_path, "火焰").exit_code == 2
    assert _search(tmp_path, "雷电").exit_code == 0


def test_campaign_search_keeps_field_only_hits_and_diagnostic_only_scopes(
    tmp_path: Path,
) -> None:
    good, bad = tmp_path / "子地图" / "001", tmp_path / "子地图" / "002"
    _pack(good, ids=False, tables=("物品",))
    _write(
        bad / "对象字段.tsv",
        [["分类", "ID", "字段键", "字段键", "值"], ["物品", "X001", "A", "B", "火焰"]],
    )
    result = _search(tmp_path, "火焰")
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 0 and result.campaign
    assert any(section["pack"] == str(good) for section in data["sections"])
    assert any(section["pack"] == str(bad) for section in data["sections"])
    assert "重复语义列" in result.render() and str(bad) in "\n".join(data["warnings"])
    replay = queries.execute_pack_query(PackQueryCliOptions(str(tmp_path), "again", ""))
    assert replay.exit_code == 0 and "尾部完整" in replay.render()


@pytest.mark.parametrize("layout", ["english", "reordered", "headerless"])
def test_search_uses_the_shared_field_schema_for_all_known_layouts(
    tmp_path: Path, layout: str
) -> None:
    row = ["物品", "X001", "字段别名", "A", "标签", "唯一字段证据", "map"]
    header = _FIELD_HEADER[:7]
    if layout == "english":
        header = [
            "category",
            "id",
            "name",
            "field_key",
            "field_label",
            "value",
            "source",
        ]
    if layout == "reordered":
        header, row = header[::-1], row[::-1]
    _write(
        tmp_path / "对象字段.tsv", ([header] if layout != "headerless" else []) + [row]
    )
    result = _search(tmp_path, "唯一字段证据")
    assert result.exit_code == 0 and "[X001]" in result.render()


def test_search_full_field_only_listing_has_no_record_ceiling(tmp_path: Path) -> None:
    _pack(tmp_path, ids=False, tables=("物品",), count=4000)
    result = _search(tmp_path, "物品:")
    assert result.exit_code == 0 and "== 物品 (4000 个)==" in result.render()
    assert result.render().count("尾部完整") == 4000 and "[Xfa0]" in result.render()


@pytest.mark.parametrize("flag", ["是", "任意原始标记"])
def test_search_preserves_and_searches_explicit_custom_metadata(
    tmp_path: Path, flag: str
) -> None:
    _write(
        tmp_path / "对象ID" / "物品.tsv",
        [_ID_HEADER, ["物品", "X001", "1", "", "普通名称", flag, ""]],
    )
    result = _search(tmp_path, "物品:" + flag)
    assert result.exit_code == 0 and "自定义标记: " + flag in result.render()
