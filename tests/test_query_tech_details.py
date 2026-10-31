"""Full technology evidence and exact, non-enumerating level-cost calculations."""

from __future__ import annotations

import csv
from decimal import getcontext
import json
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_options import PackQueryCliOptions

_ID_HEADER = ["分类", "ID", "数值", "基础ID", "名称", "自定义", "说明"]
_FIELD_HEADER = ["分类", "ID", "名称", "字段键", "字段名", "值", "来源", "扩展"]


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
            pack / "对象ID" / "科技.tsv",
            [
                _ID_HEADER,
                *[
                    [
                        "科技",
                        f"R{i:03x}",
                        str(i),
                        "rhlh",
                        "主表科技" + str(i),
                        "是",
                        "主表说明",
                    ]
                    for i in range(1, count + 1)
                ],
            ],
        )
    rows = [_FIELD_HEADER]
    for i in range(1, count + 1):
        for key, value in {
            "glvl": "3",
            "gglb": "9007199254740993",
            "gglm": "2",
            "glmb": "3",
            "glmm": "1",
            "gub1:1": "火焰效果",
            "gub1:3": "寒冰末级效果",
            "greq:3": "R002",
            "OtherField": "扩展完整原文",
        }.items():
            rows.append(
                [
                    "科技",
                    f"R{i:03x}",
                    "字段别名" + str(i),
                    key,
                    key,
                    value,
                    "war3map.w3q",
                    "附加完整证据",
                ]
            )
    _write(pack / "对象字段.tsv", rows)


def _tech(pack: Path, query: str = "R001", limit: int = 0):
    return queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "tech", query, limit=limit)
    )


@pytest.mark.parametrize("ids", [False, True])
@pytest.mark.parametrize("query", ["R001", "字段别名1", "火焰 && 寒冰", "附加完整证据"])
def test_tech_queries_keep_complete_own_fields_and_field_only_identities(
    tmp_path: Path, ids: bool, query: str
) -> None:
    _pack(tmp_path, ids=ids)
    result = _tech(tmp_path, query)
    text = result.render()
    assert result.exit_code == 0
    assert "OtherField" in text and "扩展完整原文" in text and "附加完整证据" in text
    assert "9007199254740993" in text and "9007199254740997" in text
    assert ("ID 清单未收录" in text) == (not ids)


def test_costs_and_totals_do_not_round_through_binary_float(tmp_path: Path) -> None:
    _pack(tmp_path)
    text = _tech(tmp_path).render()
    assert "3级 金9007199254740997 木5" in text
    assert "满级累计: 金27021597764222985 木12" in text


def test_conflicting_scalars_never_choose_a_winner_or_inherit_a_base_value(
    tmp_path: Path,
) -> None:
    _pack(tmp_path)
    path = tmp_path / "对象字段.tsv"
    with path.open("a", encoding="utf-8", newline="") as stream:
        csv.writer(stream, delimiter="\t").writerow(
            ["科技", "R001", "冲突别名", "gglb", "金币", "7", "other.w3q", "冲突末尾"]
        )
    text = _tech(tmp_path).render()
    assert "冲突" in text and "other.w3q" in text and "冲突末尾" in text
    assert "金9007199254740997" not in text and "金100" not in text


@pytest.mark.parametrize(
    "value", ["", "bad", "NaN", "Infinity", "'100", "''100", "' 100"]
)
def test_explicit_invalid_cost_never_silently_falls_back_to_base(
    tmp_path: Path, value: str
) -> None:
    _write(
        tmp_path / "对象ID" / "科技.tsv",
        [_ID_HEADER, ["科技", "R001", "1", "Rhlh", "科技", "是", ""]],
    )
    _write(
        tmp_path / "对象字段.tsv",
        [
            _FIELD_HEADER,
            ["科技", "R001", "科技", "gglb", "金币", value, "map", "原始保留"],
        ],
    )
    text = _tech(tmp_path).render()
    assert "未确认" in text and "原始保留" in text and "金 100" not in text


@pytest.mark.parametrize("base_id,confirmed", [("Rhlh", True), ("rhlh", False)])
def test_technology_base_costs_require_case_sensitive_declared_identity(
    tmp_path: Path, base_id: str, confirmed: bool
) -> None:
    _write(
        tmp_path / "对象ID" / "科技.tsv",
        [_ID_HEADER, ["科技", "R001", "1", base_id, "科技", "是", ""]],
    )
    text = _tech(tmp_path).render()
    assert ("每级费用: 金 100" in text) is confirmed
    assert f"基础: {base_id}" in text


def test_default_schedule_does_not_allocate_from_huge_declared_level_count(
    tmp_path: Path,
) -> None:
    level = "9" * 5000
    rows = [
        _FIELD_HEADER,
        *[
            ["科技", "R001", "巨大等级科技", key, key, value, "map", ""]
            for key, value in {
                "glvl": level,
                "gglb": "1",
                "gglm": "0",
                "glmb": "0",
                "glmm": "0",
            }.items()
        ],
    ]
    _write(tmp_path / "对象字段.tsv", rows)
    text = _tech(tmp_path).render()
    assert "费用公式" in text and level in text and "满级累计: 金" + level in text
    assert text.count("级 金") <= 2


def test_all_long_level_labels_and_conflicting_effect_records_are_retained(
    tmp_path: Path,
) -> None:
    _pack(tmp_path)
    level = "8" * 5000
    path = tmp_path / "对象字段.tsv"
    with path.open("a", encoding="utf-8", newline="") as stream:
        csv.writer(stream, delimiter="\t").writerows(
            [
                [
                    "科技",
                    "R001",
                    "科技",
                    "gub1:" + level,
                    "效果",
                    "超长等级末尾",
                    "map",
                    "超长等级证据",
                ],
                [
                    "科技",
                    "R001",
                    "科技",
                    "gub1:1",
                    "效果",
                    "另一效果",
                    "other",
                    "完整冲突效果",
                ],
            ]
        )
    text = _tech(tmp_path).render()
    assert (
        level in text
        and "超长等级末尾" in text
        and "另一效果" in text
        and "火焰效果" in text
    )


@pytest.mark.parametrize("level", ["2", "0002", "9" * 5000])
def test_explicit_level_selector_accepts_complete_positive_integer_text(
    tmp_path: Path, level: str
) -> None:
    _pack(tmp_path)
    options = queries.parse_pack_query_cli_options(
        [str(tmp_path), "tech", "R001", "--level", level]
    )
    result = queries.execute_pack_query(options)
    text = result.render()
    assert result.exit_code == 0 and "所查等级费用" in text
    if len(level) < 10:
        assert "2级 金9007199254740995 木4" in text
    else:
        assert level in text and "超出" in text


@pytest.mark.parametrize("level", ["0", "-1", "1.5", "NaN", ""])
def test_invalid_level_selector_is_rejected_before_reading_data(
    tmp_path: Path, level: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args, **kwargs):
        pytest.fail("invalid level reached data access")

    monkeypatch.setattr(queries, "_named_table", forbidden)
    with pytest.raises(queries.PackQueryCliOptionError):
        queries.parse_pack_query_cli_options(
            [str(tmp_path), "tech", "R001", "--level", level]
        )


def test_tech_empty_listing_and_level_query_replay_keep_private_history(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, ids=False, count=2)
    options = queries.parse_pack_query_cli_options(
        [str(tmp_path), "tech", "--level", "2"]
    )
    result = queries.execute_pack_query(options)
    assert (
        result.exit_code == 0
        and "[R001]" in result.render()
        and "[R002]" in result.render()
    )
    replay = queries.execute_pack_query(PackQueryCliOptions(str(tmp_path), "again", ""))
    assert replay.exit_code == 0 and "所查等级费用" in replay.render()


def test_record_limits_preserve_every_selected_tech_field(tmp_path: Path) -> None:
    _pack(tmp_path, count=3)
    text = _tech(tmp_path, "火焰", limit=1).render()
    assert "[R001]" in text and "[R002]" not in text and "其余 2 条" in text
    assert "OtherField" in text and "寒冰末级效果" in text and "附加完整证据" in text


def test_field_only_campaign_tech_keeps_its_source_section(tmp_path: Path) -> None:
    child = tmp_path / "子地图" / "001"
    _pack(child, ids=False)
    result = _tech(tmp_path, "火焰")
    assert result.exit_code == 0
    assert any(
        section["pack"] == str(child)
        for section in json.loads(result.render(as_json=True))["sections"]
    )


@pytest.mark.parametrize(
    "value,step,expected",
    [("1.25", "0.25", "3级 金1.75"), ("1e1000000000", "1", "(1E+1000000000+1×(3-1))")],
)
def test_decimal_fractions_and_wide_exponents_never_get_rounded(
    tmp_path: Path, value: str, step: str, expected: str
) -> None:
    _write(
        tmp_path / "对象字段.tsv",
        [
            _FIELD_HEADER,
            *[
                ["科技", "R001", "精确科技", key, key, text, "map", ""]
                for key, text in {"glvl": "3", "gglb": value, "gglm": step}.items()
            ],
        ],
    )
    assert expected in _tech(tmp_path).render()


def test_tech_calculations_restore_the_callers_decimal_context(tmp_path: Path) -> None:
    _pack(tmp_path)
    context = getcontext()
    before = (
        context.prec,
        context.Emax,
        context.Emin,
        context.rounding,
        dict(context.traps),
        dict(context.flags),
    )
    assert _tech(tmp_path).exit_code == 0
    assert before == (
        context.prec,
        context.Emax,
        context.Emin,
        context.rounding,
        dict(context.traps),
        dict(context.flags),
    )


@pytest.mark.parametrize("value", ["1.5", "-1"])
def test_invalid_maximum_level_never_truncates_or_inherits(
    tmp_path: Path, value: str
) -> None:
    _pack(tmp_path)
    path = tmp_path / "对象字段.tsv"
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream, delimiter="\t"))
    for row in rows[1:]:
        if row[3] == "glvl":
            row[5] = value
    _write(path, rows)
    text = _tech(tmp_path).render()
    assert "等级数未确认" in text and "最大等级:" not in text


@pytest.mark.parametrize("query", ["R001 --level 2 --level 3", "R001 --level"])
def test_api_invalid_selectors_never_access_sources(
    tmp_path: Path, query: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args, **kwargs):
        pytest.fail("invalid selector reached a source")

    monkeypatch.setattr(queries, "_named_table", forbidden)
    assert _tech(tmp_path, query).exit_code == 2


def test_large_integer_cost_and_total_have_no_digit_conversion_quota(
    tmp_path: Path,
) -> None:
    value = "9" * 5000
    _write(
        tmp_path / "对象字段.tsv",
        [
            _FIELD_HEADER,
            *[
                ["科技", "R001", "长整数科技", key, key, text, "map", ""]
                for key, text in {"glvl": "2", "gglb": value, "gglm": "0"}.items()
            ],
        ],
    )
    text = _tech(tmp_path).render()
    assert "2级 金" + value in text
    assert "满级累计: 金1" + "9" * 4999 + "8" in text


@pytest.mark.parametrize("query", ['="--level 2"', "=“--level 2”", r"\--level 2"])
def test_level_flag_text_inside_literals_or_escapes_remains_searchable(
    tmp_path: Path, query: str
) -> None:
    _pack(tmp_path)
    path = tmp_path / "对象字段.tsv"
    with path.open("a", encoding="utf-8", newline="") as stream:
        csv.writer(stream, delimiter="\t").writerow(
            ["科技", "R001", "科技", "Literal", "文字", "--level 2", "map", ""]
        )
    result = _tech(tmp_path, query)
    assert result.exit_code == 0 and "所查等级费用:" not in result.render()


def test_invalid_numeric_exponent_does_not_mutate_decimal_flags(tmp_path: Path) -> None:
    value = "1e" + "9" * 10000
    _write(
        tmp_path / "对象字段.tsv",
        [
            _FIELD_HEADER,
            ["科技", "R001", "数值科技", "gglb", "金币", value, "map", "完整原文"],
        ],
    )
    context = getcontext()
    before = dict(context.flags)
    result = _tech(tmp_path)
    assert (
        result.exit_code == 0
        and value in result.render()
        and "未确认" in result.render()
    )
    assert dict(context.flags) == before
