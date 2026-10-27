"""Protected script evidence stays unknown without erasing confirmed records."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.batch_tsv import format_tsv_rows
from gametool.item_relation_exports import ACQUISITION_REPORT_HEADER
from gametool.pack_query_options import PackQueryCliOptions


_REPORT = (
    "检测到平台插件加密脚本块：\n"
    "- 块 000042（Unknown，2787084 字节）：KKWE 加密 JASS\n"
    "- 块 9007199254740993（UnknownRaw，17 字节）：KKWE 加密 JASS\n"
    "\n真实脚本被加密存放，静态解析读不到触发逻辑。\n"
)


def _pack(root: Path, *, protected: bool = True, matched: bool = False) -> None:
    objects = root / "对象ID"
    objects.mkdir(parents=True)
    (objects / "物品.tsv").write_text(
        "分类\tID\t名称\n物品\tI001\t祷告之花\n", encoding="utf-8"
    )
    (objects / "单位.tsv").write_text(
        "分类\tID\t名称\n单位\tn001\t守卫\n", encoding="utf-8"
    )
    scripts = root / "脚本原始文本"
    scripts.mkdir()
    (scripts / "war3map.j").write_text(
        "// *** GENERATED WITH KKWE DO NOT EDIT ***\n// by Jai\n", encoding="utf-8"
    )
    (root / "脚本清单.txt").write_text(
        "脚本文件：1\nwar3map.j\t2 行\t55 字符\t语言:JASS\n", encoding="utf-8"
    )
    reference = [("来源", "行号", "函数", "对象码", "分类", "名称")]
    if matched:
        reference.append(("war3map.j", "1", "Spawn", "I001", "物品", "祷告之花"))
    (root / "脚本对象码出现索引.tsv").write_text(
        format_tsv_rows(reference), encoding="utf-8"
    )
    (root / "脚本调用参数索引.tsv").write_text(
        "来源\t行号\t函数\t调用\t参数序号\t参数\t字符串\t对象码\t机制\t用途\t摘要\t调用偏移\n",
        encoding="utf-8",
    )
    (root / "脚本字符串索引.tsv").write_text(
        "调用\t文本\n" + ("QuestSetTitle\t祷告之花\n" if matched else ""),
        encoding="utf-8",
    )
    if protected:
        unknown = root / "未知文件"
        unknown.mkdir()
        (unknown / "加密脚本检测.txt").write_text(_REPORT, encoding="utf-8")
    if matched:
        rows: list[tuple[str, ...]] = [ACQUISITION_REPORT_HEADER]
        for kind in ("怪物直接掉落", "合成"):
            row = [""] * len(ACQUISITION_REPORT_HEADER)
            for column, value in {
                0: kind,
                2: kind,
                3: "I001",
                4: "祷告之花",
                5: "单位",
                6: "n001",
                7: "守卫",
                17: "I002",
                18: "完整材料 × 9007199254740993",
                19: "war3mapUnits.doo",
                23: "已确认",
                24: "完整",
            }.items():
                row[column] = value
            rows.append(tuple(row))
        (root / "掉落与获取关系.tsv").write_text(
            format_tsv_rows(rows), encoding="utf-8"
        )


def _run(root: Path, command: str, query: str = "I001"):
    return queries.execute_pack_query(PackQueryCliOptions(str(root), command, query))


@pytest.mark.parametrize(
    "command,query",
    (
        ("refs", "I001"),
        ("locate", "I001"),
        ("recipe", "I001"),
        ("synth", ""),
        ("quest", ""),
        ("cmd", ""),
        ("where", "I001"),
        ("drop", "I001"),
    ),
)
def test_protected_empty_queries_preserve_uncertainty_and_successful_memo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, query: str
) -> None:
    _pack(tmp_path)
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    assert _run(tmp_path, "item").exit_code == 0
    memo = queries._memo_dir() / queries._LAST_QUERY_FILE
    before = memo.read_bytes()

    result = _run(tmp_path, command, query)
    payload = json.loads(result.render(as_json=True))

    assert payload["exit_code"] == 2
    assert payload["has_matches"] is False
    assert payload["input_error"] is False
    coverage = payload["script_coverage"]
    assert coverage["complete"] is False
    assert coverage["diagnostics"]
    report = next(
        source
        for source in coverage["sources"]
        if source["path"].endswith("加密脚本检测.txt")
    )
    assert report["records"] == [
        [line] if line else [] for line in _REPORT.splitlines()
    ]
    assert "9007199254740993" in result.render()
    assert "此处即「孤立对象」信号" not in result.render()
    assert "本包无合成配方" not in result.render()
    assert memo.read_bytes() == before


@pytest.mark.parametrize(
    "command", ("refs", "locate", "recipe", "synth", "where", "drop", "quest")
)
def test_confirmed_matches_survive_protected_source_diagnostics(
    tmp_path: Path, command: str
) -> None:
    _pack(tmp_path, matched=True)
    result = _run(tmp_path, command, "" if command in ("quest", "synth") else "I001")
    payload = json.loads(result.render(as_json=True))

    assert payload["exit_code"] == 0
    assert payload["has_matches"] is True
    assert payload["script_coverage"]["complete"] is False
    assert payload["input_error"] is False
    assert "祷告之花" in result.render() or command == "locate"
    assert "9007199254740993" in result.render()
    assert "此处即「孤立对象」信号" not in result.render()


def test_comment_only_primary_is_not_itself_proof_of_missing_logic(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, protected=False)
    payload = json.loads(_run(tmp_path, "refs").render(as_json=True))

    assert payload["script_coverage"]["complete"] is True
    assert payload["script_coverage"]["diagnostics"] == []
    assert payload["input_error"] is False


def test_legacy_index_only_pack_keeps_its_confirmed_reference(tmp_path: Path) -> None:
    _pack(tmp_path, protected=False, matched=True)
    (tmp_path / "脚本原始文本" / "war3map.j").unlink()
    (tmp_path / "脚本原始文本").rmdir()
    (tmp_path / "脚本清单.txt").unlink()
    payload = json.loads(_run(tmp_path, "refs").render(as_json=True))

    assert payload["exit_code"] == 0
    assert payload["has_matches"] is True
    assert payload["script_coverage"]["complete"] is None
    assert payload["script_coverage"]["diagnostics"] == []


def test_declared_missing_source_downgrades_reference_completeness(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, protected=False, matched=True)
    (tmp_path / "脚本原始文本" / "war3map.j").unlink()
    result = _run(tmp_path, "refs")
    payload = json.loads(result.render(as_json=True))

    assert payload["exit_code"] == 0
    assert payload["script_coverage"]["complete"] is False
    assert "此处即「孤立对象」信号" not in result.render()
    assert any(
        source["state"] == "declared_missing"
        for source in payload["script_coverage"]["sources"]
    )


def test_script_read_failure_is_coverage_uncertainty_not_input_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pack(tmp_path, protected=False, matched=True)
    source = tmp_path / "脚本原始文本" / "war3map.j"
    original = Path.open

    def denied(path: Path, *args, **kwargs):
        if path == source:
            raise PermissionError("source locked")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    payload = json.loads(_run(tmp_path, "refs").render(as_json=True))

    assert payload["exit_code"] == 0
    assert payload["input_error"] is False
    assert payload["script_coverage"]["complete"] is False
    assert any(
        row["state"] == "read_failed" for row in payload["script_coverage"]["sources"]
    )


def test_campaign_retains_diagnostic_only_scope_and_confirmed_other_scope(
    tmp_path: Path,
) -> None:
    _pack(tmp_path / "子地图" / "001", matched=False)
    _pack(tmp_path / "子地图" / "002", matched=True)
    result = _run(tmp_path, "refs")
    payload = json.loads(result.render(as_json=True))

    assert payload["exit_code"] == 0
    assert payload["has_matches"] is True
    assert payload["script_coverage"]["complete"] is False
    assert {Path(section["pack"]).name for section in payload["sections"]} == {
        "001",
        "002",
    }
    by_pack = {Path(section["pack"]).name: section for section in payload["sections"]}
    assert by_pack["001"]["has_matches"] is False
    assert by_pack["002"]["has_matches"] is True
    assert all(
        section["script_coverage"]["diagnostics"] for section in payload["sections"]
    )
    assert len(payload["checked_packs"]) == 3


def test_exported_object_report_retains_complete_protected_source_diagnostics(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, matched=True)
    result = _run(tmp_path, "export")
    payload = json.loads(result.render(as_json=True))
    exported = Path(
        next(
            line.removeprefix("已导出: ")
            for line in payload["lines"]
            if line.startswith("已导出: ")
        )
    )
    content = exported.read_text(encoding="utf-8")

    assert payload["exit_code"] == 0
    assert payload["script_coverage"]["complete"] is False
    assert "祷告之花" in content
    assert "9007199254740993" in content
    assert "加密脚本检测.txt" in content


def test_protected_sale_does_not_claim_unit_death_drops_are_absent(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, matched=True)
    path = tmp_path / "掉落与获取关系.tsv"
    path.write_text(
        "关系类型\t装备ID\t装备名称\t来源分类\t来源ID\t来源名称\n"
        "商店出售\tI001\t祷告之花\t单位\tn001\t守卫\n",
        encoding="utf-8",
    )

    result = _run(tmp_path, "drop")
    payload = json.loads(result.render(as_json=True))

    assert payload["exit_code"] == 0
    assert payload["has_matches"] is True
    assert payload["script_coverage"]["complete"] is False
    assert "该物品无 Boss/单位死亡掉落记录" not in result.render()


def test_script_component_failure_keeps_its_complete_original_record(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, protected=False, matched=True)
    row = (
        "wct",
        "war3map.wct",
        "parse",
        "warning",
        "BadSource",
        "是",
        "truncated\n完整后续",
        "扩展证据",
    )
    (tmp_path / "组件诊断.tsv").write_text(
        format_tsv_rows(
            (
                ("组件", "来源", "阶段", "级别", "异常类型", "可恢复", "消息", "扩展"),
                row,
            )
        ),
        encoding="utf-8",
        newline="",
    )
    payload = json.loads(_run(tmp_path, "refs").render(as_json=True))

    assert payload["exit_code"] == 0
    assert payload["script_coverage"]["complete"] is False
    report = next(
        source
        for source in payload["script_coverage"]["sources"]
        if source["state"] == "component_report"
    )
    assert report["records"][1] == list(row)


def test_unrelated_component_warning_does_not_downgrade_script_source(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, protected=False, matched=True)
    (tmp_path / "组件诊断.tsv").write_text(
        "组件\t来源\t级别\t消息\nobject-text\tunits/itemfunc.txt\twarning\t说明不可读\n",
        encoding="utf-8",
    )
    payload = json.loads(_run(tmp_path, "refs").render(as_json=True))

    assert payload["exit_code"] == 0
    assert payload["script_coverage"]["complete"] is True


def test_campaign_schema_diagnostic_only_scope_is_not_a_json_match(
    tmp_path: Path,
) -> None:
    child = tmp_path / "子地图" / "001"
    _pack(child, protected=False)
    (child / "脚本对象码出现索引.tsv").write_text(
        "来源\t行号\t对象码\t对象码\nwar3map.j\t1\tI001\tI002\n",
        encoding="utf-8",
    )

    payload = json.loads(_run(tmp_path, "refs").render(as_json=True))

    assert payload["exit_code"] == 2
    assert payload["has_matches"] is False
    assert payload["input_error"] is False
    child_section = next(
        section for section in payload["sections"] if section["pack"] == str(child)
    )
    assert child_section["has_matches"] is False


@pytest.mark.parametrize("count", ("1", "9" * 5000), ids=("one", "large_decimal"))
def test_declared_script_count_without_records_preserves_unknown_coverage(
    tmp_path: Path, count: str
) -> None:
    _pack(tmp_path, protected=False)
    (tmp_path / "脚本原始文本" / "war3map.j").unlink()
    (tmp_path / "脚本原始文本").rmdir()
    (tmp_path / "脚本清单.txt").write_text(
        "脚本文件：" + count + "\n", encoding="utf-8"
    )

    result = _run(tmp_path, "refs")
    payload = json.loads(result.render(as_json=True))

    assert payload["exit_code"] == 2
    assert payload["script_coverage"]["complete"] is False
    assert "此处即「孤立对象」信号" not in result.render()
    assert any(
        row["state"] == "manifest_incomplete"
        for row in payload["script_coverage"]["sources"]
    )
    synth = _run(tmp_path, "synth", "")
    assert "本包无合成配方" not in synth.render()
    assert count in synth.render()


def test_script_manifest_counts_non_analysis_wts_records(tmp_path: Path) -> None:
    _pack(tmp_path, protected=False)
    (tmp_path / "脚本清单.txt").write_text(
        "脚本文件：2\nwar3map.j\t2 行\t55 字符\t语言:JASS\n"
        "war3map.wts\t12 行\t234 字符\t语言:非分析文本\n",
        encoding="utf-8",
    )

    payload = json.loads(_run(tmp_path, "refs").render(as_json=True))

    assert payload["script_coverage"]["complete"] is True
    assert payload["script_coverage"]["diagnostics"] == []


def test_declared_zero_scripts_is_a_valid_empty_manifest(tmp_path: Path) -> None:
    _pack(tmp_path, protected=False)
    (tmp_path / "脚本原始文本" / "war3map.j").unlink()
    (tmp_path / "脚本原始文本").rmdir()
    (tmp_path / "脚本清单.txt").write_text("脚本文件：0\n", encoding="utf-8")

    payload = json.loads(_run(tmp_path, "refs").render(as_json=True))

    assert payload["script_coverage"]["complete"] is True
    assert payload["script_coverage"]["diagnostics"] == []


def test_campaign_discovers_encryption_report_only_child(tmp_path: Path) -> None:
    first = tmp_path / "子地图" / "001"
    (first / "未知文件").mkdir(parents=True)
    (first / "未知文件" / "加密脚本检测.txt").write_text(_REPORT, encoding="utf-8")
    _pack(tmp_path / "子地图" / "002", protected=False, matched=True)

    payload = json.loads(_run(tmp_path, "refs").render(as_json=True))

    assert payload["exit_code"] == 0
    assert payload["has_matches"] is True
    assert payload["script_coverage"]["complete"] is False
    assert {Path(section["pack"]).name for section in payload["sections"]} == {
        "001",
        "002",
    }
    assert str(first) in payload["checked_packs"]


def test_campaign_discovers_original_script_only_child(tmp_path: Path) -> None:
    first = tmp_path / "子地图" / "001"
    (first / "脚本原始文本").mkdir(parents=True)
    (first / "脚本原始文本" / "war3map.lua").write_text(
        "return true\n", encoding="utf-8"
    )
    _pack(tmp_path / "子地图" / "002", protected=False, matched=True)

    payload = json.loads(_run(tmp_path, "refs").render(as_json=True))

    assert payload["exit_code"] == 0
    assert str(first) in payload["checked_packs"]


@pytest.mark.parametrize("matched", (False, True))
def test_unknown_language_analysis_context_does_not_assert_complete_logic(
    tmp_path: Path, matched: bool
) -> None:
    _pack(tmp_path, protected=False, matched=matched)
    scripts = tmp_path / "脚本原始文本"
    (scripts / "war3map.j").unlink()
    (scripts / "custom_code.txt").write_text("return 'I001'\n", encoding="utf-8")
    (tmp_path / "脚本清单.txt").write_text(
        "脚本文件：1\ncustom_code.txt\t1 行\t14 字符\t语言:未知\n",
        encoding="utf-8",
    )

    result = _run(tmp_path, "refs")
    payload = json.loads(result.render(as_json=True))

    assert payload["exit_code"] == (0 if matched else 2)
    assert payload["has_matches"] is matched
    assert payload["script_coverage"]["complete"] is False
    assert any(
        source["state"] == "unknown_language"
        for source in payload["script_coverage"]["sources"]
    )
    assert "此处即「孤立对象」信号" not in result.render()
