"""PrintWindow failure evidence must never become an empty-inventory conclusion."""

from __future__ import annotations

import ctypes
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def capture_apis(monkeypatch):
    from gametool import live_inventory as live

    pixels = bytes((0, 0, 255, 255, 255, 0, 0, 255))

    def client_rect(_window, rect):
        rect._obj.right = 2
        rect._obj.bottom = 1
        return 1

    def dibits(_dc, _bitmap, _start, lines, buffer, _info, _usage):
        ctypes.memmove(buffer, pixels, len(pixels))
        return lines

    user = SimpleNamespace(
        FindWindowW=Mock(return_value=101),
        IsIconic=Mock(return_value=False),
        GetClientRect=Mock(side_effect=client_rect),
        GetDC=Mock(return_value=201),
        ReleaseDC=Mock(return_value=1),
        PrintWindow=Mock(return_value=1),
    )
    user.windows = {101: {"pid": 42, "title": "Warcraft III"}}

    def enumerate_windows(callback, parameter):
        for hwnd in list(user.windows):
            if not callback(hwnd, parameter):
                return 0
        return 1

    def window_title(hwnd, buffer, _length):
        buffer.value = user.windows.get(hwnd, {}).get("title", "")
        return len(buffer.value)

    def window_process(hwnd, result):
        result._obj.value = user.windows.get(hwnd, {}).get("pid", 0)
        return 7 if result._obj.value else 0

    user.EnumWindows = Mock(side_effect=enumerate_windows)
    user.GetWindowTextLengthW = Mock(
        side_effect=lambda hwnd: len(user.windows.get(hwnd, {}).get("title", ""))
    )
    user.GetWindowTextW = Mock(side_effect=window_title)
    user.GetWindowThreadProcessId = Mock(side_effect=window_process)
    gdi = SimpleNamespace(
        CreateCompatibleDC=Mock(return_value=301),
        CreateCompatibleBitmap=Mock(return_value=401),
        SelectObject=Mock(return_value=501),
        GetDIBits=Mock(side_effect=dibits),
        DeleteObject=Mock(return_value=1),
        DeleteDC=Mock(return_value=1),
    )
    monkeypatch.setattr(live, "u32", user)
    monkeypatch.setattr(live, "g32", gdi)
    return live, user, gdi


@pytest.mark.parametrize(
    ("stage", "value", "message", "cleanup"),
    (
        ("EnumWindows", 0, "EnumWindows", (False, False, False)),
        ("IsIconic", True, "最小化", (False, False, False)),
        ("GetClientRect", 0, "GetClientRect", (False, False, False)),
        ("GetDC", 0, "GetDC", (False, False, False)),
        ("CreateCompatibleDC", 0, "CreateCompatibleDC", (False, False, True)),
        ("CreateCompatibleBitmap", 0, "CreateCompatibleBitmap", (False, True, True)),
        ("SelectObject", 0, "SelectObject", (True, True, True)),
        ("SelectObject", -1, "SelectObject", (True, True, True)),
        ("PrintWindow", 0, "PrintWindow", (True, True, True)),
        ("GetDIBits", 0, "GetDIBits", (True, True, True)),
    ),
)
def test_failed_capture_reports_its_stage_and_releases_acquired_objects(
    capture_apis, stage, value, message, cleanup
):
    live, user, gdi = capture_apis
    target = getattr(user if hasattr(user, stage) else gdi, stage)
    target.side_effect = None
    target.return_value = value

    with pytest.raises(RuntimeError, match=message):
        live.capture_window()

    delete_bitmap, delete_dc, release_dc = cleanup
    assert bool(gdi.DeleteObject.call_count) is delete_bitmap
    assert bool(gdi.DeleteDC.call_count) is delete_dc
    assert bool(user.ReleaseDC.call_count) is release_dc


@pytest.mark.parametrize("pixel", (bytes((0, 0, 0, 255)), bytes((127, 127, 127, 255))))
def test_uniform_capture_is_indeterminate_and_cleans_up(capture_apis, pixel):
    live, user, gdi = capture_apis

    def dibits(_dc, _bitmap, _start, lines, buffer, _info, _usage):
        ctypes.memmove(buffer, pixel * 2, 8)
        return lines

    gdi.GetDIBits.side_effect = dibits

    with pytest.raises(RuntimeError, match="(空帧|纯色).*(无法|不能)"):
        live.capture_window()

    gdi.DeleteObject.assert_called_once_with(401)
    gdi.DeleteDC.assert_called_once_with(301)
    user.ReleaseDC.assert_called_once_with(101, 201)


def test_partial_dibits_never_exposes_the_zero_filled_remainder(capture_apis):
    live, user, gdi = capture_apis

    def client_rect(_window, rect):
        rect._obj.right = 2
        rect._obj.bottom = 2
        return 1

    user.GetClientRect.side_effect = client_rect
    gdi.GetDIBits.side_effect = None
    gdi.GetDIBits.return_value = 1

    with pytest.raises(RuntimeError, match="GetDIBits"):
        live.capture_window()

    gdi.DeleteObject.assert_called_once_with(401)
    gdi.DeleteDC.assert_called_once_with(301)
    user.ReleaseDC.assert_called_once_with(101, 201)


def test_success_deselects_bitmap_before_read_and_preserves_rgb(capture_apis):
    live, user, gdi = capture_apis
    fill = gdi.GetDIBits.side_effect

    def dibits(*args):
        assert gdi.SelectObject.call_count == 2
        gdi.SelectObject.assert_called_with(301, 501)
        return fill(*args)

    gdi.GetDIBits.side_effect = dibits

    image, size = live.capture_window()

    assert size == (2, 1)
    assert image.mode == "RGB"
    assert image.getpixel((0, 0)) == (255, 0, 0)
    assert image.getpixel((1, 0)) == (0, 0, 255)
    user.PrintWindow.assert_called_once_with(101, 301, 3)
    gdi.DeleteObject.assert_called_once_with(401)
    gdi.DeleteDC.assert_called_once_with(301)
    user.ReleaseDC.assert_called_once_with(101, 201)


def test_api_exception_still_releases_all_acquired_objects(capture_apis):
    live, user, gdi = capture_apis
    user.PrintWindow.side_effect = RuntimeError("fixture capture exception")

    with pytest.raises(RuntimeError, match="fixture capture exception"):
        live.capture_window()

    gdi.SelectObject.assert_called_with(301, 501)
    gdi.DeleteObject.assert_called_once_with(401)
    gdi.DeleteDC.assert_called_once_with(301)
    user.ReleaseDC.assert_called_once_with(101, 201)
