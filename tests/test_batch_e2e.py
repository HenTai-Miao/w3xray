"""Observable end-to-end batch command scenarios over real MPQ fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path

from w3xtool.batch_cli import BatchCliOptions, run_batch_cli

_FIXTURE = Path(__file__).parent / "fixtures" / "maps" / "war3net-map-script-builder.w3x"


def test_batch_e2e_publishes_per_map_and_global_reports(tmp_path: Path) -> None:
    # Given
    maps = tmp_path / "Maps"
    maps.mkdir()
    shutil.copyfile(_FIXTURE, maps / "sample.w3x")
    output = tmp_path / "output"

    # When
    code = run_batch_cli(BatchCliOptions(str(maps), str(output)))

    # Then
    assert code == 0
    assert tuple(output.glob("地图/*/地图摘要.txt"))
    assert tuple(output.glob("地图/*/图标索引.tsv"))
    assert tuple(output.glob("地图/*/对象描述.tsv"))
    assert (output / "批量提取汇总.tsv").is_file()
    assert (output / "批量提取状态.json").is_file()
    assert (output / "失败与重试.tsv").is_file()


def test_batch_e2e_continues_after_a_corrupt_sibling(tmp_path: Path) -> None:
    # Given
    maps = tmp_path / "Maps"
    maps.mkdir()
    (maps / "a_corrupt.w3x").write_bytes(b"not an MPQ")
    shutil.copyfile(_FIXTURE, maps / "b_valid.w3x")
    output = tmp_path / "output"

    # When
    code = run_batch_cli(BatchCliOptions(str(maps), str(output)))

    # Then
    assert code == 1
    summary = (output / "批量提取汇总.tsv").read_text(encoding="utf-8")
    assert "a_corrupt.w3x" in summary and "失败" in summary
    assert "b_valid.w3x" in summary
    assert tuple(output.glob("地图/*/地图摘要.txt"))
