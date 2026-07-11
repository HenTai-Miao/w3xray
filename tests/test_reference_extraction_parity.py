"""End-to-end extraction parity on independently written StormLib containers."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import subprocess
import sys

from w3xtool.api import load_map
from w3xtool.knowledge_pack import write_knowledge_pack_report
from w3xtool.knowledge_results import KnowledgeWriteStatus

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "reference"
_MAP = _FIXTURE_DIR / "stormlib-reference-parity-map.w3x"
_CAMPAIGN = _FIXTURE_DIR / "stormlib-reference-parity-campaign.w3n"
_HASHES = {
    _MAP: "78059e267336b1f9a4c19be3d9756ac91db61eb5590e7171a4165bfea479a3f6",
    _CAMPAIGN: "9ee3d9a8572d0f14c7895e6445fa25ce254a17a96359d7f2a83c907010f447eb",
}


def test_reference_parity_fixture_hashes_are_pinned() -> None:
    # Given/When: independently generated container bytes are hashed.
    actual = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in _HASHES}

    # Then: accidental fixture replacement cannot change the acceptance baseline.
    assert actual == _HASHES


def test_reference_map_produces_complete_sorted_four_category_reports(tmp_path: Path) -> None:
    # Given: one real MPQ combines GBK text, binary objects, SLK, WTS, JASS, Lua, WTG, and WCT.
    md = load_map(str(_MAP))

    # When: extraction publishes the complete knowledge pack.
    report = write_knowledge_pack_report(md, str(tmp_path / "pack"))

    # Then: every legacy category is sorted, unique, resolved, and includes its custom object.
    assert report.status is KnowledgeWriteStatus.COMPLETE
    expected = {"单位": "H001", "物品": "I001", "技能": "A001", "科技": "R001"}
    for category, custom_id in expected.items():
        text = (tmp_path / "pack" / "盒子兼容ID" / f"{category}ID.txt").read_text(
            encoding="utf-8",
        )
        ids = re.findall(r"^ID：(....)$", text, re.MULTILINE)
        assert ids == sorted(set(ids), key=lambda code: code.encode("latin-1"))
        assert custom_id in ids
        assert "TRIGSTR_" not in text

    unit = md.obj_index["H001"]
    ability = md.obj_index["A001"]
    assert unit.name == "圣骑士"
    assert unit.field_values["display:propernames"] == "光明使者"
    assert unit.field_values["display:description"] == "说明文本"
    assert ability.name == "测试技能"
    assert ability.field_values["DataA1"] == "777"
    assert ability.field_sources["DataA1"] == "war3map *Data.slk"
    assert {"base", "binary", "slk", "text"}.issubset(md.object_source_counts)
    assert md.object_source_counts["base"] > 0
    assert {"war3map.j", "war3map.lua"}.issubset(md.scripts)
    assert {"war3map.wtg", "war3map.wct"}.issubset(set(md.all_files))
    assert md.diagnostics == []


def test_reference_campaign_declares_reopenable_parity_child(tmp_path: Path) -> None:
    # Given: a real campaign MPQ declares the parity map through war3campaign.w3f.
    campaign = load_map(str(_CAMPAIGN))

    # When: the declared child is selected and independently published.
    assert campaign.w3f is not None
    child = campaign.sub_maps[0]
    report = write_knowledge_pack_report(child, str(tmp_path / "child-pack"))

    # Then: declaration order, persistent source, scripts, and child publication all survive.
    assert [entry.path for entry in campaign.w3f.maps] == ["Maps\\Parity01.w3x"]
    assert child.path == "Maps\\Parity01.w3x"
    assert child.archive_source is not None
    with child.archive_source.open() as archive:
        assert b"ParityLua" in archive.read_file("war3map.lua")
    assert report.status is KnowledgeWriteStatus.COMPLETE
    assert report.items_by_path["盒子兼容ID/单位ID.txt"].written
    assert not any(item.component == "campaign-child" for item in campaign.diagnostics)


def test_campaign_cli_pack_publishes_declared_child_outputs(tmp_path: Path) -> None:
    # Given: the public CLI receives the real reference campaign and an empty pack root.
    project_root = Path(__file__).resolve().parents[1]
    pack_dir = tmp_path / "campaign-pack"

    # When: the exact documented campaign publication command runs.
    result = subprocess.run(
        (
            sys.executable,
            "main.py",
            "cli",
            str(_CAMPAIGN),
            "--pack",
            str(pack_dir),
        ),
        cwd=project_root,
        check=False,
        capture_output=True,
        encoding="utf-8",
    )

    # Then: at least one child has its own terrain and resource reports.
    child_dirs = tuple((pack_dir / "子地图").glob("*"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert child_dirs
    assert (child_dirs[0] / "地形摘要.tsv").is_file()
    assert (child_dirs[0] / "资源" / "资源资产索引.tsv").is_file()
