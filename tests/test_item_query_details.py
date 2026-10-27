"""Item queries search full item/ability fields and preserve selected evidence."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Iterator
import json
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_options import PackQueryCliOptions

_ID_HEADER = ["分类", "ID", "数值", "基础ID", "名称", "自定义", "说明", "英文名"]
_FIELD_HEADER = ["分类", "ID", "名称", "字段键", "字段名", "值", "来源", "额外说明"]


@pytest.fixture(autouse=True)
def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _write(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream, delimiter="\t", lineterminator="\n").writerows(rows)


def _pack(pack: Path, *, ids: bool = True, count: int = 1) -> None:
    if ids:
        _write(
            pack / "对象ID" / "物品.tsv",
            [
                _ID_HEADER,
                *[
                    [
                        "物品",
                        f"I{i:03x}",
                        str(i),
                        "ratf",
                        f"主表物品{i}",
                        "是",
                        "主表说明",
                        "ArtifactSword",
                    ]
                    for i in range(1, count + 1)
                ],
            ],
        )
    rows = [_FIELD_HEADER]
    for i in range(1, count + 1):
        code = f"I{i:03x}"
        for key, label, value, extra in [
            ("textA", "攻击标签", "火焰", "额外物品证据"),
            ("textB", "防御标签", "寒冰", ""),
            ("ides", "地图描述", "地图尾部说明\r\n第二段", ""),
            ("igol", "地图黄金", "999", ""),
            ("iabi", "携带技能", "A001", ""),
            ("base:iabi", "继承技能", "A002", ""),
        ]:
            rows.append(
                ["物品", code, f"字段别名{i}", key, label, value, "war3map.w3t", extra]
            )
    rows.extend(
        [
            [
                "技能",
                "A001",
                "可见技名",
                "Istr:1",
                "力量标签",
                "+0011",
                "war3map.w3a",
                "",
            ],
            [
                "技能",
                "A001",
                "可见技名",
                "DataA:17",
                "完整技能字段",
                "技能尾部\ufeff文本",
                "war3map.w3a",
                "额外技能证据",
            ],
            [
                "技能",
                "A002",
                "继承技名",
                "Istr1",
                "力量",
                "88",
                "war3map.w3a",
                "继承仅有",
            ],
            [
                "技能",
                "A003",
                "未关联技名",
                "DataA1",
                "无关",
                "未关联噪声",
                "war3map.w3a",
                "",
            ],
            [
                "单位",
                "I001",
                "同码单位",
                "unitField",
                "单位",
                "单位噪声",
                "war3map.w3u",
                "",
            ],
        ]
    )
    _write(pack / "对象字段.tsv", rows)


def _item(pack: Path, query: str = "I001", limit: int = 0):
    return queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "item", query, limit=limit)
    )


@pytest.mark.parametrize("ids", [False, True])
@pytest.mark.parametrize(
    "query",
    [
        "I001",
        "字段别名1",
        "尾部说明",
        "火焰 && 寒冰",
        "额外物品证据",
        "技能尾部",
        "可见技名",
        "额外技能证据",
    ],
)
def test_items_search_complete_item_and_selected_ability_fields(
    tmp_path: Path, ids: bool, query: str
) -> None:
    _pack(tmp_path, ids=ids)
    result = _item(tmp_path, query)
    text = result.render()
    assert result.exit_code == 0 and "[I001]" in text
    assert "textA" in text and "textB" in text and "额外物品证据" in text
    assert "技能尾部" in text and "额外技能证据" in text and "+0011 力量" in text
    assert "金币: 999" in text and "地图尾部说明" in text and "第二段" in text
    assert ("ID 清单未收录" in text) == (not ids)
    if not ids:
        assert "基础ID: ratf" not in text and "继承基础 ratf" not in text


@pytest.mark.parametrize("query", ["ArtifactSword", "主表说明"])
def test_item_id_table_description_and_extra_columns_are_searchable(
    tmp_path: Path, query: str
) -> None:
    _pack(tmp_path)
    text = _item(tmp_path, query).render()
    assert "[I001]" in text and "ArtifactSword" in text and "主表说明" in text


@pytest.mark.parametrize(
    "query", ["继承仅有", "未关联噪声", "单位噪声", '= "火焰寒冰"']
)
def test_item_search_respects_link_selection_categories_and_field_boundaries(
    tmp_path: Path, query: str
) -> None:
    _pack(tmp_path)
    result = _item(tmp_path, query)
    assert result.exit_code == 2 and "未找到物品" in result.render()
    assert "text" in result.render() and "near" in result.render()


def test_field_only_identity_requires_declared_item_category_and_four_byte_code(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "对象字段.tsv",
        [
            _FIELD_HEADER,
            ["单位", "I001", "单位", "textA", "", "单位噪声", "map", ""],
            ["物品", "invalid", "错误码", "textA", "", "无效身份", "map", ""],
        ],
    )
    result = _item(tmp_path, "")
    assert (
        result.exit_code == 2
        and "[I001]" not in result.render()
        and "[invalid]" not in result.render()
    )


def test_result_limit_keeps_complete_item_and_only_renders_selected_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool.pack_query_item_abilities import ItemAbilityIndex

    _pack(tmp_path, count=5)
    rendered: list[str] = []
    real = ItemAbilityIndex.render_item

    def track(self: ItemAbilityIndex, code: str):
        rendered.append(code)
        return real(self, code)

    monkeypatch.setattr(ItemAbilityIndex, "render_item", track)
    result = _item(tmp_path, "火焰", limit=1)
    assert rendered == ["I001"] and "其余 4 条" in result.render()
    assert "额外物品证据" in result.render() and "额外技能证据" in result.render()


def test_field_only_campaign_item_is_queryable_and_again_retains_result(
    tmp_path: Path,
) -> None:
    child = tmp_path / "子地图" / "001"
    _pack(child, ids=False)
    result = _item(tmp_path, "技能尾部")
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 0
    assert any(section["pack"] == str(child) for section in data["sections"])
    replay = queries.execute_pack_query(PackQueryCliOptions(str(tmp_path), "again", ""))
    assert replay.exit_code == 0 and "技能尾部" in replay.render()


def test_full_item_listing_has_no_record_ceiling_and_does_not_mutate_sources(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, count=1500)
    paths = list(tmp_path.rglob("*.tsv"))
    before = {path: path.read_bytes() for path in paths}
    result = _item(tmp_path, "")
    assert result.exit_code == 0
    assert sum(line.startswith("[I") for line in result.sections[0].lines) == 1500
    assert before == {path: path.read_bytes() for path in paths}


def test_all_known_item_and_skill_fields_keep_complete_long_values(
    tmp_path: Path,
) -> None:
    _pack(tmp_path)
    path = tmp_path / "对象字段.tsv"
    tail = "完整长文" * 40000
    with path.open("a", encoding="utf-8", newline="") as stream:
        csv.writer(stream, delimiter="\t").writerow(
            ["物品", "I001", "长别名", "LongField", "正文", tail, "map", "尾部证据"]
        )
    text = _item(tmp_path, "长别名").render()
    assert tail in text and "尾部证据" in text


def test_field_only_item_does_not_infer_a_vanilla_price(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(
        tmp_path / "对象字段.tsv",
        [
            _FIELD_HEADER,
            ["物品", "ratf", "字段物品", "textA", "", "原始证据", "map", ""],
        ],
    )
    monkeypatch.setattr(queries, "_base_prices", lambda: {"ratf": "9999"})
    text = _item(tmp_path, "ratf").render()
    assert "[ratf]" in text and "ID 清单未收录" in text and "金币:" not in text


def test_item_expression_runs_once_per_record_and_shared_skill_fields_are_prepared_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool.pack_query_field_evidence import ObjectField
    from gametool.search import CompiledQuery

    _pack(tmp_path, count=50)
    scored, prepared = [], []
    real_score, real_fields = CompiledQuery.score_fields, ObjectField.search_fields

    def score(self: CompiledQuery, fields: Iterable[str]) -> int | None:
        scored.append(1)
        return real_score(self, fields)

    def fields(self: ObjectField, clean) -> Iterator[str]:
        if self.key == "DataA:17":
            prepared.append(1)
        yield from real_fields(self, clean)

    monkeypatch.setattr(CompiledQuery, "score_fields", score)
    monkeypatch.setattr(ObjectField, "search_fields", fields)
    result = _item(tmp_path, "火焰 && 技能尾部", limit=1)
    assert result.exit_code == 0 and len(scored) == 50 and len(prepared) == 1
    assert "其余 49 条" in result.render()


def test_explicit_empty_item_ability_does_not_search_overridden_skill_fields(
    tmp_path: Path,
) -> None:
    _pack(tmp_path)
    path = tmp_path / "对象字段.tsv"
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream, delimiter="\t"))
    for row in rows[1:]:
        if row[0] == "物品" and row[3] == "iabi":
            row[5] = ""
    _write(path, rows)
    assert _item(tmp_path, "技能尾部").exit_code == 2
    text = _item(tmp_path, "I001").render()
    assert (
        "显式空值" in text and "已被自定义 iabi 覆盖" in text and "Istr:1" not in text
    )


@pytest.mark.parametrize("code", ["i!é?", "I001"])
def test_field_only_item_accepts_complete_four_byte_identities(
    tmp_path: Path, code: str
) -> None:
    _write(
        tmp_path / "对象字段.tsv",
        [_FIELD_HEADER, ["物品", code, "字段物品", "textA", "", "原始证据", "map", ""]],
    )
    result = _item(tmp_path, '="' + code + '"')
    assert result.exit_code == 0 and "[" + code + "]" in result.render()


@pytest.mark.parametrize("tail", [[], [""], ["   "]])
def test_cli_item_accepts_empty_keyword_for_a_complete_listing(
    tmp_path: Path, tail: list[str]
) -> None:
    _pack(tmp_path, count=2)
    options = queries.parse_pack_query_cli_options([str(tmp_path), "item", *tail])
    assert options.query == "" and options.limit == 0
    result = queries.execute_pack_query(options)
    assert result.exit_code == 0
    assert sum(line.startswith("[I") for line in result.sections[0].lines) == 2
    assert queries._load_last_query() == {
        "pack": str(tmp_path),
        "command": "item",
        "query": "",
    }
    replay = queries.execute_pack_query(PackQueryCliOptions(str(tmp_path), "again", ""))
    assert replay.exit_code == 0 and "[I002]" in replay.render()
