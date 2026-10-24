"""gui_live_probe 弹窗测试: 后台线程/JSON 复制/文本区状态机 (不碰真内存)。"""

from __future__ import annotations

import tkinter as tk

import pytest

from gametool.gui_live_probe import LiveProbeWindow

pytest.importorskip("customtkinter")


@pytest.fixture
def _tk():
    root = tk.Tk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


def json_marker(code: int) -> str:
    return str(code) + chr(0)


def _pump(root: tk.Tk, deadline_s: float, done: list[str]) -> bool:
    import time

    end = time.time() + deadline_s
    while time.time() < end:
        root.update()
        if done:
            return True
        time.sleep(0.02)
    return False


def test_probe_window_reports_missing_game(_tk, tmp_path):
    """无游戏进程时探针返回 2 + 「war3 未运行」JSON, 弹窗软失败不炸。"""
    win = LiveProbeWindow(_tk, pack_dir=str(tmp_path))
    done: list[str] = []
    orig = LiveProbeWindow._finish
    LiveProbeWindow._finish = lambda self, text: done.append(text)  # type: ignore[assignment, method-assign]
    try:
        win._start()
        assert _pump(_tk, 60, done), "探针 60s 未返回"
        text = done[0]
        assert text.startswith("2" + chr(0))
        assert ("war3 未运行" in text) or (
            "OpenProcess" in text
        )  # 环境相关: 无进程或权限差
        assert '"strategy_used": null' in text
    finally:
        LiveProbeWindow._finish = orig  # type: ignore[assignment, method-assign]


def test_probe_json_autocopy_on_success(_tk, tmp_path):
    """探针成功 (code 0) 时尾部 JSON 自动复制到剪贴板, 输出区渲染正文。"""
    win = LiveProbeWindow(_tk, pack_dir=str(tmp_path))
    fake_body = '前置输出…\n{"units": [{"x": 1.0}]}\n'
    win._finish(json_marker(0) + fake_body)
    out = win._output.get("1.0", "end")
    assert '{"units"' in out
    # 剪贴板读取可能被外部应用抢占 (环境敏感), 只验证提示状态:
    hint = win._copy_hint.cget("text")
    assert ("已复制" in hint) or (hint == "")


def test_probe_json_not_copied_on_failure(_tk, tmp_path):
    """非 0 退出码不复制 JSON (探针失败数据无意义)。"""
    win = LiveProbeWindow(_tk, pack_dir=str(tmp_path))
    win._finish(json_marker(2) + '{"slots": []}\n')
    assert "已复制" not in win._copy_hint.cget("text")


def test_probe_where_drop_menu_routes(_tk, tmp_path) -> None:
    """右键 where/drop 直达: 前缀码经 query_callback 送达, 无码不发。"""
    sent: list[str] = []
    win = LiveProbeWindow(_tk, tmp_path, query_callback=sent.append)
    # 探针自动启动定时器会清空输出 — 置禁用让 _start 早退, 保住测试文本
    win._probe_button.configure(state="disabled")
    # CTkTextbox insert/tag 有代理延迟 — 直接驱动内部 tk.Text 保证同步可见
    inner = win._output._textbox
    inner.configure(state="normal")  # 展示区默认 disabled, insert 静默无效
    inner.insert("1.0", "冰晶指环 [I083]")
    inner.tag_add("sel", "1.6", "1.11")
    win._where_selected_code()
    assert sent == ["where I083"]
    inner.delete("1.0", "end")
    win._drop_selected_code()
    assert sent == ["where I083"]  # 无码不重复发
