"""Offline War3Tools configuration viewer with guarded, Tk-safe delivery."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from pathlib import Path
from time import monotonic
import tkinter as tk
from tkinter import TclError, filedialog, messagebox

import customtkinter as ctk

from .cache_root import gamexray_cache_root
from .gui_pack_query import bind_geometry_memory
from .gui_tk_callbacks import cancel_widget_callbacks
from .gui_worker_host import GuiWorkerHostMixin
from .gui_worker_registry import GuiWorkerTicket
from .save_text_encoding import SAVE_TEXT_ENCODINGS, normalize_save_text_encoding
from .theme import BG, CARD, FONT, MONO_FONT, SUBTLE, TITLE_FONT
from .war3tools_config import inspect_war3tools_config
from .war3tools_config_report import (
    War3ToolsSelection,
    format_war3tools_report,
    revalidate_war3tools_selection,
    select_war3tools_report,
    war3tools_report_to_dict,
    write_war3tools_export,
)


@dataclass(frozen=True, slots=True)
class _ReportView:
    text: str
    sections: tuple[tuple[str, str], ...]


_session_selection: War3ToolsSelection | None = None
_session_views: dict[str, _ReportView] = {}


def _memo_path() -> Path:
    return gamexray_cache_root() / "gui-query-memo" / "war3tools-config.json"


def _load_memo() -> dict[str, str]:
    try:
        value = json.loads(_memo_path().read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return {
                key: value[key]
                for key in ("source", "query", "encoding", "view")
                if isinstance(value.get(key), str)
            }
    except OSError, ValueError, UnicodeError:
        pass  # Optional GUI memory must never prevent an explicit inspection.
    return {}


def _save_memo(values: dict[str, str]) -> None:
    try:
        path = _memo_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(values, ensure_ascii=True), encoding="utf-8")
    except OSError, ValueError, UnicodeError:
        pass  # Preference failures leave the current user choices intact.


def _report_view(text: str) -> _ReportView:
    sections: list[tuple[str, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith("## "):
            sections.append((line[3:].strip(), f"{number}.0"))
        elif line.startswith("== ") and line.endswith(" =="):
            sections.append((line[3:-3].strip(), f"{number}.0"))
    return _ReportView(text, tuple(sections) or (("报告顶部", "1.0"),))


def _build_views(selection: War3ToolsSelection) -> dict[str, _ReportView]:
    return {
        "配置与诊断": _report_view(format_war3tools_report(selection)),
        "完整 JSON": _report_view(
            json.dumps(war3tools_report_to_dict(selection), ensure_ascii=True, indent=2)
            + "\n"
        ),
    }


def _prepare_report(
    selection: War3ToolsSelection,
) -> tuple[War3ToolsSelection, dict[str, _ReportView]]:
    """Reprove after full rendering, retaining changed-source snapshot evidence."""
    views = _build_views(selection)
    checked = revalidate_war3tools_selection(selection)
    if checked != selection:
        views = _build_views(checked)
    return checked, views


class War3ToolsConfigDialog(ctk.CTkToplevel, GuiWorkerHostMixin):
    def __init__(self, parent, *, initial_path: str = "") -> None:
        super().__init__(parent)
        self.title("War3Tools 配置总览（离线）")
        self.configure(fg_color=BG)
        self.minsize(960, 600)
        bind_geometry_memory(self, "war3tools-config", "1180x800")
        self._closed = False
        self._generation = 0
        self._text_epoch = 0
        self._scheduled: set[str] = set()
        self._selection: War3ToolsSelection | None = None
        self._views: dict[str, _ReportView] = {}
        self._source_current = False
        self._fresh = False
        self._detail_text = ""
        self._find_start = "1.0"
        self._find_keyword = ""
        self._sections: tuple[tuple[str, str], ...] = ()
        self._jump_buttons: list[ctk.CTkButton] = []
        self._init_gui_worker_host()
        memo = _load_memo()
        self.source_var = tk.StringVar(value=initial_path or memo.get("source", ""))
        self.query_var = tk.StringVar(value=memo.get("query", ""))
        try:
            encoding = normalize_save_text_encoding(memo.get("encoding", "auto"))
        except ValueError:
            encoding = "auto"
        self.encoding_var = tk.StringVar(value=encoding)
        self.find_var = tk.StringVar()
        mode = memo.get("view", "配置与诊断")
        self.view_var = tk.StringVar(
            value=mode if mode in {"配置与诊断", "完整 JSON"} else "配置与诊断"
        )
        self._build_controls()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.bind("<Escape>", lambda _event: self.destroy())
        for key in ("f", "F"):
            self.bind(f"<Control-{key}>", self._focus_search)
        for key in ("a", "A"):
            self.bind(f"<Control-{key}>", self._select_all)
        for key in ("r", "R"):
            self.bind(f"<Control-{key}>", lambda _event: self.refresh() or "break")
        self.source_var.trace_add("write", self._invalidate_source)
        self.encoding_var.trace_add("write", self._invalidate_source)
        self.query_var.trace_add("write", self._invalidate_query)
        self.transient(parent)
        self._schedule(self._activate)
        if initial_path:
            self._schedule(self.refresh)
        elif _session_selection is not None:
            self._receive_selection(
                _session_selection,
                self._generation,
                views=_session_views,
                fresh=False,
            )
            self.status.configure(
                text="显示本进程上次检查快照；点击「读取 / 刷新」后可筛选和导出。"
            )
        else:
            self._show_view(
                _report_view(
                    "# War3Tools 配置总览\n\n选择 War3Tools 目录或单个 INI 文件，然后点击「读取 / 刷新」。\n\n"
                    "## 继续查证\n可按字段、原值或功能类别筛选；留空展示全部声明。"
                    "完整诊断、来源和原始证据随报告保留。请选择实际保存的配置目录或文件。"
                )
            )

    def _activate(self) -> None:
        self.grab_set()
        self.focus_set()

    def _build_controls(self) -> None:
        ctk.CTkLabel(
            self, text="War3Tools 配置总览", font=(TITLE_FONT, 21, "bold")
        ).pack(anchor="w", padx=14, pady=(12, 3))
        ctk.CTkLabel(
            self,
            text="离线查看所选配置的全部声明、按键冲突和来源证据；游戏中的实际效果需另行核实。",
            font=(FONT, 11),
            text_color=SUBTLE,
        ).pack(anchor="w", padx=14, pady=(0, 6))
        source = ctk.CTkFrame(self, fg_color=CARD)
        source.pack(fill="x", padx=12, pady=3)
        ctk.CTkLabel(source, text="目录 / INI", width=85).pack(side="left", padx=4)
        self.source_entry = ctk.CTkEntry(source, textvariable=self.source_var)
        self.source_entry.pack(side="left", fill="x", expand=True, padx=4, pady=5)
        for label, command in (
            ("选目录", self._pick_directory),
            ("选 INI", self._pick_file),
        ):
            ctk.CTkButton(source, text=label, width=75, command=command).pack(
                side="left", padx=3
            )
        self.refresh_button = ctk.CTkButton(
            source, text="读取 / 刷新", width=110, command=self.refresh
        )
        self.refresh_button.pack(side="left", padx=(3, 7))
        self.source_entry.bind("<Return>", lambda _event: self.refresh())
        controls = ctk.CTkFrame(self, fg_color=CARD)
        controls.pack(fill="x", padx=12, pady=3)
        ctk.CTkOptionMenu(
            controls,
            variable=self.encoding_var,
            values=list(SAVE_TEXT_ENCODINGS),
            width=125,
        ).pack(side="left", padx=4, pady=5)
        self.query_entry = ctk.CTkEntry(
            controls,
            textvariable=self.query_var,
            placeholder_text="字段 / 原值 / 功能类别；留空全部，支持 &&、||",
        )
        self.query_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.query_entry.bind("<Return>", lambda _event: self.search())
        ctk.CTkButton(controls, text="筛选", width=65, command=self.search).pack(
            side="left", padx=3
        )
        ctk.CTkButton(
            controls, text="全部设置", width=85, command=self._clear_query
        ).pack(side="left", padx=3)
        ctk.CTkOptionMenu(
            controls,
            variable=self.view_var,
            values=["配置与诊断", "完整 JSON"],
            command=self._switch_view,
            width=125,
        ).pack(side="left", padx=4)
        exports = ctk.CTkFrame(self, fg_color="transparent")
        exports.pack(fill="x", padx=12, pady=3)
        self.export_buttons: dict[str, ctk.CTkButton] = {}
        for format in ("json", "md", "tsv"):
            button = ctk.CTkButton(
                exports,
                text="导出 " + format.upper(),
                width=100,
                state="disabled",
                command=lambda selected=format: self.export_report(selected),
            )
            button.pack(side="right", padx=3)
            self.export_buttons[format] = button
        self.status = ctk.CTkLabel(
            self,
            text="请选择明确的 War3Tools 配置目录或 INI 文件。",
            anchor="w",
            font=(FONT, 11),
            text_color=SUBTLE,
        )
        self.status.pack(fill="x", padx=14, pady=3)
        self.jump_bar = ctk.CTkScrollableFrame(
            self, orientation="horizontal", height=34, fg_color="transparent"
        )
        self.jump_bar.pack(fill="x", padx=10)
        search = ctk.CTkFrame(self, fg_color="transparent")
        search.pack(fill="x", padx=12, pady=3)
        self.find_entry = ctk.CTkEntry(
            search,
            textvariable=self.find_var,
            placeholder_text="Ctrl+F 内搜；回车找下一处并循环",
        )
        self.find_entry.pack(side="left", fill="x", expand=True, padx=3)
        self.find_entry.bind("<Return>", lambda _event: self._find_next())
        ctk.CTkButton(search, text="下一处", width=80, command=self._find_next).pack(
            side="left", padx=3
        )
        self.details = ctk.CTkTextbox(self, font=(MONO_FONT, 12), wrap="none")
        self.details.pack(fill="both", expand=True, padx=12, pady=(3, 12))
        self.details.tag_config("search-hit", background="#8a6d00", foreground="white")
        self.details.tag_config(
            "section-current", background="#244b43", foreground="white"
        )
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="复制选中", command=self._copy_selected)
        menu.add_command(
            label="复制全部", command=lambda: self._copy(self._detail_text)
        )
        menu.add_command(
            label="导出完整报告 (.json / .md / .tsv)", command=self.export_report
        )
        self.details.bind(
            "<Button-3>", lambda event: menu.tk_popup(event.x_root, event.y_root)
        )

    def _schedule(self, callback: Callable[[], None]) -> None:
        def deliver() -> None:
            self._scheduled.discard(identifier)
            if not self._closed:
                callback()

        identifier = self.after(1, deliver)
        self._scheduled.add(identifier)

    def _memo(self) -> None:
        _save_memo(
            {
                "source": self.source_var.get(),
                "query": self.query_var.get(),
                "encoding": self.encoding_var.get(),
                "view": self.view_var.get(),
            }
        )

    def _set_export_state(self, enabled: bool) -> None:
        for button in self.export_buttons.values():
            button.configure(state="normal" if enabled else "disabled")

    def _invalidate_source(self, *_args) -> None:
        self._generation += 1
        self._fresh = self._source_current = False
        for group in ("war3tools-read", "war3tools-query", "war3tools-export"):
            self._cancel_gui_worker_group(group)
        self._set_export_state(False)
        self.status.configure(
            text="来源或编码已改变；请点击「读取 / 刷新」，当前内容为上次快照。"
        )

    def _invalidate_query(self, *_args) -> None:
        self._generation += 1
        self._fresh = False
        self._cancel_gui_worker_group("war3tools-query")
        self._cancel_gui_worker_group("war3tools-export")
        self._set_export_state(False)
        self.status.configure(
            text="筛选条件已改变；按回车或点击「筛选」查看当前条件的完整结果。"
        )

    def _pick_directory(self) -> None:
        if path := filedialog.askdirectory(
            parent=self, title="选择 War3Tools 配置目录"
        ):
            self.source_var.set(path)
            self.refresh()

    def _pick_file(self) -> None:
        if path := filedialog.askopenfilename(
            parent=self,
            title="选择 War3Tools 配置 INI",
            filetypes=[("INI 配置", "*.ini"), ("所有文件", "*.*")],
        ):
            self.source_var.set(path)
            self.refresh()

    def refresh(self) -> None:
        if self._closed:
            return
        source = self.source_var.get().strip()
        if not source:
            self.status.configure(
                text="请选择配置目录或单个 INI 文件，再点击「读取 / 刷新」。"
            )
            self.source_entry.focus_set()
            return
        encoding, query = self.encoding_var.get(), self.query_var.get()
        self._memo()
        self._generation += 1
        generation = self._generation
        self._fresh = self._source_current = False
        self._set_export_state(False)
        self._cancel_gui_worker_group("war3tools-query")
        self._cancel_gui_worker_group("war3tools-export")
        self.title(f"War3Tools 配置总览 · {Path(source).name}")
        self.status.configure(text="正在读取全部配置声明并复验来源 …")

        def work(ticket: GuiWorkerTicket) -> None:
            started = monotonic()
            try:
                inspection = inspect_war3tools_config(source, text_encoding=encoding)
                selection = select_war3tools_report(inspection, query)
                selection, views = _prepare_report(selection)
                elapsed = monotonic() - started
                if not ticket.cancellation.is_set():
                    self._post_gui_worker(
                        ticket,
                        lambda: self._receive_selection(
                            selection, generation, views=views, elapsed=elapsed
                        ),
                    )
            except Exception as exc:  # BROAD_EXCEPT_OK - report owned background failures without crossing into Tk.
                message = f"读取失败：{type(exc).__name__}: {exc}；请核对目录、文件和编码后重试。"
                self._post_gui_worker(
                    ticket, lambda: self._receive_error(generation, message)
                )

        self._start_gui_worker("war3tools-read", work, replace=True)

    def search(self) -> None:
        if self._closed:
            return
        if self._selection is None or not self._source_current:
            self.status.configure(text="请先读取当前配置来源，再按字段或功能类别筛选。")
            return
        inspection, query = self._selection.inspection, self.query_var.get()
        self._memo()
        self._generation += 1
        generation = self._generation
        self._fresh = False
        self._set_export_state(False)
        self.status.configure(text="正在筛选完整声明并复验来源 …")

        def work(ticket: GuiWorkerTicket) -> None:
            started = monotonic()
            try:
                selection = select_war3tools_report(inspection, query)
                selection, views = _prepare_report(selection)
                elapsed = monotonic() - started
                if not ticket.cancellation.is_set():
                    self._post_gui_worker(
                        ticket,
                        lambda: self._receive_selection(
                            selection, generation, views=views, elapsed=elapsed
                        ),
                    )
            except Exception as exc:  # BROAD_EXCEPT_OK - preserve the prior evidence and surface owned filtering failures.
                message = f"筛选失败：{type(exc).__name__}: {exc}；请检查查询表达式，或清空筛选后重试。"
                self._post_gui_worker(
                    ticket, lambda: self._receive_error(generation, message)
                )

        self._start_gui_worker("war3tools-query", work, replace=True)

    def _clear_query(self) -> None:
        self.query_var.set("")
        self.search()

    def _receive_error(self, generation: int, message: str) -> None:
        if self._closed or generation != self._generation:
            return
        self._fresh = False
        self._set_export_state(False)
        self.status.configure(text=message)

    def _receive_selection(
        self,
        selection: War3ToolsSelection,
        generation: int,
        *,
        views: dict[str, _ReportView],
        elapsed: float = 0,
        fresh: bool = True,
    ) -> None:
        if self._closed or generation != self._generation:
            return
        global _session_selection, _session_views
        _session_selection, _session_views = selection, views
        self._selection, self._views = selection, views
        inspection = selection.inspection
        self._fresh = self._source_current = (
            fresh and inspection.stable and not inspection.input_error
        )
        self._set_export_state(self._fresh)
        self.title(f"War3Tools 配置总览 · {Path(inspection.path).name}")
        self.status.configure(
            text=f"{inspection.files_total} 份配置 · {inspection.settings_total} 项声明 · "
            f"退出码 {inspection.exit_code} · 来源{'已复验' if self._fresh else '需重新读取'} "
            f"—— 耗时 {elapsed:.3f} 秒 —— 完整诊断与原始证据保留"
        )
        self._switch_view(self.view_var.get())

    def _switch_view(self, mode: str) -> None:
        if mode in self._views:
            self.view_var.set(mode)
            self._show_view(self._views[mode])
        self._memo()

    def _show_view(self, view: _ReportView) -> None:
        self._text_epoch += 1
        epoch = self._text_epoch
        self._detail_text = view.text
        self._find_start, self._find_keyword = "1.0", ""
        self._sections = view.sections
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.configure(state="disabled")
        for button in self._jump_buttons:
            button.destroy()
        self._jump_buttons.clear()
        for index, (label, _position) in enumerate(view.sections):
            button = ctk.CTkButton(
                self.jump_bar,
                text=label,
                width=max(80, len(label) * 14),
                height=26,
                fg_color="transparent",
                border_width=1,
                command=lambda i=index: self._jump(i),
            )
            button.pack(side="left", padx=3)
            self._jump_buttons.append(button)
        offset = 0

        def batch() -> None:
            nonlocal offset
            if epoch != self._text_epoch:
                return
            self.details.configure(state="normal")
            self.details.insert("end", view.text[offset : offset + 32768])
            self.details.configure(state="disabled")
            offset += 32768
            if offset < len(view.text):
                self._schedule(batch)
            else:
                self.details.see("1.0")
                self._jump(0)

        self._schedule(batch)

    def _mark_section(self, index: int) -> None:
        self.details.tag_remove("section-current", "1.0", "end")
        for i, button in enumerate(self._jump_buttons):
            button.configure(fg_color="#245b4b" if i == index else "transparent")
        if self._sections:
            position = self._sections[index][1]
            self.details.tag_add("section-current", position, position + " lineend")

    def _jump(self, index: int) -> None:
        if self._sections:
            self.details.see(self._sections[index][1])
            self._mark_section(index)

    def _focus_search(self, _event=None) -> str:
        self.find_entry.focus_set()
        return "break"

    def _find_next(self) -> None:
        keyword = self.find_var.get()
        self.details.tag_remove("search-hit", "1.0", "end")
        if keyword != self._find_keyword:
            self._find_keyword, self._find_start = keyword, "1.0"
        if not keyword:
            self._find_start = "1.0"
            return
        found = self.details.search(
            keyword, self._find_start, stopindex="end", nocase=True
        )
        if not found:
            found = self.details.search(keyword, "1.0", stopindex="end", nocase=True)
        if found:
            end = f"{found}+{len(keyword)}c"
            self.details.tag_add("search-hit", found, end)
            self.details.see(found)
            self._find_start = end
            line = int(found.split(".")[0])
            index = max(
                (
                    i
                    for i, (_, start) in enumerate(self._sections)
                    if int(start.split(".")[0]) <= line
                ),
                default=0,
            )
            self._mark_section(index)
        else:
            self.status.configure(
                text="当前报告内没有匹配文字；可改搜字段原名、原值或诊断代码。"
            )
            self._find_start = "1.0"

    def _select_all(self, _event=None) -> str:
        focus = self.focus_get()
        for entry in (self.source_entry, self.query_entry, self.find_entry):
            if focus is entry._entry:
                entry.select_range(0, "end")
                entry.icursor("end")
                return "break"
        self.details.focus_set()
        self.details.tag_add("sel", "1.0", "end-1c")
        self.details.mark_set("insert", "end-1c")
        return "break"

    def _copy(self, text: str) -> None:
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)

    def _copy_selected(self) -> None:
        try:
            self._copy(self.details.get("sel.first", "sel.last"))
        except TclError:
            pass  # An empty selection is an ordinary no-op.

    def export_report(self, format: str | None = None) -> None:
        if self._closed:
            return
        selection = self._selection
        if selection is None or not self._fresh:
            self.status.configure(text="请先读取当前配置并完成筛选，再导出报告。")
            return
        suffix = format or "json"
        path = filedialog.asksaveasfilename(
            parent=self,
            title="导出完整 War3Tools 配置证据到新文件",
            initialfile="War3Tools配置证据." + suffix,
            defaultextension="." + suffix,
            filetypes=[("JSON", "*.json"), ("Markdown", "*.md"), ("TSV", "*.tsv")],
        )
        if not path:
            return
        generation = self._generation
        chosen_format = format or Path(path).suffix.lower().lstrip(".") or "json"
        self._set_export_state(False)
        self.status.configure(text="导出前正在复验完整来源 …")

        def work(ticket: GuiWorkerTicket) -> None:
            try:
                if ticket.cancellation.is_set():
                    return
                output = write_war3tools_export(path, selection, chosen_format)
                self._post_gui_worker(
                    ticket, lambda: self._receive_export(generation, str(output), "")
                )
            except Exception as exc:  # BROAD_EXCEPT_OK - keep export failures visible without unhandled worker exceptions.
                message = f"{type(exc).__name__}: {exc}"
                self._post_gui_worker(
                    ticket, lambda: self._receive_export(generation, "", message)
                )

        self._start_gui_worker("war3tools-export", work, replace=True)

    def _receive_export(self, generation: int, output: str, error: str) -> None:
        if self._closed or generation != self._generation:
            return
        if error:
            self._fresh = False
            self._set_export_state(False)
            self.status.configure(
                text="导出失败；请刷新来源或选择独立的新文件名：" + error
            )
            messagebox.showerror("War3Tools 配置报告导出失败", error, parent=self)
        else:
            self._set_export_state(self._fresh)
            self.status.configure(text="已导出完整配置证据报告：" + output)

    def _on_destroy(self, event) -> None:
        if event.widget is self and not self._closed:
            self._stop()

    def _stop(self) -> None:
        self._closed = True
        self._generation += 1
        for identifier in tuple(self._scheduled):
            try:
                self.after_cancel(identifier)
            except TclError:
                pass  # An already-delivered callback has nothing left to cancel.
        self._scheduled.clear()
        self._shutdown_gui_worker_host(0)

    def destroy(self) -> None:
        if self._closed:
            return
        self._memo()
        cancel_widget_callbacks(self)
        self._stop()
        super().destroy()


def open_war3tools_config_dialog(
    parent, *, initial_path: str = ""
) -> War3ToolsConfigDialog:
    return War3ToolsConfigDialog(parent, initial_path=initial_path)


__all__ = ("War3ToolsConfigDialog", "open_war3tools_config_dialog")
