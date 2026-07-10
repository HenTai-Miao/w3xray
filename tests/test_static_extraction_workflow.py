"""End-to-end release scenario for the complete static extraction workflow."""

from __future__ import annotations

from pathlib import Path

from w3xtool.api import load_map
from w3xtool.external_listfile import read_external_listfile
from w3xtool.knowledge_pack import write_knowledge_pack
from w3xtool.load_context import build_map_load_context

FIXTURES = Path(__file__).with_name("fixtures")
MAP_FIXTURE = FIXTURES / "maps" / "war3net-map-script-builder.w3x"
TRIGGER_FIXTURE_DIR = FIXTURES / "trigger"


def test_real_format_trigger_listfile_pack_workflow(tmp_path: Path) -> None:
    # Given: a real Reforged-format map, matching trigger schemas, and an external listfile.
    listfile = tmp_path / "listfile.txt"
    _ = listfile.write_text("war3map.wtg\nmissing/custom.blp\n", encoding="utf-8")
    context = build_map_load_context(
        external_names=read_external_listfile(str(listfile)),
        game_data_path=str(TRIGGER_FIXTURE_DIR),
    )
    md = load_map(str(MAP_FIXTURE), load_context=context)
    before = tuple(md.all_files)

    # When: the complete knowledge pack is written from that immutable map model.
    pack = tmp_path / "pack"
    written = write_knowledge_pack(md, str(pack), game_data_path=str(TRIGGER_FIXTURE_DIR))

    # Then: ECA localization, listfile diagnostics, identity, resources, and boundaries coexist.
    assert written > 0
    assert tuple(md.all_files) == before
    eca = (pack / "触发器ECA.tsv").read_text(encoding="utf-8")
    coverage = (pack / "需求覆盖.tsv").read_text(encoding="utf-8")
    manifest = (pack / "资料包目录.tsv").read_text(encoding="utf-8")
    assert "语义文本" in eca
    assert "Kill gg_unit_hpea_0006" in eca
    assert "WTG ECA\t已提取" in coverage
    assert "TriggerStrings 本地化可用" in coverage
    assert "外部 listfile\t部分采用" in coverage
    assert "确认 1，缺失 1" in coverage
    assert "ECA 展开需匹配 TriggerData，语义本地化需 TriggerStrings" in manifest
    assert (pack / "地图与对象ID索引.tsv").is_file()
    assert (pack / "资源" / "资源资产索引.tsv").is_file()
    assert (pack / "提取完整性.txt").is_file()
