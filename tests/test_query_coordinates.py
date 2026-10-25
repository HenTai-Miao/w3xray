"""Precise coordinate handoff without IDs, counts or other units leaking in."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import cast

import pytest

from gametool.query_coordinates import coordinates_from_text, radius_from_text


@pytest.mark.parametrize(
    "text",
    [
        "1e-7 -2.123456789012345",
        "near 1e-7 -2.123456789012345 500",
        "单位: 目标 [n123] ×500 @(1e-7,-2.123456789012345) 距99",
        '"x":1e-7,"y":-2.123456789012345',
        '{"x":1e-7,"y":-2.123456789012345}',
    ],
)
def test_precise_pairs_ignore_other_numbers(text: str) -> None:
    point = coordinates_from_text(text)
    assert point is not None
    assert tuple(map(float, point)) == (1e-7, -2.123456789012345)


@pytest.mark.parametrize("key", ["selected", "selected_unit"])
def test_nested_selected_unit_wins_over_other_units(key: str) -> None:
    text = json.dumps(
        {
            "all_units": [{"x": 9000, "y": 8000}],
            key: {"x": 1e-7, "y": -2e3, "items": [{"code": "I123", "x": 50, "y": 60}]},
        }
    )
    point = coordinates_from_text(text)
    assert point is not None and tuple(map(float, point)) == (1e-7, -2000.0)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "目标 [n123] ×500",
        "1 2 3 4",
        "near 1 2\nnear 3 4",
        "@(1,2)\n@(3,4)",
        '{"all_units":[{"x":1,"y":2},{"x":3,"y":4}]}',
        '{"selected":null,"x":3,"y":4}',
        '{"selected":{"x":null,"y":2},"all_units":[{"x":3,"y":4}]}',
        '{"x":NaN,"y":2}',
        "near 1e309 2",
        '"x":1,"y":2,"x":3,"y":4',
    ],
)
def test_missing_invalid_or_multiple_coordinates_are_refused(text: str) -> None:
    assert coordinates_from_text(text) is None


@pytest.mark.parametrize("text", ['{"radius":1e-7}', "半径 1e-7", "1 2 1e-7"])
def test_radius_preserves_scientific_notation(text: str) -> None:
    radius = radius_from_text(text)
    assert radius is not None and float(radius) == 1e-7


class _Entry:
    text = ""

    def delete(self, _start: int, _end: str) -> None:
        self.text = ""

    def insert(self, _start: int, text: str) -> None:
        self.text = text


class _Box:
    def __init__(self, text: str) -> None:
        self.text = text

    def get(self, _start: str, _end: str) -> str:
        return self.text


def test_query_window_reruns_the_annotated_point() -> None:
    from gametool.gui_pack_query import _PackQueryWindow

    entry = _Entry()
    calls: list[str] = []
    window = SimpleNamespace(
        _keyword=entry,
        _switch_mode=calls.append,
        _run_clicked=lambda: calls.append("run"),
    )
    _PackQueryWindow._near_rerun_from_box(
        cast(_PackQueryWindow, cast(object, window)),
        _Box("单位 [n123] ×8 @(1e-7,-2e3) 距50"),
        "100",
    )
    assert entry.text == "1e-7 -2e3 100"
    assert calls == ["near", "run"]


def test_query_clipboard_uses_nested_selected_coordinates() -> None:
    from gametool.gui_pack_query import _PackQueryWindow

    entry = _Entry()
    raw = '{"selected":{"x":1e-7,"y":-2e3,"items":[{"code":"I123"}]},"all_units":[{"x":900,"y":800}]}'
    window = SimpleNamespace(_keyword=entry, clipboard_get=lambda: raw)
    _PackQueryWindow._coords_from_clipboard(
        cast(_PackQueryWindow, cast(object, window))
    )
    assert tuple(map(float, entry.text.split())) == (1e-7, -2000.0)


def test_probe_rerun_uses_annotation_instead_of_code_digits() -> None:
    from gametool.gui_live_probe import LiveProbeWindow

    calls: list[str] = []
    window = SimpleNamespace(
        _output=_Box("单位 [n123] ×8 @(1e-7,-2e3) 距50"), _query_callback=calls.append
    )
    LiveProbeWindow._near_rerun_selected(
        cast(LiveProbeWindow, cast(object, window)), "100"
    )
    assert calls == ["near 1e-7 -2e3 100"]


def test_guide_rerun_uses_shared_precise_coordinate_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gametool import gui_topbar

    calls: list[str] = []

    def opened(*_args: object, **kwargs: object) -> None:
        calls.append(str(kwargs["prefill"]))

    monkeypatch.setattr(gui_topbar, "open_pack_query_dialog", opened)
    app = SimpleNamespace(on_export_pack=lambda: None)
    gui_topbar._near_selected_coords(
        app, _Box("单位 [n123] ×8 @(1e-7,-2e3) 距50"), "100"
    )
    assert calls == ["near 1e-7 -2e3 100"]
