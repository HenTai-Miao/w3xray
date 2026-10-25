"""Object lists accept older packs without losing rows or hero descriptions."""

from __future__ import annotations

from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_options import PackQueryCliOptions


@pytest.mark.parametrize(
    ("command", "table"),
    [("heroes", "英雄"), ("units", "单位"), ("skills", "技能"), ("buffs", "增益")],
)
def test_explicit_list_limit_discloses_exact_remainder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, table: str
) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    folder = tmp_path / "对象ID"
    folder.mkdir()
    (folder / f"{table}.tsv").write_text(
        "分类\tID\t数值\t基础ID\t名称\n"
        + "".join(f"{table}\tX{i:03}\t1\tX{i:03}\t对象{i}\n" for i in range(31)),
        encoding="utf-8",
    )
    full = queries.execute_pack_query(PackQueryCliOptions(str(tmp_path), command, ""))
    limited = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), command, "", limit=1)
    )
    assert full.render().count("[X") == 31
    assert limited.render().count("[X") == 1
    assert "其余 30 条未显示" in limited.render()


@pytest.mark.parametrize(
    ("command", "table", "code"),
    [
        ("heroes", "英雄", "H001"),
        ("units", "单位", "n001"),
        ("skills", "技能", "A001"),
        ("buffs", "增益", "B001"),
    ],
)
@pytest.mark.parametrize("legacy", [True, False])
def test_list_keeps_records_without_optional_columns_and_full_description(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    table: str,
    code: str,
    legacy: bool,
) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    folder = tmp_path / "对象ID"
    folder.mkdir()
    description = "火焰攻击|n" + "完整说明" * 1000 + "效果尾部"
    header = "分类\tID\t数值\t基础ID\t名称"
    row = f"{table}\t{code}\t1\t{code}\t对象名称"
    if not legacy:
        header += "\t自定义\t说明"
        row += "\t是\t" + description
    (folder / f"{table}.tsv").write_text(header + "\n" + row + "\n", encoding="utf-8")
    query = "对象名称" if legacy else "效果尾部"
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), command, query)
    )
    assert result.exit_code == 0
    assert f"[{code}]" in result.render()
    if legacy:
        assert "来源未记录" in result.render()
    else:
        assert description.replace("|n", " ") in result.render()
