"""Explicit limits count real records while keeping each record complete."""

from __future__ import annotations

from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_options import PackQueryCliOptions


@pytest.fixture
def pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    objects = tmp_path / "对象ID"
    objects.mkdir()
    header = "分类\tID\t数值\t基础ID\t名称\t自定义\t说明\n"
    for category, prefix in [("物品", "I"), ("科技", "R")]:
        (objects / f"{category}.tsv").write_text(
            header
            + "".join(
                f"{category}\t{prefix}{i:03}\t1\tzzzz\t对象{i}\t是\t完整说明{i}\n"
                for i in range(1, 4)
            ),
            encoding="utf-8",
        )
    fields = ["分类\tID\t名称\t字段\t字段名\t值\t来源"]
    for index in range(1, 4):
        fields.extend(
            f"科技\tR{index:03}\t对象{index}\tgub1:{level}\t提示\t完整效果{level}\twar3map.w3q"
            for level in range(1, 14)
        )
        fields.append(
            f"单位\tn{index:03}\t商店{index}\tusei\t出售物品\tI001\twar3map.w3u"
        )
    (tmp_path / "对象字段.tsv").write_text("\n".join(fields), encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("command", ["item", "tech", "shop"])
def test_record_limit_does_not_guess_from_number_of_output_lines(
    pack: Path, command: str
) -> None:
    query = "商店" if command == "shop" else "对象"
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), command, query, limit=1)
    )
    output = result.render()
    assert result.exit_code == 0
    prefix = "n" if command == "shop" else "I" if command == "item" else "R"
    assert f"[{prefix}001]" in output
    assert f"[{prefix}002]" not in output and f"[{prefix}003]" not in output
    assert "其余 2 条未显示" in output
    if command == "tech":
        assert "完整效果13" in output


@pytest.mark.parametrize("command", ["item", "tech", "price", "shop"])
def test_exact_limit_does_not_claim_complete_results_were_truncated(
    pack: Path, command: str
) -> None:
    code = "n001" if command == "shop" else "R001" if command == "tech" else "I001"
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), command, code, limit=1)
    )
    assert result.exit_code == 0
    assert "已达 --limit" not in result.render()


@pytest.mark.parametrize("command", ["item", "tech", "shop"])
def test_default_keeps_all_records_and_complete_descriptions(
    pack: Path, command: str
) -> None:
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), command, "商店" if command == "shop" else "对象")
    )
    assert result.exit_code == 0
    for index in range(1, 4):
        prefix = "n" if command == "shop" else "I" if command == "item" else "R"
        assert f"[{prefix}{index:03}]" in result.render()


def _relation(
    kind: str, item: str, name: str, source: str = "", source_name: str = ""
) -> list[str]:
    row = [""] * 19
    row[2], row[3], row[4], row[6], row[7] = kind, item, name, source, source_name
    return row


def test_recipe_limit_applies_after_both_evidence_sources(pack: Path) -> None:
    row = _relation("合成", "I001", "对象1")
    row[17], row[18] = "I099", "材料x2"
    (pack / "掉落与获取关系.tsv").write_text("\t".join(row), encoding="utf-8")
    (pack / "脚本调用参数索引.tsv").write_text(
        "call YDWENewItemsFormula('I099',2,'I002')\n", encoding="utf-8"
    )
    full = queries.execute_pack_query(PackQueryCliOptions(str(pack), "recipe", "对象"))
    limited = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "recipe", "对象", limit=1)
    )
    assert "[I001]" in full.render() and "[I002]" in full.render()
    assert "[I002]" not in limited.render()
    assert "其余 1 条未显示" in limited.render()


def test_one_selected_shop_keeps_its_stock_and_crafting_evidence(pack: Path) -> None:
    row = _relation("商店制造", "I002", "对象2", "n001", "商店1")
    (pack / "掉落与获取关系.tsv").write_text("\t".join(row), encoding="utf-8")
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "shop", "商店", limit=1)
    )
    assert "I001" in result.render() and "I002" in result.render()
    assert "商店制造" in result.render()
    assert "n002" not in result.render()
    assert "其余 2 条未显示" in result.render()


@pytest.mark.parametrize("command", ["item", "price"])
def test_item_queries_keep_legacy_records_without_description_columns(
    pack: Path, command: str
) -> None:
    (pack / "对象ID" / "物品.tsv").write_text(
        "分类\tID\t数值\t基础ID\t名称\n物品\tI001\t1\tzzzz\t旧物品\n", encoding="utf-8"
    )
    result = queries.execute_pack_query(PackQueryCliOptions(str(pack), command, "I001"))
    assert result.exit_code == 0 and "[I001]" in result.render()


@pytest.mark.parametrize("command", ["item", "tech", "price", "shop"])
def test_named_queries_use_unicode_casefold(pack: Path, command: str) -> None:
    for path in (pack / "对象ID").glob("*.tsv"):
        path.write_text(
            path.read_text(encoding="utf-8").replace("对象1", "Straße"),
            encoding="utf-8",
        )
    fields = pack / "对象字段.tsv"
    fields.write_text(
        fields.read_text(encoding="utf-8").replace("商店1", "Straße"), encoding="utf-8"
    )
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), command, "STRASSE")
    )
    assert result.exit_code == 0 and "Straße" in result.render()


def test_recipe_material_names_use_casefold_and_miss_counts_variants(
    pack: Path,
) -> None:
    first = _relation("合成", "I001", "对象1")
    first[17], first[18] = "I098", "Straßex2"
    second = first.copy()
    second[17], second[18] = "I099", "其他材料x2"
    (pack / "掉落与获取关系.tsv").write_text(
        "\t".join(first) + "\n" + "\t".join(second), encoding="utf-8"
    )
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "recipe", "STRASSE")
    )
    assert result.exit_code == 0 and "Straßex2" in result.render()
    miss = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "recipe", "不存在的材料")
    )
    assert miss.exit_code == 2 and "共 2 条合成配方" in miss.render()
