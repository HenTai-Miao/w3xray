"""端到端: 关类目导出 → 对应文件确实不存在; 全开 → 与默认一致。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from gametool.api import load_map
from gametool.extraction_profile import (
    CATEGORY_OBJECTS,
    CATEGORY_TRIGGERS,
    ExtractionProfile,
    normalize_profile,
)
from gametool.knowledge_pack import write_knowledge_pack_report
from gametool.mpq_layout import MPQLayoutError

_FIXTURE_MAP = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "maps"
    / "war3net-map-script-builder.w3x"
)


def _load_profile_map():
    explicit_map = os.environ.get("GAMEXRAY_TEST_MAP")
    if explicit_map is None:
        if os.environ.get("GAMEXRAY_REAL_MAP_TEST") == "1":
            pytest.fail(
                "GAMEXRAY_REAL_MAP_TEST=1 需要用 GAMEXRAY_TEST_MAP 明确选择地图文件"
            )
        path = _FIXTURE_MAP
    else:
        if not explicit_map:
            pytest.fail("GAMEXRAY_TEST_MAP 不能为空")
        path = Path(explicit_map).expanduser()
    if not path.is_file() or path.suffix.casefold() not in {".w3x", ".w3m"}:
        pytest.fail(f"提取配置测试需要存在的 .w3x/.w3m 地图，当前路径: {path}")
    return load_map(str(path))


class TestProfileEndToEnd:
    def test_disabled_categories_skip_files(self, tmp_path):
        md = _load_profile_map()
        try:
            profile = normalize_profile(
                {CATEGORY_TRIGGERS: False, CATEGORY_OBJECTS: False}
            )
            out = str(tmp_path / "pack-off")
            write_knowledge_pack_report(md, out, profile=profile)
            # 关掉的组: 对象表与触发器文件不存在
            assert not os.path.exists(os.path.join(out, "对象ID"))
            assert not os.path.exists(os.path.join(out, "对象字段.tsv"))
            assert not os.path.exists(os.path.join(out, "触发器ECA.tsv"))
            # 开着的组: 存在且非空
            assert os.path.exists(os.path.join(out, "预放置单位.tsv"))
            assert os.path.getsize(os.path.join(out, "预放置单位.tsv")) > 100
        finally:
            md.close()

    def test_default_profile_matches_full_export(self, tmp_path):
        md = _load_profile_map()
        try:
            out_full = str(tmp_path / "pack-full")
            out_profile = str(tmp_path / "pack-default")
            write_knowledge_pack_report(md, out_full)
            write_knowledge_pack_report(md, out_profile, profile=ExtractionProfile())
            full_files = set(os.listdir(out_full))
            profile_files = set(os.listdir(out_profile))
            assert full_files == profile_files
        finally:
            md.close()


@pytest.mark.parametrize("invalid_input", ("empty", "missing", "directory", "suffix"))
def test_explicit_map_rejects_invalid_input(tmp_path, monkeypatch, invalid_input):
    path = tmp_path / "selected.w3x"
    if invalid_input == "directory":
        path.mkdir()
    elif invalid_input == "suffix":
        path = tmp_path / "selected.txt"
        path.write_bytes(_FIXTURE_MAP.read_bytes())
    monkeypatch.setenv(
        "GAMEXRAY_TEST_MAP", "" if invalid_input == "empty" else str(path)
    )

    with pytest.raises(pytest.fail.Exception, match="GAMEXRAY_TEST_MAP|提取配置测试"):
        _load_profile_map()


def test_explicit_map_parse_failure_never_loads_default_fixture(tmp_path, monkeypatch):
    path = tmp_path / "broken.w3x"
    path.write_bytes(b"not an MPQ archive")
    monkeypatch.setenv("GAMEXRAY_TEST_MAP", str(path))

    with pytest.raises(MPQLayoutError):
        _load_profile_map()


def test_explicit_map_uses_selected_source(tmp_path, monkeypatch):
    path = tmp_path / "selected.w3x"
    path.write_bytes(_FIXTURE_MAP.read_bytes())
    monkeypatch.setenv("GAMEXRAY_TEST_MAP", str(path))
    monkeypatch.setenv("GAMEXRAY_REAL_MAP_TEST", "1")

    md = _load_profile_map()
    try:
        assert Path(md.path).resolve() == path.resolve()
        assert md.units
    finally:
        md.close()


def test_real_map_flag_requires_explicit_source(monkeypatch):
    monkeypatch.delenv("GAMEXRAY_TEST_MAP", raising=False)
    monkeypatch.setenv("GAMEXRAY_REAL_MAP_TEST", "1")

    with pytest.raises(pytest.fail.Exception, match="GAMEXRAY_TEST_MAP"):
        _load_profile_map()
