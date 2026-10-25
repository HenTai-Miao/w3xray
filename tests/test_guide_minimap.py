# -*- coding: utf-8 -*-
"""guide --minimap-marks 纯函数测试: 边界换算/商店标注/JSON 点位/渲染冒烟。"""

from __future__ import annotations

import pytest

from gametool.guide_minimap import (
    GuideMinimapError,
    crop_to_playable,
    extra_marks_from_json,
    playable_bounds,
    render_marks,
    script_unit_positions,
    shop_marks,
    world_to_pixel,
)
from gametool.map_data import GameObject, MapData
from gametool.w3i import W3iInfo


def _md_with_bounds() -> MapData:
    md = MapData(path="m.w3x", name="m")
    md.w3i = W3iInfo(
        camera_bounds=(-8288.0, -4192.0, 4192.0, 4192.0, 0.0, 0.0, 0.0, 0.0),
        camera_margins=(96, 96, 96, 96),
    )
    return md


class TestPlayableBounds:
    def test_applies_margins(self):
        assert playable_bounds(_md_with_bounds()) == (-8192.0, -4096.0, 4096.0, 4096.0)

    def test_none_without_w3i(self):
        md = MapData(path="m.w3x", name="m")
        assert playable_bounds(md) is None

    def test_none_with_empty_bounds(self):
        md = MapData(path="m.w3x", name="m")
        md.w3i = W3iInfo()
        assert playable_bounds(md) is None

    def test_none_with_degenerate_span(self):
        md = MapData(path="m.w3x", name="m")
        md.w3i = W3iInfo(
            camera_bounds=(10.0, 10.0, 10.0, 10.0), camera_margins=(0, 0, 0, 0)
        )
        assert playable_bounds(md) is None


class TestWorldToPixel:
    bounds = (-8192.0, -4096.0, 4096.0, 4096.0)

    def test_top_left_corner(self):
        assert world_to_pixel(-8192, 4096, self.bounds, 100, 50) == (0.0, 0.0)

    def test_bottom_right_corner(self):
        assert world_to_pixel(4096, -4096, self.bounds, 100, 50) == (100.0, 50.0)

    def test_center(self):
        assert world_to_pixel(-2048, 0, self.bounds, 100, 50) == (50.0, 25.0)


class TestShopMarks:
    def test_usei_shelf_with_position(self):
        md = MapData(path="m.w3x", name="m")
        md.objects["单位"] = [
            GameObject(
                category="单位",
                ext="w3u",
                obj_id="n00D",
                base_id="n00D",
                name="军需官",
                is_custom=True,
                fields=[("usei", "I000,I001")],
            )
        ]
        positions = {"n00D": (-4901.0, -192.0)}
        assert shop_marks(md, positions) == (("军需官", -4901.0, -192.0),)

    def test_shelf_without_placement_skipped(self):
        md = MapData(path="m.w3x", name="m")
        md.objects["单位"] = [
            GameObject(
                category="单位",
                ext="w3u",
                obj_id="n00X",
                base_id="n00X",
                name="脚本商店",
                is_custom=True,
                fields=[("usei", "I000")],
            )
        ]
        assert shop_marks(md, {}) == ()

    def test_plain_unit_without_shelf_skipped(self):
        md = MapData(path="m.w3x", name="m")
        md.objects["单位"] = [
            GameObject(
                category="单位",
                ext="w3u",
                obj_id="n001",
                base_id="n001",
                name="杂兵",
                is_custom=True,
            )
        ]
        assert shop_marks(md, {"n001": (1.0, 2.0)}) == ()


class TestScriptPositions:
    def test_negative_space_coords(self):
        md = MapData(path="m.w3x", name="m")
        md.scripts = {
            "war3map.j": "set u = CreateUnit(p, 'n000', - 7910.0, 2596.0, 270.000)"
        }
        assert script_unit_positions(md) == {"n000": ((-7910.0, 2596.0),)}

    def test_every_position_per_code(self):
        md = MapData(path="m.w3x", name="m")
        md.scripts = {
            "war3map.j": "CreateUnit(p, 'n007', 3344.0, 1312.0, 90.0)\n"
            + "CreateUnit(p, 'n007', 1.0, 2.0, 90.0)"
        }
        assert script_unit_positions(md) == {"n007": ((3344.0, 1312.0), (1.0, 2.0))}


class TestExtraMarks:
    def test_valid_json(self, tmp_path):
        path = tmp_path / "marks.json"
        path.write_text('[["翡翠点", 32, -1888]]', encoding="utf-8")
        assert extra_marks_from_json(str(path)) == (("翡翠点", 32.0, -1888.0),)

    def test_not_a_list(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text('{"a": 1}', encoding="utf-8")
        with pytest.raises(GuideMinimapError, match="应是数组"):
            extra_marks_from_json(str(path))

    def test_bad_entry(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text('[["名", 1]]', encoding="utf-8")
        with pytest.raises(GuideMinimapError, match="格式错误"):
            extra_marks_from_json(str(path))


class TestRender:
    def test_crop_vertical_letterbox(self):
        from PIL import Image

        img = Image.new("RGB", (64, 64))
        out = crop_to_playable(img, (0.0, 0.0, 12288.0, 8192.0))
        assert out.size == (64, 43)

    def test_render_smoke(self, tmp_path):
        from PIL import Image

        img = Image.new("RGB", (120, 80), (40, 90, 40))
        out = tmp_path / "m.png"
        render_marks(
            img,
            (0.0, 0.0, 12000.0, 8000.0),
            (("商店", 100.0, 100.0), ("自定义", 6000.0, 4000.0)),
            str(out),
        )
        assert out.exists()
        assert out.stat().st_size > 0
