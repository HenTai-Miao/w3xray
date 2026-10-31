"""affixes/registered 词缀与注册数据查询 — 临时包覆盖。"""

from __future__ import annotations

from pathlib import Path
import json

import pytest

from gametool.pack_query_cli import _query_affix, _query_registered


def _rows(path: Path, name: str, rows: list[list[str]]) -> None:
    """写一个 TSV 表 (TAB 分隔)。"""
    body = "\n".join("\t".join(r) for r in rows)
    (path / name).write_text(body + "\n", encoding="utf-8")


def _make_pack(tmp_path: Path) -> Path:
    pack = tmp_path / "pack"
    pack.mkdir()
    _rows(
        pack,
        "词缀表.tsv",
        [
            ["词缀名", "倍率", "属性"],
            ["锋利", "12", "的攻击力"],
            ["坚固", "8", "的护甲"],
        ],
    )
    return pack


def _make_registered_pack(tmp_path: Path) -> Path:
    pack = tmp_path / "reg"
    pack.mkdir()
    _rows(
        pack,
        "注册数据.tsv",
        [
            ["消息名", "记录数", "记录JSON"],
            ["save", "2", '{"a":1}'],
            ["save", "2", '{"b":2}'],
            ["load", "1", '{"c":3}'],
        ],
    )
    return pack


def test_affix_list_all(tmp_path: Path) -> None:
    lines = _query_affix(_make_pack(tmp_path), "", 0)
    assert any("锋利" in line for line in lines)
    assert any("坚固" in line for line in lines)
    assert any("公式" in line for line in lines)


def test_affix_filter_and_miss(tmp_path: Path) -> None:
    pack = _make_pack(tmp_path)
    hit = _query_affix(pack, "锋利", 0)
    assert any("锋利" in line for line in hit)
    assert not any("坚固" in line for line in hit)
    miss = _query_affix(pack, "不存在", 0)
    assert miss and "共 2 条" in miss[0]


def test_affix_missing_table_has_exit(tmp_path: Path) -> None:
    pack = tmp_path / "empty"
    pack.mkdir()
    lines = _query_affix(pack, "", 0)
    assert lines and "词缀表.tsv" in lines[0]
    assert any("--dump-objects" in line for line in lines)


def test_registered_missing_table_has_exit(tmp_path: Path) -> None:
    pack = tmp_path / "empty"
    pack.mkdir()
    lines = _query_registered(pack, "", 0)
    assert lines and "注册数据.tsv" in lines[0]


def test_registered_list_all(tmp_path: Path) -> None:
    lines = _query_registered(_make_registered_pack(tmp_path), "", 0)
    assert any("2 种" in line for line in lines)
    assert any("save" in line and "2 条" in line for line in lines)
    assert any("load" in line and "1 条" in line for line in lines)


def test_registered_filter_hits_payload(tmp_path: Path) -> None:
    lines = _query_registered(_make_registered_pack(tmp_path), "load", 0)
    assert any("== load ==" in line for line in lines)
    assert any('"c":3' in line for line in lines)
    assert not any("== save ==" in line for line in lines)


def test_registered_miss_lists_names(tmp_path: Path) -> None:
    lines = _query_registered(_make_registered_pack(tmp_path), "xxx", 0)
    assert lines and "共 2 种消息名" in lines[0]
    assert "save" in lines[0] and "load" in lines[0]  # miss 也列全部消息名


@pytest.mark.parametrize(
    "value",
    [
        "=formula",
        "-23",
        "+10",
        "@name",
        "'\u2060=literal",
        'TAB\tCR\r\nLF\n\ufeff"quote',
    ],
)
def test_real_runtime_exports_decode_exactly_one_safety_envelope(
    tmp_path: Path, value: str
) -> None:
    from gametool import pack_query_cli as queries
    from gametool.live_object_dump import _write_affixes_tsv, _write_registered_data_tsv

    assert (
        _write_affixes_tsv({value: {"multiplier": value, "stat": value}}, str(tmp_path))
        == 1
    )
    assert queries._load_affixes(tmp_path) == [(value, value, value)]
    affix_text = "\n".join(_query_affix(tmp_path, "", 0))
    assert f"[{value}] {value}" in affix_text
    assert f"词条等级 × {value}" in affix_text
    assert "原始TSV单元格" in affix_text
    assert (
        _write_registered_data_tsv(
            {value: {"records": [{"value": value}]}}, str(tmp_path)
        )
        == 1
    )
    rows = queries._registered_data_rows(tmp_path)
    assert len(rows) == 1 and rows[0][0] == value
    assert json.loads(rows[0][2]) == {"value": value}
    assert tuple(queries._read_rows(tmp_path, "注册数据.tsv")[1]) == rows[0].raw
    assert f"== {value} ==" in "\n".join(_query_registered(tmp_path, value, 0))


def test_runtime_export_provenance_and_independent_variants_remain_queryable(
    tmp_path: Path,
) -> None:
    from gametool.live_object_dump import (
        AffixDefinitions,
        RegisteredRecords,
        RuntimeTextEvidence,
        _write_affixes_tsv,
        _write_registered_data_tsv,
    )

    affixes = AffixDefinitions()
    affixes.evidence = tuple(
        RuntimeTextEvidence(
            address, b"raw", "=affix", ("-1", "@stat"), ("'\u2060=literal",)
        )
        for address in (1, 2)
    )
    assert _write_affixes_tsv(affixes, str(tmp_path)) == 1
    text = "\n".join(_query_affix(tmp_path, "", 1))
    assert "地址: 0x1" in text and "原始文本HEX: 726177" in text
    assert "诊断: '\u2060=literal" in text and "其余 1 条未显示" in text
    assert "地址: 0x2" not in text
    registered = RegisteredRecords()
    registered.evidence = (
        RuntimeTextEvidence(
            3, b"encoded", "=message", ('{"a":1,"a":2}',), ("@diagnostic",)
        ),
    )
    assert _write_registered_data_tsv(registered, str(tmp_path)) == 2
    text = "\n".join(_query_registered(tmp_path, "@diagnostic", 1))
    assert '"a":1,"a":2' in text and "地址: 0x3" in text
    assert "诊断: @diagnostic" in text and "原始TSV单元格" in text
