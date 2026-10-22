"""affixes/registered 词缀与注册数据查询 — 临时包覆盖。"""

from __future__ import annotations

from pathlib import Path

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
