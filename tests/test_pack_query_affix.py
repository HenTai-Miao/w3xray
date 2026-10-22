"""affixes/registered 词缀与注册数据查询 — 临时包三路覆盖 (首次补测)。"""

from __future__ import annotations

from pathlib import Path

from gametool.pack_query_cli import _query_affix, _query_registered


def _make_pack(tmp_path: Path) -> Path:
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "词缀表.tsv").write_text(
        "词缀名\t倍率\t属性\n"
        "锋利\t12\t的攻击力\n"
        "坚固\t8\t的护甲\n",
        encoding="utf-8",
    )
    return pack


def test_affix_list_all(tmp_path: Path) -> None:
    lines = _query_affix(_make_pack(tmp_path), "", 0)
    assert any("锋利" in l for l in lines)
    assert any("坚固" in l for l in lines)
    assert any("公式" in l for l in lines)


def test_affix_filter_and_miss(tmp_path: Path) -> None:
    pack = _make_pack(tmp_path)
    hit = _query_affix(pack, "锋利", 0)
    assert any("锋利" in l for l in hit)
    assert not any("坚固" in l for l in hit)
    miss = _query_affix(pack, "不存在", 0)
    assert miss and "共 2 条" in miss[0]


def test_affix_missing_table_has_exit(tmp_path: Path) -> None:
    pack = tmp_path / "empty"
    pack.mkdir()
    lines = _query_affix(pack, "", 0)
    assert lines and "词缀表.tsv" in lines[0]
    assert any("--dump-objects" in l for l in lines)


def test_registered_missing_table_has_exit(tmp_path: Path) -> None:
    pack = tmp_path / "empty"
    pack.mkdir()
    lines = _query_registered(pack, "", 0)
    assert lines and "注册数据.tsv" in lines[0]
