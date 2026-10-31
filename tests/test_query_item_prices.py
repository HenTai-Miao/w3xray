"""Price queries and object/shop summaries share complete, qualified evidence."""

from __future__ import annotations

import csv
from decimal import getcontext, localcontext
import json
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_options import PackQueryCliOptions

_IDS = ["分类", "ID", "数值", "基础ID", "名称", "自定义", "说明"]
_FIELDS = ["分类", "ID", "名称", "字段键", "字段名", "值", "来源", "扩展"]


@pytest.fixture(autouse=True)
def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _write(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream, delimiter="\t", lineterminator="\n").writerows(rows)


def _pack(
    pack: Path, *, ids: bool = True, count: int = 1, values: tuple[str, ...] = ("123",)
) -> None:
    if ids:
        _write(
            pack / "对象ID" / "物品.tsv",
            [
                _IDS,
                *[
                    [
                        "物品",
                        f"I{i:03x}",
                        str(i),
                        "ratf",
                        f"主表物品{i}",
                        "是",
                        "清单说明",
                    ]
                    for i in range(1, count + 1)
                ],
            ],
        )
    rows = [_FIELDS]
    for i in range(1, count + 1):
        code = f"I{i:03x}"
        rows.extend(
            [
                "物品",
                code,
                f"金币别名{i}",
                "igol",
                "金币字段",
                value,
                f"map{n}.w3t",
                f"附加金币证据{n}",
            ]
            for n, value in enumerate(values)
        )
        rows.append(
            [
                "物品",
                code,
                f"字段别名{i}",
                "OtherField",
                "说明字段",
                "火焰完整\r\n寒冰末尾",
                "extra.w3t",
                "附加完整原文",
            ]
        )
    rows.append(
        [
            "单位",
            "n001",
            "测试商店",
            "usei",
            "货架",
            ",".join(f"I{i:03x}" for i in range(1, count + 1)),
            "map.w3u",
            "货架证据",
        ]
    )
    _write(pack / "对象字段.tsv", rows)


def _query(pack: Path, command: str = "price", keyword: str = "I001", limit: int = 0):
    return queries.execute_pack_query(
        PackQueryCliOptions(str(pack), command, keyword, limit)
    )


@pytest.mark.parametrize("ids", [False, True])
@pytest.mark.parametrize(
    "keyword", ["I001", "金币别名1", "火焰 && 寒冰", "附加完整原文"]
)
def test_price_searches_full_records_and_keeps_all_selected_evidence(
    tmp_path: Path, ids: bool, keyword: str
) -> None:
    _pack(tmp_path, ids=ids)
    result = _query(tmp_path, keyword=keyword)
    text = result.render()
    assert result.exit_code == 0 and "[I001]" in text
    assert "金币: 123" in text and "地图价" in text
    assert "OtherField" in text and "火焰完整\r\n寒冰末尾" in text
    assert "map0.w3t" in text and "附加金币证据0" in text
    assert "附加完整原文" in text and "静态金币" in text


@pytest.mark.parametrize("command", ["price", "item", "shop"])
def test_conflicting_gold_fields_never_choose_the_last_value_or_base(
    tmp_path: Path, command: str
) -> None:
    _pack(tmp_path, values=("123", "456"))
    result = _query(tmp_path, command, "n001" if command == "shop" else "I001")
    text = result.render()
    assert result.exit_code == 0
    assert "金币字段冲突" in text and "未确认" in text
    assert "金币: 456" not in text and "456金" not in text and "800金" not in text
    assert "map0.w3t" in text and "map1.w3t" in text
    assert "附加金币证据0" in text and "附加金币证据1" in text


@pytest.mark.parametrize(
    "value", ["", "NaN", "Infinity", "not-a-number", "'123", "''123", "' 123"]
)
@pytest.mark.parametrize("command", ["price", "item", "shop"])
def test_invalid_custom_gold_suppresses_inheritance_and_retains_raw_value(
    tmp_path: Path, value: str, command: str
) -> None:
    _pack(tmp_path, values=(value,))
    result = _query(tmp_path, command, "n001" if command == "shop" else "I001")
    text = result.render()
    assert result.exit_code == 0 and "金币字段未确认" in text
    assert "金币: 800" not in text and "800金" not in text
    assert "map0.w3t" in text and "附加金币证据0" in text
    assert value in text if value else "显式空值" in text


def test_inherited_field_value_outranks_catalog_and_is_labeled_as_inherited(
    tmp_path: Path,
) -> None:
    _pack(tmp_path)
    path = tmp_path / "对象字段.tsv"
    path.write_bytes(path.read_bytes().replace(b"\tigol\t", b"\tbase:GoldCost\t"))
    text = _query(tmp_path).render()
    assert "金币: 123" in text and "继承字段" in text and "地图价" not in text
    assert "base:GoldCost" in text and "map0.w3t" in text


def test_custom_gold_overrides_inherited_evidence_without_erasing_it(
    tmp_path: Path,
) -> None:
    _pack(tmp_path)
    with (tmp_path / "对象字段.tsv").open("a", encoding="utf-8", newline="") as stream:
        csv.writer(stream, delimiter="\t").writerow(
            [
                "物品",
                "I001",
                "继承名称",
                "base:igol",
                "基础金币",
                "900",
                "base:ratf",
                "被覆盖证据",
            ]
        )
    text = _query(tmp_path).render()
    assert "金币: 123" in text and "金币字段冲突" not in text
    assert "已被自定义金币字段覆盖" in text
    assert "900" in text and "被覆盖证据" in text and "base:ratf" in text


def test_equivalent_numeric_spellings_are_not_conflicting_and_keep_each_source(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, values=("00123", "+123.00", "1.23e2"))
    text = _query(tmp_path).render()
    assert "未确认" not in text and "金币字段冲突" not in text
    assert "00123" in text and "+123.00" in text and "1.23e2" in text
    assert all(f"附加金币证据{i}" in text for i in range(3))


@pytest.mark.parametrize("command", ["price", "item", "shop"])
def test_five_thousand_digit_gold_is_complete_and_not_coerced_through_int_or_float(
    tmp_path: Path, command: str
) -> None:
    value = "9" * 5000
    _pack(tmp_path, values=(value,))
    text = _query(tmp_path, command, "n001" if command == "shop" else "I001").render()
    assert value in text and "未确认" not in text and "Overflow" not in text


@pytest.mark.parametrize("tail", [[], [""], ["   "]])
def test_cli_price_empty_listing_and_again_preserve_the_empty_query(
    tmp_path: Path, tail: list[str]
) -> None:
    _pack(tmp_path, count=2)
    options = queries.parse_pack_query_cli_options([str(tmp_path), "price", *tail])
    assert options.query == "" and options.limit == 0
    result = queries.execute_pack_query(options)
    assert (
        result.exit_code == 0
        and "[I001]" in result.render()
        and "[I002]" in result.render()
    )
    assert queries._load_last_query() == {
        "pack": str(tmp_path),
        "command": "price",
        "query": "",
    }
    replay = _query(tmp_path, "again", "")
    assert replay.exit_code == 0 and "[I002]" in replay.render()


def test_price_limit_selects_whole_records_with_every_price_and_other_field(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, count=3, values=("123", "456"))
    text = _query(tmp_path, keyword="附加完整原文", limit=1).render()
    assert "其余 2 条" in text and "[I001]" in text and "[I002]" not in text
    assert "附加金币证据0" in text and "附加金币证据1" in text
    assert "附加完整原文" in text and "OtherField" in text


@pytest.mark.parametrize("ids", [False, True])
def test_missing_base_declaration_never_falls_back_to_lowercased_object_identity(
    tmp_path: Path, ids: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    if ids:
        _write(
            tmp_path / "对象ID" / "物品.tsv",
            [_IDS, ["物品", "RATF", "", "", "自定义物品", "是", ""]],
        )
    _write(
        tmp_path / "对象字段.tsv",
        [
            _FIELDS,
            ["物品", "RATF", "自定义别名", "OtherField", "", "字段原文", "map", ""],
        ],
    )
    monkeypatch.setattr(queries, "_base_prices", lambda: {"ratf": "7777"})
    result = _query(tmp_path, keyword="RATF")
    text = result.render()
    assert result.exit_code == 0 and "[RATF]" in text and "7777" not in text
    assert "基础物品 [ratf]" not in text


def test_base_catalog_reference_is_separate_from_evidence_of_map_sales(
    tmp_path: Path,
) -> None:
    _pack(tmp_path)
    text = _query(tmp_path, keyword="RATC").render()
    assert "金币: 500" in text and "基础资料参考" in text and "商店出售" in text


def test_price_campaign_keeps_field_only_and_diagnostic_only_scopes_and_again(
    tmp_path: Path,
) -> None:
    child, bad = tmp_path / "子地图" / "001", tmp_path / "子地图" / "002"
    _pack(child, ids=False)
    _write(
        bad / "对象字段.tsv",
        [["分类", "ID", "字段键", "值", "值"], ["物品", "I002", "igol", "1", "2"]],
    )
    result = _query(tmp_path, keyword="附加完整原文")
    payload = json.loads(result.render(as_json=True))
    assert result.exit_code == 0 and any(
        section["pack"] == str(child) for section in payload["sections"]
    )
    assert any(
        str(bad) in note and "对象字段.tsv" in note for note in payload["warnings"]
    )
    replay = _query(tmp_path, "again", "")
    assert replay.exit_code == 0 and "附加完整原文" in replay.render()


def test_complete_price_listing_has_no_record_ceiling_and_preserves_inputs(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, ids=False, count=1500)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.tsv")}
    result = _query(tmp_path, keyword="")
    assert result.exit_code == 0
    assert sum(line.startswith("[I") for line in result.sections[0].lines) == 1500
    assert before == {path: path.read_bytes() for path in before}


def test_invalid_numeric_exponent_does_not_change_caller_decimal_context(
    tmp_path: Path,
) -> None:
    value = "1e" + "9" * 10000
    _pack(tmp_path, values=(value,))
    with localcontext() as context:
        context.clear_flags()
        before = (context.prec, dict(context.flags), dict(context.traps))
        text = _query(tmp_path).render()
        assert "金币字段未确认" in text and value in text
        assert (
            getcontext().prec,
            dict(getcontext().flags),
            dict(getcontext().traps),
        ) == before


def test_object_category_and_case_qualified_price_fields_do_not_merge(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "对象字段.tsv",
        [
            _FIELDS,
            ["物品", "I001", "大写物品", "igol", "", "123", "item-map", "物品证据"],
            ["物品", "i001", "小写物品", "igol", "", "456", "item-map", "小写证据"],
            ["单位", "I001", "同码单位", "igol", "", "999", "unit-map", "单位证据"],
        ],
    )
    text = _query(tmp_path, keyword="").render()
    assert "[I001]" in text and "[i001]" in text
    assert "金币: 123" in text and "金币: 456" in text
    assert "999" not in text and "单位证据" not in text


def test_conflicting_inherited_fields_never_select_catalog_or_last_record(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, values=("123", "456"))
    path = tmp_path / "对象字段.tsv"
    path.write_bytes(path.read_bytes().replace(b"\tigol\t", b"\tbase:igol\t"))
    text = _query(tmp_path).render()
    assert (
        "金币字段冲突" in text and "金币: 800" not in text and "金币: 456" not in text
    )


def test_conflicting_explicit_base_ids_are_diagnostic_instead_of_last_wins(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "对象ID" / "物品.tsv",
        [
            _IDS,
            ["物品", "I001", "", "ratf", "甲物品", "是", "第一基础"],
            ["物品", "I001", "", "ratc", "乙物品", "是", "第二基础"],
        ],
    )
    text = _query(tmp_path).render()
    assert "基础 ID 声明冲突" in text and "未确认" in text
    assert "金币: 500" not in text and "金币: 800" not in text
    assert (
        "ratf" in text and "ratc" in text and "第一基础" in text and "第二基础" in text
    )


def test_base_reference_remains_available_beside_map_field_search_matches(
    tmp_path: Path,
) -> None:
    _pack(tmp_path)
    text = _query(tmp_path, keyword="RATF").render()
    assert "[I001]" in text and "金币: 123" in text
    assert "基础物品 [ratf]" in text and "金币: 800" in text and "基础资料参考" in text


def test_incomplete_field_source_does_not_invent_a_catalog_fallback(
    tmp_path: Path,
) -> None:
    _pack(tmp_path)
    _write(
        tmp_path / "对象字段.tsv",
        [["分类", "ID", "字段键", "值", "值"], ["物品", "I001", "igol", "1", "2"]],
    )
    text = _query(tmp_path).render()
    assert "金币: 800" not in text and "金币字段来源不完整" in text
    assert "[⚠" in text and "重复语义列" in text and "第 4, 5 列" in text


def test_price_expression_evaluates_once_per_record_and_renders_selected_records_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool import pack_query_item_prices as prices
    from gametool.search import CompiledQuery

    _pack(tmp_path, count=50)
    scored, rendered = [], []
    original_score, original_render = (
        CompiledQuery.score_fields,
        prices.render_object_record,
    )

    def score(self, fields):
        scored.append(1)
        return original_score(self, fields)

    def render(record, *args, **kwargs):
        rendered.append(record.row[1])
        return original_render(record, *args, **kwargs)

    monkeypatch.setattr(CompiledQuery, "score_fields", score)
    monkeypatch.setattr(prices, "render_object_record", render)
    text = _query(tmp_path, keyword="火焰 && 附加完整原文", limit=1).render()
    assert len(scored) == 50 and rendered == ["I001"] and "其余 49 条" in text


def test_shop_limits_render_all_gold_evidence_only_for_selected_shops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool.pack_query_field_evidence import ObjectField

    _pack(tmp_path, count=2)
    path = tmp_path / "对象字段.tsv"
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream, delimiter="\t"))
    rows[-1][5] = "I001"
    rows.append(["单位", "n002", "第二商店", "usei", "货架", "I002", "map.w3u", ""])
    _write(path, rows)
    rendered = []
    original = ObjectField.render_lines

    def render(self, *args, **kwargs):
        if self.key == "igol":
            rendered.append(self.value)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ObjectField, "render_lines", render)
    text = _query(tmp_path, "shop", "", limit=1).render()
    assert "其余 1 条" in text and "[n002]" not in text
    assert rendered == ["123"] and "附加金币证据0" in text


def test_igol_and_goldcost_are_one_scalar_role_with_conflicts_preserved(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, values=("123", "456"))
    path = tmp_path / "对象字段.tsv"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace("\tigol\t", "\tGoldCost\t", 1), encoding="utf-8", newline=""
    )
    text = _query(tmp_path).render()
    assert "金币字段冲突" in text and "GoldCost" in text and "igol" in text


def test_compatibility_override_map_never_selects_an_ambiguous_value(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, values=("123", "456"))
    assert queries.load_item_gold_overrides(tmp_path) == {"I001": ""}


@pytest.mark.parametrize("values", [("",), ("123", "456"), ("0",)])
def test_death_pool_annotations_never_turn_unknown_or_zero_gold_into_non_sale(
    tmp_path: Path, values: tuple[str, ...]
) -> None:
    _pack(tmp_path, values=values)
    script = """function Trig_goldConditions takes nothing returns boolean
return GetUnitTypeId(GetDyingUnit()) == 'n001'
endfunction
function Trig_goldActions takes nothing returns nothing
call PlaceRandomItem((udg_GoldPool[1]),0,0)
endfunction
function InitTrig_gold takes nothing returns nothing
set gg_trg_gold=CreateTrigger()
call TriggerAddCondition(gg_trg_gold,Condition(function Trig_goldConditions))
call TriggerAddAction(gg_trg_gold,function Trig_goldActions)
endfunction
call ItemPoolAddItemType(udg_GoldPool[1],'I001',1.0)
"""
    text = "\n".join(queries._script_pool_drops(tmp_path, "n001", script=script))
    assert "[I001]" in text and "  非卖品" not in text
    assert "静态金币0金" in text if values == ("0",) else "金币字段未确认" in text
    assert "附加金币证据0" in text
