"""Release regressions for isolated, truthful knowledge-pack publications."""

from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path

import pytest

from gametool.extraction_profile import normalize_profile
from gametool.knowledge_pack import write_knowledge_pack_report
from gametool.knowledge_results import KnowledgeWriteStatus
from gametool.map_data import GameObject, MapData


def test_republishing_a_nonempty_destination_preserves_the_complete_prior_tree(
    tmp_path: Path,
) -> None:
    first = MapData(path="first.w3x", name="旧地图")
    first.objects = {
        "物品": [GameObject("物品", "w3t", "I001", "ratf", "旧装备", True)]
    }
    pack = tmp_path / "pack"
    assert (
        write_knowledge_pack_report(first, str(pack)).status
        is KnowledgeWriteStatus.COMPLETE
    )
    (pack / "用户备注.txt").write_text("保留我的备注", encoding="utf-8")
    before = {
        path.relative_to(pack): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in pack.rglob("*")
        if path.is_file()
    }

    report = write_knowledge_pack_report(
        MapData(path="second.w3x", name="新地图"), str(pack)
    )

    assert report.status is KnowledgeWriteStatus.FAILED
    assert report.written_count == 0
    assert report.first_failure is not None
    assert "非空" in (report.first_failure.error or "")
    assert "空目录" in (report.first_failure.error or "")
    assert {
        path.relative_to(pack): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in pack.rglob("*")
        if path.is_file()
    } == before


@pytest.mark.parametrize(
    ("disabled", "unit_table", "doodad_table"),
    (("units", False, True), ("preplaced", True, False)),
)
def test_profile_uses_the_declared_unit_and_doodad_groups(
    tmp_path: Path,
    disabled: str,
    unit_table: bool,
    doodad_table: bool,
) -> None:
    pack = tmp_path / "pack"
    report = write_knowledge_pack_report(
        MapData(path="map.w3x", name="地图"),
        str(pack),
        profile=normalize_profile({disabled: False}),
    )

    assert report.status is KnowledgeWriteStatus.COMPLETE
    assert (pack / "预放置单位.tsv").exists() is unit_table
    assert (pack / "预放置装饰物.tsv").exists() is doodad_table
    coverage = (pack / "需求覆盖.tsv").read_text(encoding="utf-8")
    assert "按请求" in coverage
    assert disabled in coverage


def test_disabling_basic_reports_never_claims_the_missing_artifacts_were_exported(
    tmp_path: Path,
) -> None:
    pack = tmp_path / "pack"
    report = write_knowledge_pack_report(
        MapData(path="map.w3x", name="地图", scripts={"war3map.j": "call Confirmed()"}),
        str(pack),
        profile=normalize_profile({"basic": False}),
    )

    assert report.status is KnowledgeWriteStatus.COMPLETE
    assert not (pack / "地图信息.txt").exists()
    assert not (pack / "组件诊断.tsv").exists()
    rows = {
        row["需求"]: row
        for row in csv.DictReader(
            StringIO((pack / "需求覆盖.tsv").read_text(encoding="utf-8")),
            delimiter="\t",
        )
    }
    for request in ("脚本来源", "组件诊断", "整理配置文件格式"):
        assert rows[request]["状态"].startswith("按请求")
        assert rows[request]["主要产物"] == ""
        assert "未产出" in rows[request]["说明"]
    assert "basic" in rows["提取配置"]["说明"]
