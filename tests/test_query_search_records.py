"""Search results retain complete records even when their names or IDs already match."""

import csv
import json
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool import search
from gametool.pack_query_options import PackQueryCliOptions

_TABLES = ("物品", "单位", "技能", "英雄", "增益", "科技", "装饰物", "可破坏物")


@pytest.fixture(autouse=True)
def isolate_memo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _objects(
    pack: Path,
    category: str,
    count: int = 1,
    description: str = "火焰伤害增加 100；完整说明末尾",
    extra: int = 1,
) -> None:
    parent = pack / "对象ID"
    parent.mkdir(parents=True, exist_ok=True)
    with (parent / f"{category}.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(
            [
                "分类",
                "ID",
                "数值",
                "基础ID",
                "名称",
                "自定义",
                "说明",
                *(f"扩展{i}" for i in range(extra)),
            ]
        )
        for index in range(count):
            code = chr(ord("I") + index // 4096) + f"{index % 4096:03x}"
            writer.writerow(
                [
                    category,
                    code,
                    65536 + index,
                    "base",
                    f"火焰剑{index}",
                    "是",
                    description,
                    *(f"完整扩展值{i}" for i in range(extra)),
                ]
            )


@pytest.mark.parametrize("category", _TABLES)
@pytest.mark.parametrize("mode", ["name", "id", "category"])
def test_every_table_displays_complete_evidence_for_name_id_or_category_hits(
    tmp_path: Path, category: str, mode: str
) -> None:
    _objects(tmp_path, category)
    expression = {"name": "火焰", "id": "I000", "category": ""}[mode]
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "search", category + ":" + expression)
    )
    text = result.render()
    assert result.exit_code == 0 and "[I000] 火焰剑0" in text
    assert "数值: 65536" in text and "基础ID: base" in text
    assert "说明: 火焰伤害增加 100；完整说明末尾" in text
    assert "扩展0: 完整扩展值0" in text


@pytest.mark.parametrize("spelling", ["0", "all", "全部", "1"])
def test_explicit_limits_count_records_and_never_shorten_multiline_fields(
    tmp_path: Path, spelling: str
) -> None:
    description = "\n".join(f"火焰说明完整行{i}" for i in range(2000))
    _objects(tmp_path, "物品", 3, description)
    options = queries.parse_pack_query_cli_options(
        [str(tmp_path), "search", "物品:火焰", "--limit", spelling]
    )
    result = queries.execute_pack_query(options)
    text = result.render()
    expected = 1 if spelling == "1" else 3
    assert result.exit_code == 0 and text.count("  [I") == expected
    assert text.count(description) == expected
    assert ("其余 2 条未显示" in text) == (spelling == "1")
    data = json.loads(result.render(as_json=True))
    assert data["exit_code"] == 0 and description in "\n".join(data["lines"])


def test_exact_record_limit_has_no_false_remainder(tmp_path: Path) -> None:
    _objects(tmp_path, "物品", 2)
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "search", "火焰", limit=2)
    )
    assert (
        result.render().count("完整说明末尾") == 2 and "条未显示" not in result.render()
    )


def test_all_1500_extra_fields_remain_in_a_single_limited_record(
    tmp_path: Path,
) -> None:
    _objects(tmp_path, "物品", 1, extra=1500)
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "search", "I000", limit=1)
    )
    text = result.render()
    assert result.exit_code == 0 and all(
        f"扩展{i}: 完整扩展值{i}" in text for i in range(1500)
    )


def test_campaign_search_json_and_again_keep_full_name_match_evidence(
    tmp_path: Path,
) -> None:
    for index in range(3):
        _objects(tmp_path / "子地图" / f"{index:03}", "物品")
    first = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "search", "火焰")
    )
    again = queries.execute_pack_query(PackQueryCliOptions(str(tmp_path), "again", ""))
    for result in [first, again]:
        data = json.loads(result.render(as_json=True))
        assert result.exit_code == 0 and result.campaign and len(data["sections"]) == 3
        assert all(
            "完整说明末尾" in "\n".join(section["lines"])
            for section in data["sections"]
        )


def test_search_does_not_evaluate_name_matches_a_second_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _objects(tmp_path, "物品", 10)
    original = search.CompiledQuery.score_fields
    calls = 0

    def counted(self, fields):
        nonlocal calls
        calls += 1
        return original(self, fields)

    monkeypatch.setattr(search.CompiledQuery, "score_fields", counted)
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "search", "火焰")
    )
    assert result.exit_code == 0 and result.render().count("完整说明末尾") == 10
    assert calls <= 10


def test_5000_name_matches_keep_the_last_complete_record(tmp_path: Path) -> None:
    _objects(tmp_path, "物品", 5000)
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "search", "火焰")
    )
    text = result.render()
    assert result.exit_code == 0 and text.count("完整说明末尾") == 5000
    assert "[J387] 火焰剑4999" in text and "条未显示" not in text
