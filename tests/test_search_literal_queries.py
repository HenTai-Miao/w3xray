"""Literal GUI FourCC handoffs through the actual Boolean query consumers."""

from __future__ import annotations

from pathlib import Path

import pytest

from gametool.batch_tsv import format_tsv_rows
from gametool.gui_live_evidence import object_query
from gametool.item_relation_exports import ACQUISITION_REPORT_HEADER
from gametool.object_codes import decode_object_id_query, encode_object_id_query
from gametool.pack_query_cli import execute_pack_query
from gametool.pack_query_options import PackQueryCliOptions
from gametool.search import compile_query, encode_literal_query


@pytest.mark.parametrize("position", range(4))
def test_encoded_literal_keeps_every_latin1_byte_in_each_position(
    position: int,
) -> None:
    for value in range(256):
        cells = list("QaZx")
        cells[position] = chr(value)
        code = "".join(cells)
        assert decode_object_id_query(encode_object_id_query(code)) == code
        compiled = compile_query(encode_literal_query(code))
        assert not compiled.is_empty
        assert compiled.score(code) is not None
        assert compiled.score("字面量不应命中其他对象") is None
        other_case = code.swapcase()
        if other_case != code:
            assert compiled.score(other_case) is None


def test_doubled_quotes_backslashes_and_boolean_composition_are_literal() -> None:
    value = 'a"\\%() && || b'
    literal = encode_literal_query(value)
    assert literal == '="a""\\%() && || b"'
    compiled = compile_query(literal + ' && ="限定"')
    assert compiled.score_fields((value, "限定")) is not None
    assert compiled.score_fields(('a"%() && || b', "限定")) is None
    assert compiled.score_fields((value, "缺失")) is None
    quotes = '"' * 20_001
    assert compile_query(encode_literal_query(quotes)).score(quotes) is not None


def _pack(tmp_path: Path, category: str, code: str) -> Path:
    pack = tmp_path / "pack"
    tables = pack / "对象ID"
    tables.mkdir(parents=True)
    header = ("分类", "ID", "数值", "基础ID", "名称", "自定义", "说明")
    records = [
        header,
        (category, code, "1", "", "目标记录", "是", "完整目标字段"),
        (category, "cccc", "2", "", "无关香蕉", "是", "banana"),
        (category, "dddd", "3", "", "无关字母", "是", "alpha"),
        (category, "nnnn", "5", "", code, "是", "名称碰撞对象"),
        (category, "eeee", "6", "", "字段碰撞对象", "是", code),
    ]
    alternative = _case_variant(code)
    if alternative != code:
        records.append((category, alternative, "4", "", "大小写另一对象", "是", ""))
    (tables / f"{category}.tsv").write_text(
        format_tsv_rows(records), encoding="utf-8", newline=""
    )
    (pack / "对象字段.tsv").write_text(
        "分类\tID\t名称\t字段键\t字段名\t值\t来源\n", encoding="utf-8"
    )
    return pack


def _case_variant(code: str) -> str:
    return code.translate(
        str.maketrans(
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
        )
    )


@pytest.mark.parametrize("item", (False, True))
@pytest.mark.parametrize(
    "code",
    (
        "a||b",
        "a&&b",
        "a%b%",
        "a(b)",
        'a"b?',
        '""""',
        "a\\b?",
        'a\\"?',
        " a| ",
        "  a ",
        "    ",
        "QazX",
        "a|nb",
        "|rAB",
        "ÿAéZ",
        "\x00A\tB",
        "\rA\nB",
    ),
)
def test_selected_fourcc_handoff_selects_target_through_public_query(
    tmp_path: Path, item: bool, code: str
) -> None:
    pack = _pack(tmp_path, "物品" if item else "单位", code)
    handoff = object_query(
        {"code": code, "name": "不应用名称猜测"}, "detail", item=item
    )
    assert handoff is not None
    command, _, keyword = handoff.partition(" ")
    result = execute_pack_query(PackQueryCliOptions(str(pack), command, keyword))
    output = result.render()
    assert "目标记录" in output
    assert "无关香蕉" not in output
    assert "无关字母" not in output
    assert "大小写另一对象" not in output
    assert "[nnnn]" not in output and "[eeee]" not in output


@pytest.mark.parametrize("item", (False, True))
@pytest.mark.parametrize("action", ("where", "drop"))
@pytest.mark.parametrize(
    "code",
    (
        'a"||',
        "a||b",
        "QazX",
        " a| ",
        "    ",
        "a|nb",
        "|rAB",
        "a\\b?",
        "a%b%",
        "a(b)",
        "ÿAéZ",
        "\x00A\tB",
        "\rA\nB",
    ),
)
def test_acquisition_handoffs_use_exact_id_without_name_or_case_aliases(
    tmp_path: Path, item: bool, action: str, code: str
) -> None:
    pack = _pack(tmp_path, "物品" if item else "单位", code)
    relation_rows: list[tuple[str, ...]] = [ACQUISITION_REPORT_HEADER]
    identities = [(code, "目标记录"), ("nnnn", code), ("cccc", "无关香蕉")]
    if _case_variant(code) != code:
        identities.append((_case_variant(code), "大小写另一对象"))
    for identity, name in identities:
        row = [""] * len(ACQUISITION_REPORT_HEADER)
        for index, value in {
            0: "relation:" + identity,
            2: "怪物直接掉落",
            3: identity if item else "I999",
            4: name if item else "共同掉落物",
            5: "单位",
            6: "u999" if item else identity,
            7: "共同来源" if item else name,
            19: "war3mapUnits.doo",
            23: "已确认",
            24: "完整",
        }.items():
            row[index] = value
        relation_rows.append(tuple(row))
    (pack / "掉落与获取关系.tsv").write_text(
        format_tsv_rows(relation_rows), encoding="utf-8", newline=""
    )
    handoff = object_query({"code": code}, action, item=item)
    assert handoff is not None
    command, _, keyword = handoff.partition(" ")
    assert command == ("where" if item and action == "where" else "drop")
    result = execute_pack_query(PackQueryCliOptions(str(pack), command, keyword))
    output = result.render()
    assert "目标记录" in output
    assert "大小写另一对象" not in output
    assert "无关香蕉" not in output
    assert "[nnnn]" not in output


@pytest.mark.parametrize("item", (False, True))
def test_plain_exact_name_queries_keep_existing_semantics(
    tmp_path: Path, item: bool
) -> None:
    pack = _pack(tmp_path, "物品" if item else "单位", "I001")
    command = "item" if item else "units"
    ordinary = execute_pack_query(
        PackQueryCliOptions(str(pack), command, encode_literal_query("I001"))
    ).render()
    selected = execute_pack_query(
        PackQueryCliOptions(str(pack), command, encode_object_id_query("I001"))
    ).render()
    assert "[nnnn]" in ordinary and "[eeee]" in ordinary
    assert "[nnnn]" not in selected and "[eeee]" not in selected
    assert "目标记录" in selected
