"""Map-independent, offline hotkey inspection with main-thread-only Tk updates."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog
from typing import cast

import customtkinter as ctk

from .hotkey_config import diff_hotkey_configs, inspect_hotkey_config
from .hotkey_config_cli import (
    HotkeyReport,
    format_hotkey_result,
    hotkey_result_to_dict,
    write_hotkey_export,
)
from .hotkey_config_models import CONTRACT_BASIS
from .gui_pack_query import bind_geometry_memory
from .theme import BG, CARD, FONT, SUBTLE, TEXT, TITLE_FONT


_session_result: HotkeyReport | None = None
_session_mode = "检查详情"
_session_views: dict[str, str] = {}


@dataclass(frozen=True, slots=True)
class _CompletedJob:
    result: HotkeyReport | None
    note: str
    error: str
    elapsed: float
    views: dict[str, str]


def _memo_path() -> Path:
    from .cache_root import gamexray_cache_root

    return gamexray_cache_root() / "gui-query-memo" / "hotkey-inspector.json"


def _load_choices() -> dict[str, str]:
    try:
        values = json.loads(_memo_path().read_text(encoding="utf-8"))
        if isinstance(values, dict):
            return {
                key: values[key]
                for key in ("path", "compare", "profile")
                if isinstance(values.get(key), str)
            }
    except OSError, ValueError, UnicodeError:
        pass  # fail-open: remembered choices never block the offline dialog.
    return {}


def _save_choices(values: dict[str, str]) -> None:
    try:
        target = _memo_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        _ = target.write_text(json.dumps(values, ensure_ascii=True), encoding="utf-8")
    except OSError, ValueError, UnicodeError:
        pass  # fail-open: inspection remains available when GUI memory is unwritable.


def open_hotkey_config_dialog(parent: tk.Misc) -> None:
    """Open without a loaded map or any automatic configuration discovery."""
    _HotkeyConfigDialog(parent)


class _HotkeyConfigDialog(ctk.CTkToplevel):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.title("离线改键方案检查 — 选择配置文件")
        self.configure(fg_color=BG)
        self.transient(cast(tk.Tk | tk.Toplevel, parent.winfo_toplevel()))
        bind_geometry_memory(self, "hotkey-config-inspector", "1040x780")
        self.grab_set()
        self._closed = False
        self._destroy_started = False
        self._busy = False
        self._generation = 0
        self._poll_id: str | None = None
        self._result: HotkeyReport | None = None
        self._views: dict[str, str] = dict(_session_views)
        self._result_fresh = False
        self._search_start = "1.0"
        self._sections: list[tuple[str, str]] = []
        self._jump_buttons: list[ctk.CTkButton] = []
        self._active_section = -1
        choices = _load_choices()
        self._path_var = tk.StringVar(value=choices.get("path", ""))
        self._compare_var = tk.StringVar(value=choices.get("compare", ""))
        self._profile_var = tk.StringVar(value=choices.get("profile", ""))

        header = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        header.pack(fill="x", padx=14, pady=(14, 8))
        ctk.CTkLabel(
            header,
            text="离线改键方案检查与比较",
            font=(TITLE_FONT, 18, "bold"),
            text_color=TEXT,
        ).pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            header,
            text=CONTRACT_BASIS,
            font=(FONT, 11),
            text_color=SUBTLE,
            wraplength=960,
            justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 10))
        self._path_entry = self._file_row(
            "配置文件", self._path_var, lambda: self._choose(self._path_var)
        )
        self._compare_entry = self._file_row(
            "旧文件（可选）", self._compare_var, lambda: self._choose(self._compare_var)
        )
        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(fill="x", padx=14, pady=(4, 6))
        self._profile_entry = ctk.CTkEntry(
            controls,
            textvariable=self._profile_var,
            placeholder_text="单文件检查：唯一方案名，留空检查全部",
            width=300,
        )
        self._profile_entry.pack(side="left", padx=(0, 8))
        self._run_button = ctk.CTkButton(
            controls, text="检查 / 比较 (Ctrl+R)", width=160, command=self._run
        )
        self._run_button.pack(side="left", padx=(0, 8))
        self._mode = ctk.CTkOptionMenu(
            controls,
            values=["检查详情", "完整 JSON"],
            command=self._switch_mode,
            width=120,
        )
        self._mode.set(_session_mode)
        self._mode.pack(side="left", padx=(0, 8))
        self._export_button = ctk.CTkButton(
            controls,
            text="导出完整报告",
            width=120,
            state="disabled",
            command=self._export,
        )
        self._export_button.pack(side="right")
        self._status = ctk.CTkLabel(
            self,
            text="选择配置文件后检查；选择旧文件后比较全部原方案。",
            text_color=SUBTLE,
            font=(FONT, 11),
            anchor="w",
        )
        self._status.pack(fill="x", padx=14, pady=(0, 4))
        self._jump_bar = ctk.CTkScrollableFrame(
            self, orientation="horizontal", height=34, fg_color="transparent"
        )
        self._jump_bar.pack(fill="x", padx=10)
        search_row = ctk.CTkFrame(self, fg_color="transparent")
        search_row.pack(fill="x", padx=14, pady=(4, 6))
        self._search = ctk.CTkEntry(
            search_row, placeholder_text="Ctrl+F 内搜；回车跳下一处并循环", height=28
        )
        self._search.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            search_row, text="下一处", width=70, height=28, command=self._find_next
        ).pack(side="right")
        self._output = ctk.CTkTextbox(self, wrap="none", font=("Consolas", 12))
        self._output.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self._output.tag_config("hit", background="#8a6d00", foreground="white")
        self._output.tag_config(
            "section-current", background="#244b43", foreground="white"
        )
        self._build_context_menu()
        self._search.bind("<Return>", lambda _event: self._find_next())
        for entry in (self._path_entry, self._compare_entry, self._profile_entry):
            entry.bind("<Return>", lambda _event: self._run())
        for key in ("f", "F"):
            self.bind(f"<Control-{key}>", lambda _event: self._focus_search())
        for key in ("a", "A"):
            self.bind(f"<Control-{key}>", self._select_all)
        for key in ("r", "R"):
            self.bind(f"<Control-{key}>", lambda _event: self._run() or "break")
        self.bind("<Escape>", lambda _event: self._close())
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Destroy>", self._on_destroy, add="+")
        for variable in (self._path_var, self._compare_var, self._profile_var):
            variable.trace_add("write", self._invalidate)
        if _session_result is not None:
            self._result = _session_result
            self._render()
            self._status.configure(
                text="显示本进程上次检查快照；重新检查所选文件后可导出。"
            )
        else:
            self._set_text(
                "选择配置文件并点击检查。\n\n== 使用方法 ==\n单文件：检查完整原声明、静态兼容投影与冲突诊断。\n比较：旧文件 → 配置文件，按唯一方案名与绑定ID显示差异。\n\n没有配置文件时，可先在原工具中保存方案，再明确选择该文件。"
            )

    def _file_row(
        self, label: str, variable: tk.StringVar, choose: Callable[[], None]
    ) -> ctk.CTkEntry:
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=3)
        ctk.CTkLabel(row, text=label, width=110, anchor="w", font=(FONT, 12)).pack(
            side="left"
        )
        entry = ctk.CTkEntry(row, textvariable=variable)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(row, text="打开文件", width=90, command=choose).pack(side="right")
        return entry

    def _choose(self, variable: tk.StringVar) -> None:
        selected = filedialog.askopenfilename(
            parent=self,
            title="选择离线改键配置 JSON",
            filetypes=[("JSON 配置", "*.json"), ("全部文件", "*.*")],
        )
        if selected:
            variable.set(selected)

    def _choices(self) -> dict[str, str]:
        return {
            "path": self._path_var.get(),
            "compare": self._compare_var.get(),
            "profile": self._profile_var.get(),
        }

    def _invalidate(self, *_args: object) -> None:
        self._generation += 1
        self._result_fresh = False
        self._export_button.configure(state="disabled")
        self._status.configure(
            text="文件或筛选已改变；请重新检查。"
            if not self._busy
            else "选择已改变；当前后台结果将丢弃，请完成后重新检查。"
        )

    def _run(self) -> None:
        if self._closed or self._busy:
            return
        path = self._path_var.get().strip()
        compare = self._compare_var.get().strip()
        profile = self._profile_var.get() or None
        if not path:
            self._status.configure(
                text="请用“打开文件”选择一个配置 JSON，或在配置文件栏输入路径。"
            )
            self._path_entry.focus_set()
            return
        _save_choices(self._choices())
        self.title("离线改键方案检查 — " + Path(path).name)
        self._result_fresh = False
        self._export_button.configure(state="disabled")
        self._set_text("检查中…\n完整读取与来源复验可能需要一些时间。")

        def work() -> tuple[HotkeyReport | None, str]:
            result = (
                diff_hotkey_configs(compare, path)
                if compare
                else inspect_hotkey_config(path, profile=profile)
            )
            return result, (
                "比较全部原声明方案" if compare else "检查完成"
            ) + f"；退出码 {result.exit_code}。"

        self._start_worker(work, "后台比较中…" if compare else "后台检查中…")

    def _start_worker(
        self, work: Callable[[], tuple[HotkeyReport | None, str]], message: str
    ) -> None:
        self._busy = True
        self._run_button.configure(state="disabled")
        self._export_button.configure(state="disabled")
        self._status.configure(text=message)
        self._generation += 1
        generation = self._generation
        done: queue.SimpleQueue[_CompletedJob] = queue.SimpleQueue()

        def worker() -> None:
            started = time.monotonic()
            try:
                result, note = work()
                views = (
                    {
                        "检查详情": format_hotkey_result(result),
                        "完整 JSON": json.dumps(
                            hotkey_result_to_dict(result), ensure_ascii=True, indent=2
                        )
                        + "\n",
                    }
                    if result is not None
                    else {}
                )
                done.put(
                    _CompletedJob(result, note, "", time.monotonic() - started, views)
                )
            except Exception as exc:  # BROAD_EXCEPT_OK - deliver owned offline job failures to the Tk polling path.
                done.put(
                    _CompletedJob(
                        None,
                        "",
                        f"{type(exc).__name__}: {exc}",
                        time.monotonic() - started,
                        {},
                    )
                )

        threading.Thread(target=worker, daemon=True).start()

        def poll() -> None:
            self._poll_id = None
            if self._closed:
                return
            try:
                completion = done.get_nowait()
            except queue.Empty:
                self._poll_id = self.after(80, poll)
                return
            self._busy = False
            self._run_button.configure(state="normal")
            if generation != self._generation:
                self._status.configure(text="已丢弃过期结果；请重新检查当前选择。")
                return
            if completion.error:
                self._status.configure(
                    text=f"操作失败（{completion.elapsed:.3f}s）：{completion.error}。请核对路径后重新检查。"
                )
                return
            if completion.result is not None:
                global _session_result, _session_views
                self._result = completion.result
                _session_result = completion.result
                self._views = completion.views
                _session_views = completion.views
                self._result_fresh = True
                self._render()
            self._export_button.configure(
                state="normal" if self._result_fresh else "disabled"
            )
            self._status.configure(
                text=f"{completion.note} —— 耗时 {completion.elapsed:.3f}s ——"
            )

        self._poll_id = self.after(80, poll)

    def _switch_mode(self, mode: str) -> None:
        global _session_mode
        _session_mode = mode
        self._mode.set(mode)
        self._render()

    def _render(self) -> None:
        if self._result is None:
            return
        text = self._views.get(self._mode.get(), "")
        if not text:
            return
        self._set_text(text)

    def _set_text(self, text: str) -> None:
        self._output.configure(state="normal")
        self._output.delete("1.0", "end")
        self._output.insert("1.0", text)
        self._output.configure(state="disabled")
        self._output.see("1.0")
        self._search_start = "1.0"
        self._output.tag_remove("hit", "1.0", "end")
        self._sections = [
            (line.strip("= "), f"{index}.0")
            for index, line in enumerate(text.splitlines(), 1)
            if line.startswith("== ") and line.endswith(" ==")
        ]
        if not self._sections:
            self._sections = [("报告顶部", "1.0")]
        for button in self._jump_buttons:
            button.destroy()
        self._jump_buttons.clear()
        for index, (label, _position) in enumerate(self._sections):
            button = ctk.CTkButton(
                self._jump_bar,
                text=label,
                width=max(80, len(label) * 14),
                height=26,
                fg_color="transparent",
                border_width=1,
                command=lambda i=index: self._jump(i),
            )
            button.pack(side="left", padx=3)
            self._jump_buttons.append(button)
        self._active_section = -1
        self._mark_section(0)

    def _mark_section(self, index: int) -> None:
        if index == self._active_section:
            return
        self._active_section = index
        self._output.tag_remove("section-current", "1.0", "end")
        for i, button in enumerate(self._jump_buttons):
            button.configure(fg_color="#245b4b" if i == index else "transparent")
        if self._sections:
            position = self._sections[index][1]
            self._output.tag_add("section-current", position, position + " lineend")

    def _jump(self, index: int) -> None:
        self._output.see(self._sections[index][1])
        self._mark_section(index)

    def _focus_search(self) -> str:
        self._search.focus_set()
        return "break"

    def _find_next(self) -> None:
        needle = self._search.get()
        self._output.tag_remove("hit", "1.0", "end")
        if not needle:
            self._search_start = "1.0"
            return
        position = self._output.search(
            needle, self._search_start, stopindex="end", nocase=True
        )
        if not position:
            position = self._output.search(needle, "1.0", stopindex="end", nocase=True)
        if not position:
            self._status.configure(
                text="报告内未找到该文字；可改搜 binding_id、方案名或诊断代码。"
            )
            self._search_start = "1.0"
            return
        end = f"{position}+{len(needle)}c"
        self._output.tag_add("hit", position, end)
        self._output.see(position)
        self._search_start = end
        line = int(position.split(".")[0])
        section = max(
            (
                i
                for i, (_, start) in enumerate(self._sections)
                if int(start.split(".")[0]) <= line
            ),
            default=0,
        )
        self._mark_section(section)

    def _select_all(self, _event=None) -> str | None:
        if self.focus_get() in {
            entry._entry
            for entry in (
                self._path_entry,
                self._compare_entry,
                self._profile_entry,
                self._search,
            )
        }:
            return None
        self._output.tag_add("sel", "1.0", "end-1c")
        self._output.mark_set("insert", "end-1c")
        self._output.focus_set()
        return "break"

    def _copy(self, selected: bool) -> None:
        if selected:
            try:
                text = self._output.get("sel.first", "sel.last")
            except tk.TclError:
                return
        else:
            text = self._output.get("1.0", "end-1c")
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)

    def _build_context_menu(self) -> None:
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="复制选中", command=lambda: self._copy(True))
        menu.add_command(label="复制全部", command=lambda: self._copy(False))
        menu.add_command(label="导出完整报告 (.md / .json)", command=self._export)
        jump = tk.Menu(menu, tearoff=0)
        menu.add_cascade(label="段落跳转", menu=jump)

        def popup(event) -> None:
            jump.delete(0, "end")
            for index, (label, _position) in enumerate(self._sections):
                jump.add_command(label=label, command=lambda i=index: self._jump(i))
            menu.tk_popup(event.x_root, event.y_root)

        self._output.bind("<Button-3>", popup)

    def _export(self) -> None:
        if self._closed or self._busy or self._result is None or not self._result_fresh:
            self._status.configure(text="请先检查当前选择，再导出完整报告。")
            return
        selected = filedialog.asksaveasfilename(
            parent=self,
            title="导出完整报告到新文件（不会覆盖）",
            defaultextension=".md",
            filetypes=[("完整 Markdown 报告", "*.md"), ("完整 JSON 证据", "*.json")],
        )
        if not selected:
            return
        result = self._result

        def work() -> tuple[HotkeyReport | None, str]:
            write_hotkey_export(selected, result)
            return None, f"完整报告已导出: {selected}"

        self._start_worker(work, "正在复验来源并导出完整报告…")

    def _on_destroy(self, event) -> None:
        if event.widget is self:
            _save_choices(self._choices())
            self._closed = True
            self._generation += 1
            if self._poll_id is not None:
                try:
                    self.after_cancel(self._poll_id)
                except tk.TclError:
                    pass  # The root may already have removed the owned callback.
                self._poll_id = None

    def _close(self) -> None:
        if self._closed:
            return
        _save_choices(self._choices())
        self._closed = True
        self._generation += 1
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
            self._poll_id = None
        self.destroy()

    def destroy(self) -> None:
        """Retire this window's complete Tcl callback tree before Tk teardown."""
        if self._destroy_started:
            return
        self._destroy_started = True
        from .gui_tk_callbacks import cancel_widget_callbacks

        cancel_widget_callbacks(self)
        super().destroy()
