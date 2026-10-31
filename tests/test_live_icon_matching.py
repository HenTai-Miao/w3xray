"""Known synthetic pixels verify icon scores and image-coordinate attribution."""

from __future__ import annotations

import sys

import numpy as np
from PIL import Image
import pytest


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows live module")


@pytest.mark.parametrize("point", ((0, 0), (17, 11), (39, 29)))
def test_ncc_exact_match_scores_one_at_its_true_top_left(
    point: tuple[int, int],
) -> None:
    from gametool.live_inventory import ncc_best

    rng = np.random.default_rng(42)
    region = rng.integers(0, 256, (40, 52)).astype(np.float64)
    template = rng.integers(0, 256, (11, 13)).astype(np.float64)
    x, y = point
    region[y : y + 11, x : x + 13] = template
    score, located = ncc_best(region, template)
    assert score == pytest.approx(1.0)
    assert located == point


def test_full_image_match_keeps_multiple_names_and_correct_coordinates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gametool import live_inventory as live

    rng = np.random.default_rng(17)
    pixels = rng.integers(0, 256, (70, 100), dtype=np.uint8)
    first = rng.integers(0, 256, (9, 9), dtype=np.uint8)
    second = rng.integers(0, 256, (9, 9), dtype=np.uint8)
    pixels[10:19, 12:21] = first
    pixels[45:54, 70:79] = second
    arrays = {"first": first.astype(np.float64), "second": second.astype(np.float64)}
    monkeypatch.setattr(live, "get_icon_array", lambda path, _size: arrays[path])
    matches = live.match_image_full(
        Image.fromarray(pixels),
        {"I001": "first", "I002": "second"},
        {b"I001": "第一物品", b"I002": "第二物品"},
        min_score=0.99,
        downscale=1,
        sizes=(9,),
    )
    assert {(entry[1], entry[2], entry[3]) for entry in matches} == {
        ("I001", "第一物品", (12, 10)),
        ("I002", "第二物品", (70, 45)),
    }
    assert all(entry[0] == pytest.approx(1.0) for entry in matches)


def test_inventory_crop_reports_window_pixels_instead_of_crop_pixels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gametool import live_inventory as live

    pixels = np.zeros((100, 200), dtype=np.uint8)
    monkeypatch.setattr(live, "get_icon_array", lambda _path, _size: np.ones((2, 2)))
    monkeypatch.setattr(live, "ncc_best", lambda _region, _template: (1.0, (5, 7)))
    matches = live.match_inventory(
        Image.fromarray(pixels), {"I001": "icon"}, {b"I001": "第一物品"}
    )
    assert len(matches) == 1
    assert matches[0][2:4] == ("第一物品", (129, 67))
