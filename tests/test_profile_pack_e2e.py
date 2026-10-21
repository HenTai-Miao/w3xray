"""端到端: 关类目导出 → 对应文件确实不存在; 全开 → 与默认一致。"""

from __future__ import annotations

import os

import pytest

from gametool.extraction_profile import (
    CATEGORY_OBJECTS,
    CATEGORY_TRIGGERS,
    ExtractionProfile,
    normalize_profile,
)
from gametool.knowledge_pack import write_knowledge_pack_report

pytestmark = pytest.mark.skipif(
    os.environ.get("GAMEXRAY_REAL_MAP_TEST") != "1",
    reason="需要真实地图与游戏数据 (GAMEXRAY_REAL_MAP_TEST=1 开启)",
)


def _load_real_map():
    import glob

    candidates = sorted(
        glob.glob(
            r"C:/Program Files (x86)/Warcraft III Frozen Throne/Maps/dz/rpg/*.w3x"
        )
    )
    for path in candidates:
        try:
            from gametool.api import load_map

            return load_map(path)
        except Exception:
            continue
    pytest.skip("无可解析的真实地图")


class TestProfileEndToEnd:
    def test_disabled_categories_skip_files(self, tmp_path):
        md = _load_real_map()
        profile = normalize_profile({CATEGORY_TRIGGERS: False, CATEGORY_OBJECTS: False})
        out = str(tmp_path / "pack-off")
        write_knowledge_pack_report(md, out, profile=profile)
        # 关掉的组: 对象表与触发器文件不存在
        assert not os.path.exists(os.path.join(out, "对象ID"))
        assert not os.path.exists(os.path.join(out, "对象字段.tsv"))
        assert not os.path.exists(os.path.join(out, "触发器ECA.tsv"))
        # 开着的组: 存在且非空
        assert os.path.exists(os.path.join(out, "预放置单位.tsv"))
        assert os.path.getsize(os.path.join(out, "预放置单位.tsv")) > 100

    def test_default_profile_matches_full_export(self, tmp_path):
        md = _load_real_map()
        out_full = str(tmp_path / "pack-full")
        out_profile = str(tmp_path / "pack-default")
        write_knowledge_pack_report(md, out_full)
        write_knowledge_pack_report(md, out_profile, profile=ExtractionProfile())
        full_files = set(os.listdir(out_full))
        profile_files = set(os.listdir(out_profile))
        assert full_files == profile_files
