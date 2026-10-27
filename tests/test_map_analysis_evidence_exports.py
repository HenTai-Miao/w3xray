"""Public pack export/query/profile paths carry the new source evidence."""

import csv
from io import StringIO
from pathlib import Path

import pytest

from gametool import pack_query_cli
from gametool.extraction_profile import ExtractionProfile
from gametool.knowledge_pack import write_knowledge_pack
from gametool.map_data import MapData
from gametool.pack_query_options import PackQueryCliOptions


def _fixture(tmp_path: Path) -> tuple[MapData, Path]:
    source = tmp_path / "source"
    source.mkdir()
    (source / "hidden.blp").write_bytes(b"BLP1payload")
    (source / "table.slk").write_text(
        'ID;PWXL;N;E\nC;X1;Y1;K"hidden.blp"\nE\n', encoding="utf-8"
    )
    script = (
        "function Entry takes nothing returns nothing\n"
        "call Later()\ncall Later()\ncall Later()\n"
        "endfunction\nfunction Later takes nothing returns nothing\nendfunction\n"
    )
    md = MapData(
        str(source),
        "source-evidence",
        scripts={"war3map.j": script},
        all_files=["table.slk"],
    )
    return md, tmp_path / "pack"


def test_actual_pack_exports_manifested_candidates_and_discovered_body(
    tmp_path: Path,
) -> None:
    md, pack = _fixture(tmp_path)
    before = {
        entry.name: (entry.read_bytes(), entry.stat().st_mtime_ns)
        for entry in Path(md.path).iterdir()
    }
    write_knowledge_pack(md, str(pack), profile=ExtractionProfile())
    candidate_text = (pack / "资源" / "隐式资源候选.tsv").read_text(encoding="utf-8")
    rows = list(csv.reader(StringIO(candidate_text), delimiter="\t"))
    item = next(row for row in rows if row[0] == "hidden.blp")
    assert item[2] == "confirmed" and item[9] == 'K"hidden.blp"' and item[14] == "11"
    assert (pack / "资源" / "素材文件" / "hidden.blp").read_bytes() == b"BLP1payload"
    inventory = (pack / "资源" / "资源资产索引.tsv").read_text(encoding="utf-8")
    assert (
        "hidden.blp\t图像\t存在/已引用" in inventory and "当前归档实读确认" in inventory
    )
    manifest = (pack / "资料包目录.tsv").read_text(encoding="utf-8")
    assert "资源/隐式资源候选.tsv" in manifest and "脚本前向引用.tsv" in manifest
    assert "资源/脚本前向引用.tsv" not in manifest
    assert "脚本前向引用.tsv" in (pack / "资料包写入结果.tsv").read_text(
        encoding="utf-8"
    )
    assert before == {
        entry.name: (entry.read_bytes(), entry.stat().st_mtime_ns)
        for entry in Path(md.path).iterdir()
    }
    assert md.all_files == ["table.slk"]


def test_public_text_query_finds_every_forward_record_and_limits_whole_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    md, pack = _fixture(tmp_path)
    write_knowledge_pack(md, str(pack), profile=ExtractionProfile())
    monkeypatch.setattr(pack_query_cli, "_memo_dir", lambda: tmp_path / "memo")
    result = pack_query_cli.execute_pack_query(
        PackQueryCliOptions(str(pack), "text", "forward")
    )
    assert result.exit_code == 0
    output = result.render()
    assert output.count("脚本前向引用.tsv:") == 3 and "source-function" in output
    limited = pack_query_cli.execute_pack_query(
        PackQueryCliOptions(str(pack), "text", "forward", limit=1)
    )
    output = limited.render()
    assert output.count("脚本前向引用.tsv:") == 1 and "Later()" in output
    assert "其余 2 条未显示" in output


@pytest.mark.parametrize("disabled", ["resources", "scripts"])
def test_new_artifacts_obey_their_real_extraction_profile_categories(
    tmp_path: Path, disabled: str
) -> None:
    md, pack = _fixture(tmp_path)
    write_knowledge_pack(md, str(pack), profile=ExtractionProfile({disabled: False}))
    assert (pack / "脚本前向引用.tsv").exists() is (disabled != "scripts")
    assert (pack / "资源" / "隐式资源候选.tsv").exists() is (disabled != "resources")
    coverage = (pack / "需求覆盖.tsv").read_text(encoding="utf-8")
    assert "按提取配置未产出" in coverage
    if disabled == "scripts":
        line = next(
            line
            for line in coverage.splitlines()
            if line.startswith("诊断 JASS 声明顺序\t")
        )
        assert "按请求未产出主要产物" in line and "脚本前向引用.tsv" in line
