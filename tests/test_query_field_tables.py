"""Object field identity, complete legacy evidence and explicit empty overrides."""

import csv
import json
import os
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_options import PackQueryCliOptions

_HEADER = ["分类", "ID", "名称", "字段键", "字段名", "值", "来源"]
_FIELDS = [
    ["物品", "I001", "测试物品", "igol", "金币", "123", "war3map.w3t"],
    ["物品", "I001", "测试物品", "ides", "说明", "地图完整说明末尾", "war3map.w3t"],
    ["物品", "I001", "测试物品", "iabi", "技能", "A001", "war3map.w3t"],
    ["技能", "A001", "力量", "Istr:1", "力量奖励", "11", "war3map.w3a"],
    ["单位", "n001", "测试商店", "usei", "货架", "I001, I002", "war3map.w3u"],
    ["科技", "R001", "测试科技", "glvl", "等级", "3", "war3map.w3q"],
    ["科技", "R001", "测试科技", "gub1:3000", "提示", "末级完整效果", "war3map.w3q"],
]


def _write(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t", lineterminator="\n").writerows(rows)


@pytest.fixture(autouse=True)
def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _pack(pack: Path, layout: str = "canonical") -> Path:
    for category, codes in [
        ("物品", [("I001", "测试物品"), ("I002", "第二物品")]),
        ("单位", [("n001", "测试商店")]),
        ("科技", [("R001", "测试科技")]),
    ]:
        _write(
            pack / "对象ID" / f"{category}.tsv",
            [["分类", "ID", "数值", "基础ID", "名称", "自定义", "说明"]]
            + [
                [category, code, "1", "zzzz", name, "是", "旧说明"]
                for code, name in codes
            ],
        )
    header, rows = list(_HEADER), [list(row) for row in _FIELDS]
    if layout == "reordered":
        order = [5, 6, 2, 3, 0, 1, 4]
        header, rows = (
            [header[i] for i in order],
            [[row[i] for i in order] for row in rows],
        )
    elif layout == "english":
        header = [
            "CATEGORY",
            "RAWCODE",
            "NAME",
            "FIELD_KEY",
            "FIELD_LABEL",
            "VALUE",
            "SOURCE",
        ]
        categories = {
            "物品": "items",
            "单位": "units",
            "技能": "abilities",
            "科技": "upgrades",
        }
        rows = [[categories[row[0]], *row[1:]] for row in rows]
    elif layout == "minimal":
        order = [0, 1, 3, 5]
        header, rows = (
            [header[i] for i in order],
            [[row[i] for i in order] for row in rows],
        )
    elif layout in {"six", "headerless6"}:
        header, rows = header[:6], [row[:6] for row in rows]
    elif layout == "legacy_named":
        header[3] = "字段"
    records = rows if layout.startswith("headerless") else [header, *rows]
    if layout == "bom":
        records = [[], [" \ufeff "], ["\ufeff 分类 ", *header[1:]], *rows]
    path = pack / "对象字段.tsv"
    _write(path, records)
    return path


@pytest.mark.parametrize(
    "layout",
    [
        "canonical",
        "reordered",
        "english",
        "minimal",
        "six",
        "headerless7",
        "headerless6",
        "legacy_named",
        "bom",
    ],
)
@pytest.mark.parametrize("command", ["price", "item", "shop", "tech"])
def test_field_consumers_share_complete_named_and_legacy_views(
    tmp_path: Path, layout: str, command: str
) -> None:
    path = _pack(tmp_path, layout)
    original = path.read_bytes()
    query = {"price": "I001", "item": "I001", "shop": "n001", "tech": "R001"}[command]
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), command, query)
    )
    text = result.render()
    assert (
        result.exit_code == 0
        and not json.loads(result.render(as_json=True))["warnings"]
    )
    if command == "price":
        assert "123" in text and "地图价" in text
    elif command == "item":
        assert (
            "地图完整说明末尾" in text and "+11 力量" in text and "旧说明" not in text
        )
    elif command == "shop":
        assert "测试商店 [n001]" in text and "123金" in text and "第二物品" in text
    else:
        assert "最大等级: 3" in text and "末级完整效果" in text
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "layout", ["headerless7", "headerless6", "reordered", "english"]
)
def test_diff_retains_the_first_field_and_finds_real_value_changes(
    tmp_path: Path, layout: str
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    _pack(old, layout)
    path = _pack(new, layout)
    path.write_bytes(path.read_bytes().replace(b"123", b"456"))
    result = queries.execute_pack_query(PackQueryCliOptions(str(new), "diff", str(old)))
    assert result.exit_code == 0 and "igol: 123 -> 456" in result.render()


@pytest.mark.parametrize(
    "header",
    [
        ["分类", "ID", "字段键", "值", "值"],
        ["分类", "ID", "字段键"],
        ["分类", "ID", "值"],
        ["ID", "字段键", "值"],
    ],
)
def test_ambiguous_or_missing_field_columns_are_attributable_diagnostics(
    tmp_path: Path, header: list[str]
) -> None:
    _pack(tmp_path)
    _write(tmp_path / "对象字段.tsv", [header, ["物品", "I001", "igol", "123", "456"]])
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "price", "I001")
    )
    warnings = json.loads(result.render(as_json=True))["warnings"]
    assert (
        len(warnings) == 1
        and "对象字段.tsv" in warnings[0]
        and str(tmp_path) in warnings[0]
    )
    assert (
        "请核对表头" in warnings[0] and queries.load_item_gold_overrides(tmp_path) == {}
    )
    assert result.render().count(warnings[0]) == 1


@pytest.mark.parametrize("reverse", [False, True])
def test_an_explicit_empty_stock_overrides_inherited_goods(
    tmp_path: Path, reverse: bool
) -> None:
    _pack(tmp_path)
    rows = [
        ["单位", "n001", "测试商店", "usei", "货架", "", "map"],
        ["单位", "n001", "测试商店", "base:Sellitems", "货架", "I001", "base:ngme"],
    ]
    _write(tmp_path / "对象字段.tsv", [_HEADER, *(reversed(rows) if reverse else rows)])
    assert queries.load_shop_stocks(tmp_path) == [("n001", "测试商店", [])]
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "shop", "n001")
    )
    assert result.exit_code == 0 and "货架字段显式为空" in result.render()
    assert "I001" not in result.render()


def test_nonunit_stock_fields_cannot_invent_a_shop(tmp_path: Path) -> None:
    _pack(tmp_path)
    _write(
        tmp_path / "对象字段.tsv",
        [_HEADER, ["物品", "I001", "假商店", "usei", "货架", "I002", "map"]],
    )
    assert queries.load_shop_stocks(tmp_path) == []


def test_field_view_refreshes_after_same_size_same_mtime_edit(tmp_path: Path) -> None:
    path = _pack(tmp_path, "reordered")
    first = queries.load_item_gold_overrides(tmp_path)
    stat = path.stat()
    original = path.read_bytes()
    path.write_bytes(original.replace(b"123", b"456"))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    second = queries.load_item_gold_overrides(tmp_path)
    assert (
        path.stat().st_size == stat.st_size
        and path.stat().st_mtime_ns == stat.st_mtime_ns
    )
    assert first == {"I001": "123"} and second == {"I001": "456"}


def test_all_bad_field_records_are_disclosed_beyond_explicit_result_limit(
    tmp_path: Path,
) -> None:
    _pack(tmp_path)
    rows = [_HEADER, *_FIELDS, *[["物品", "bad"] for _ in range(5000)]]
    _write(tmp_path / "对象字段.tsv", rows)
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "item", "I001", limit=1)
    )
    warnings = json.loads(result.render(as_json=True))["warnings"]
    assert (
        len(warnings) == 1
        and "记录序号: " + ", ".join(map(str, range(9, 5009))) in warnings[0]
    )
    assert "地图完整说明末尾" in result.render()


def test_field_view_retains_sparse_and_duplicate_extra_columns(tmp_path: Path) -> None:
    _pack(tmp_path)
    header = [
        "分类",
        "ID",
        "字段键",
        "值",
        "",
        "扩展字段5",
        "重名",
        "重名",
        *(f"额外{i}" for i in range(2000)),
    ]
    _write(
        tmp_path / "对象字段.tsv",
        [
            header,
            [
                "物品",
                "I001",
                "ides",
                "完整\n多行\t末尾",
                "空名证据",
                "有名证据",
                "第一列",
                "第二列",
            ],
        ],
    )
    rows = queries._field_rows(tmp_path)
    assert rows[1][5] == "完整\n多行\t末尾"
    assert rows[1][7:] == ("空名证据", "有名证据", "第一列", "第二列")
    assert (
        len(rows[1]) == 11
        and len(rows[0]) == 2011
        and len(set(rows[0])) == len(rows[0])
    )


def test_campaign_field_diagnostics_keep_their_map_and_do_not_leak(
    tmp_path: Path,
) -> None:
    good, bad = tmp_path / "子地图" / "001", tmp_path / "子地图" / "002"
    _pack(good)
    _pack(bad)
    _write(
        bad / "对象字段.tsv",
        [["分类", "ID", "字段键", "值", "值"], ["物品", "I001", "igol", "1", "2"]],
    )
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "item", "I001")
    )
    data = json.loads(result.render(as_json=True))
    assert len(data["warnings"]) == 1 and len(data["sections"]) == 2
    assert "重复语义列" not in "\n".join(data["sections"][0]["lines"])
    assert str(bad) == data["sections"][1]["pack"] and "重复语义列" in "\n".join(
        data["sections"][1]["lines"]
    )
    _pack(bad)
    again = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "item", "I001")
    )
    assert not json.loads(again.render(as_json=True))["warnings"]


def test_a_missing_field_table_is_a_real_diff_not_an_identical_pack(
    tmp_path: Path,
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    _pack(old)
    _pack(new)
    (old / "对象字段.tsv").unlink()
    result = queries.execute_pack_query(PackQueryCliOptions(str(new), "diff", str(old)))
    assert result.exit_code == 0 and "igol: (无) -> 123" in result.render()


@pytest.mark.parametrize("code", ["I-01", "I_01", "é001"])
@pytest.mark.parametrize("named", [False, True])
def test_stock_codes_keep_all_four_bytes_and_use_the_actual_suffix(
    tmp_path: Path, code: str, named: bool
) -> None:
    _pack(tmp_path)
    value = f"说明(ABCD) 测试物品({code})" if named else code
    _write(
        tmp_path / "对象字段.tsv",
        [_HEADER, ["单位", "n001", "测试商店", "usei", "货架", value, "map"]],
    )
    assert queries.load_shop_stocks(tmp_path) == [("n001", "测试商店", [code])]


def test_named_ability_codes_do_not_lose_equipped_effects(tmp_path: Path) -> None:
    _pack(tmp_path)
    _write(
        tmp_path / "对象字段.tsv",
        [
            _HEADER,
            [
                "物品",
                "I001",
                "测试物品",
                "iabi",
                "技能",
                "文字(ABCD) 力量(A_01)",
                "map",
            ],
            ["技能", "A_01", "力量", "Istr1", "力量奖励", "17", "map"],
        ],
    )
    assert queries.load_item_equipped_effects(tmp_path) == {"I001": ["+17 力量"]}
