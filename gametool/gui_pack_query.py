"""GUI 内直查当前资料包 — search/doc 子命令的图形入口 (后台线程, 结果弹窗)。"""

from __future__ import annotations

import os
import tkinter as tk
from typing import TYPE_CHECKING

import customtkinter as ctk

from .theme import BG, CARD, FONT, SUBTLE, TEXT, TITLE_FONT

if TYPE_CHECKING:
    from collections.abc import Callable


_LAST_KEYWORD = ""
_LAST_MODE = "doc"
_LAST_RESULT = ""
_HISTORY: list[tuple[str, str]] = []  # (模式, 关键词) 最近 10 条
_WINDOW_GEOMETRY: dict[str, str] = {}  # 窗口名 -> "WxH" (进程级)


def _memo_dir() -> str:
    try:
        from .cache_root import gamexray_cache_root  # noqa: PLC0415

        return str(gamexray_cache_root() / "gui-query-memo")
    except OSError:
        return ""


def _save_memo() -> None:
    """收藏+历史落盘 (fail-open): 重启程序不丢。"""
    import json  # noqa: PLC0415

    from pathlib import Path  # noqa: PLC0415

    base = _memo_dir()
    if not base:
        return
    try:
        base_path = Path(base)
        base_path.mkdir(parents=True, exist_ok=True)
        (base_path / "history.json").write_text(
            json.dumps(_HISTORY, ensure_ascii=False), encoding="utf-8"
        )
        (base_path / "pinned.json").write_text(
            json.dumps(_PINNED, ensure_ascii=False), encoding="utf-8"
        )
        (base_path / "geometry.json").write_text(
            json.dumps(_WINDOW_GEOMETRY, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass  # fail-open: 记忆失败不影响查询


def _load_memo() -> None:
    import json  # noqa: PLC0415

    from pathlib import Path  # noqa: PLC0415

    base = _memo_dir()
    if not base:
        return
    try:
        base_path = Path(base)
        history = json.loads((base_path / "history.json").read_text(encoding="utf-8"))
        _HISTORY[:] = [tuple(x) for x in history]
        pinned = json.loads((base_path / "pinned.json").read_text(encoding="utf-8"))
        _PINNED[:] = [tuple(x) for x in pinned]
        geo = json.loads((base_path / "geometry.json").read_text(encoding="utf-8"))
        _WINDOW_GEOMETRY.update(geo)
    except OSError, ValueError:
        pass  # fail-open: 缺文件/坏格式当空白


def _remember_geometry(win, name: str) -> None:
    """窗口关闭时把尺寸写进进程级记忆。"""
    _WINDOW_GEOMETRY[name] = win.geometry()


_PINNED: list[tuple[str, str]] = []  # (标题, 内容)


def open_pack_query_dialog(
    master,
    pack_dir_provider: Callable[[], str | None],
    ensure_pack: Callable[[], str | None],
    prefill: str = "",
    prefill_command: str = "",
) -> None:
    """打开包查询窗口。

    pack_dir_provider 返回最近一次导出的资料包目录 (无则 None);
    ensure_pack 在无包时回调 GUI 的导出动作 (先导出再查)。
    """
    pack_dir = pack_dir_provider()
    if not pack_dir or not os.path.isdir(pack_dir):
        ensure_pack()
        return
    _PackQueryWindow(master, pack_dir)


class _PackQueryWindow(ctk.CTkToplevel):
    def __init__(self, master, pack_dir: str) -> None:
        super().__init__(master)
        _load_memo()
        self.title("资料包查询")
        remembered = _WINDOW_GEOMETRY.get("pack-query")
        self.geometry(remembered or "760x560")
        self.bind("<Destroy>", lambda _e: _remember_geometry(self, "pack-query"))
        self.configure(fg_color=BG)
        self.transient(master)
        self.grab_set()
        self._pack_dir = pack_dir

        header = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        header.pack(fill="x", padx=14, pady=(14, 8))
        ctk.CTkLabel(
            header,
            text="资料包查询",
            font=(TITLE_FONT, 17, "bold"),
            text_color=TEXT,
        ).pack(anchor="w", padx=12, pady=(8, 0))
        ctk.CTkLabel(
            header,
            text=f"包: {pack_dir}",
            font=(FONT, 11),
            text_color=SUBTLE,
            anchor="w",
            justify="left",
        ).pack(fill="x", padx=12, pady=(0, 8))

        row = ctk.CTkFrame(self, fg_color="transparent")
        _HISTORY_VALUES = [f"{c} {k}".strip() for c, k in _HISTORY] or ["(无历史)"]
        self._history = ctk.CTkOptionMenu(
            row,
            values=_HISTORY_VALUES,
            width=120,
            command=self._on_history_pick,
        )
        self._history.set(_HISTORY_VALUES[0] if _HISTORY else "(历史)")
        self._history.pack(side="right")
        self._history_clear = ctk.CTkButton(
            row,
            text="清历史",
            width=60,
            height=26,
            font=(FONT, 11),
            fg_color="transparent",
            border_width=1,
            command=self._clear_history,
        )
        self._history_clear.pack(side="right", padx=(0, 4))
        row.pack(fill="x", padx=14)
        self._keyword = ctk.CTkEntry(
            row, placeholder_text="四码或名称…  Ctrl+1..8 切模式  回车查", width=340
        )
        self._keyword.insert(0, prefill or _LAST_KEYWORD)
        self._keyword.pack(side="left", padx=(0, 8))
        self._keyword.bind("<Return>", lambda _e: self._run(self._mode.get()))
        self._mode_commands = [
            "doc",
            "search",
            "list",
            "buffs",
            "export",
            "synth",
            "skills",
            "units",
        ]
        for _i, _cmd in enumerate(self._mode_commands, start=1):
            self.bind_all(
                f"<Control-Key-{_i}>",
                lambda _e, c=_cmd: self._switch_mode(c),
            )
        self._mode = ctk.CTkSegmentedButton(
            row,
            values=[
                "doc",
                "search",
                "list",
                "buffs",
                "export",
                "synth",
                "skills",
                "units",
            ],
            width=200,
        )
        self._mode.set(prefill_command or _LAST_MODE)
        self._mode.pack(side="left", padx=(0, 8))
        ctk.CTkButton(row, text="查询", width=84, command=self._run_clicked).pack(
            side="left"
        )

        pin_row = ctk.CTkFrame(self, fg_color="transparent")
        pin_row.pack(fill="x", padx=14, pady=(10, 0))
        ctk.CTkButton(
            pin_row,
            text="⊕ 收藏本次结果 (对比用)",
            width=150,
            height=24,
            font=(FONT, 11),
            command=self._pin_current,
        ).pack(side="left")
        ctk.CTkButton(
            pin_row,
            text="清空收藏",
            width=90,
            height=24,
            font=(FONT, 11),
            fg_color="transparent",
            border_width=1,
            command=self._clear_pinned,
        ).pack(side="left", padx=(6, 0))
        self._pinned_box = ctk.CTkTextbox(
            self, font=("Consolas", 11), wrap="none", height=120
        )
        if _PINNED:
            self._render_pinned()

        find_row = ctk.CTkFrame(self, fg_color="transparent")
        find_row.pack(fill="x", padx=14)
        self._find_var = ctk.StringVar()
        find_entry = ctk.CTkEntry(
            find_row,
            textvariable=self._find_var,
            placeholder_text="结果内搜索 (回车跳下一处)…",
            width=280,
            height=26,
        )
        find_entry.pack(side="left")
        self._find_state = {"start": "1.0"}

        def _find_next():
            needle = self._find_var.get().strip()
            if not needle:
                return
            start = self._find_state["start"]
            pos = self._output.search(needle, start, stopindex="end", nocase=True)
            if not pos:
                self._find_state["start"] = "1.0"
                pos = self._output.search(needle, "1.0", stopindex="end", nocase=True)
            if pos:
                self._output.see(pos)
                self._output.mark_set("insert", pos)
                end = f"{pos}+{len(needle)}c"
                self._output.tag_add("sel", pos, end)
                self._find_state["start"] = end

        find_entry.bind("<Return>", lambda _e: _find_next())
        self.bind_all("<Control-f>", lambda _e: find_entry.focus_set() or "break")
        self._output = ctk.CTkTextbox(self, font=("Consolas", 12), wrap="none")
        self._output.pack(fill="both", expand=True, padx=14, pady=10)
        if _LAST_RESULT:
            self._output.insert("1.0", _LAST_RESULT)
        pin_menu = tk.Menu(self, tearoff=0)
        pin_menu.add_command(label="复制收藏全部", command=self._copy_pinned)
        pin_menu.add_command(label="清空收藏", command=self._clear_pinned)
        pin_menu.add_command(
            label="导出收藏为 .md",
            command=lambda: self._export_md(self._pinned_box, "收藏对比"),
        )
        self._pinned_box.bind(
            "<Button-3>", lambda e: pin_menu.tk_popup(e.x_root, e.y_root)
        )

        if prefill:
            self.after(120, lambda: self._run(prefill_command or "doc"))
        elif not _LAST_RESULT:
            self.after(120, lambda: self._run("stats"))
            self.after(120, lambda: self._run("doc"))

        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="复制全部", command=self._copy_all)
        menu.add_command(
            label="导出为 .md", command=lambda: self._export_md(self._output)
        )
        self._output.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

    def _clear_history(self) -> None:
        _HISTORY.clear()
        _save_memo()
        self._history.set("(历史)")

    def _on_history_pick(self, value: str) -> None:
        for cmd, kw in _HISTORY:
            if f"{cmd} {kw}".strip() == value:
                self._mode.set(cmd)
                self._keyword.delete(0, "end")
                self._keyword.insert(0, kw)
                self._run(cmd)
                return

    def _switch_mode(self, command: str) -> None:
        self._mode.set(command)
        self._keyword.focus_set()

    def _run_clicked(self) -> None:
        self._run(self._mode.get())

    def _run(self, command: str) -> None:
        global _LAST_KEYWORD, _LAST_MODE
        _LAST_KEYWORD = self._keyword.get().strip()
        _LAST_MODE = command
        keyword = self._keyword.get().strip()
        if keyword or command in (
            "stats",
            "list",
            "buffs",
            "skills",
            "units",
            "heroes",
            "synth",
        ):
            entry = (command, keyword)
            if entry in _HISTORY:
                _HISTORY.remove(entry)
            _HISTORY.insert(0, entry)
            del _HISTORY[10:]
        _save_memo()
        if command in ("doc", "export", "search", "diff") and not keyword:
            self._output.delete("1.0", "end")
            self._find_state["start"] = "1.0"
            self._output.insert("1.0", f"{command} 需要四码或名称")
            return
        self._output.delete("1.0", "end")
        self._find_state["start"] = "1.0"
        self._output.insert("1.0", "查询中 …")
        self.configure(cursor="watch")
        self.after(50, lambda: self._run_blocking(command, keyword))

    def _run_blocking(self, command: str, keyword: str) -> None:
        try:
            from gametool.pack_query_cli import (
                PackQueryCliOptions,
                run_pack_query_cli,
            )
        except ImportError as exc:  # pragma: no cover
            self._finish(f"查询模块不可用: {exc}")
            return
        import contextlib
        import io

        options = PackQueryCliOptions(
            pack_dir=self._pack_dir, command=command, query=keyword, limit=0
        )
        buffer = io.StringIO()
        err_buffer = io.StringIO()
        try:
            with (
                contextlib.redirect_stdout(buffer),
                contextlib.redirect_stderr(err_buffer),
            ):
                run_pack_query_cli(options)
            output = buffer.getvalue() or "(无输出)"
            elapsed = err_buffer.getvalue().strip()
            if elapsed:
                output += f"\n──────────  {elapsed}  ──────────\n"
            self._finish(output)
        except SystemExit as exc:  # run_pack_query_cli 返回码路径不打异常
            output = buffer.getvalue() or f"(退出码 {exc.code})"
            self._finish(output)

    def _pin_current(self) -> None:
        text = self._output.get("1.0", "end").strip()
        if not text or text.startswith(("查询中", "doc 需要")):
            return
        title = f"{self._mode.get()} {self._keyword.get().strip()}"
        _PINNED.append((title, text))
        _save_memo()
        self._render_pinned()

    def _clear_pinned(self) -> None:
        _PINNED.clear()
        _save_memo()
        self._pinned_box.delete("1.0", "end")

    def _export_md(self, source_box, label: str = "查询结果") -> None:
        text = source_box.get("1.0", "end").strip()
        if not text:
            return
        from .archive_export import tmp_extract_dir  # noqa: PLC0415

        out_dir = tmp_extract_dir("pack-query-export")
        safe = "".join(ch if ch not in '\\/:*?"<>|' else "_" for ch in label)
        out_path = os.path.join(out_dir, safe + ".md")
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        self._output.insert("end", f"\n[已导出: {out_path}]\n")
        self.clipboard_clear()
        self.clipboard_append(out_path)

    def _copy_pinned(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._pinned_box.get("1.0", "end"))

    def _render_pinned(self) -> None:
        self._pinned_box.delete("1.0", "end")
        self._pinned_box.tag_config("del-mark", foreground="#d33", underline=True)
        for index, (title, text) in enumerate(_PINNED):
            mark = f"del-{index}"
            self._pinned_box.tag_delete(mark)
            self._pinned_box.insert("end", "[删] ", mark)
            self._pinned_box.tag_bind(
                mark,
                "<Button-1>",
                lambda _e, i=index: self._remove_pinned(i),
            )
            self._pinned_box.insert("end", f"==== 收藏: {title} ====" + "\n")
            self._pinned_box.insert("end", text + "\n\n")

    def _remove_pinned(self, index: int) -> None:
        if 0 <= index < len(_PINNED):
            del _PINNED[index]
            _save_memo()
            self._render_pinned()

    def _copy_all(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._output.get("1.0", "end"))

    def _finish(self, text: str) -> None:
        global _LAST_RESULT
        _LAST_RESULT = text
        self.configure(cursor="")
        self._output.delete("1.0", "end")
        self._find_state["start"] = "1.0"
        self._output.insert("1.0", text)
