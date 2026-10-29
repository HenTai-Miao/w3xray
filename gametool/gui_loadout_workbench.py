"""Independent offline equipment-plan viewer with main-thread Tk delivery."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import json
from pathlib import Path
from time import monotonic
import tkinter as tk
from tkinter import TclError, filedialog, messagebox, ttk

import customtkinter as ctk

from .cache_root import gamexray_cache_root
from .gui_pack_query import bind_geometry_memory
from .gui_tk_callbacks import cancel_widget_callbacks
from .gui_worker_host import GuiWorkerHostMixin
from .gui_worker_registry import GuiWorkerTicket
from .loadout_report import (
    LoadoutReport,
    LoadoutSelection,
    format_loadout_report,
    loadout_report_payload,
    read_loadout_report,
    select_loadout_report,
    write_loadout_export,
)
from .save_text_encoding import SAVE_TEXT_ENCODINGS, normalize_save_text_encoding
from .theme import BG, CARD, FONT, MONO_FONT, SUBTLE, TITLE_FONT


_session_selection: LoadoutSelection | None = None


def _memo_path() -> Path:
    return gamexray_cache_root() / "gui-query-memo" / "loadout-workbench.json"


def _load_memo() -> dict[str, str]:
    try:
        value = json.loads(_memo_path().read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return {
                key: value[key]
                for key in ("source", "query", "encoding")
                if isinstance(value.get(key), str)
            }
    except OSError, ValueError, UnicodeError:
        pass  # GUI memory is optional; it never blocks reading a selected file.
    return {}


def _save_memo(values: dict[str, str]) -> None:
    try:
        path = _memo_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(values, ensure_ascii=True), encoding="utf-8")
    except OSError, ValueError, UnicodeError:
        pass  # A failed preference write does not change or discard user input.


class LoadoutWorkbench(ctk.CTkToplevel, GuiWorkerHostMixin):
    def __init__(self, parent, *, initial_path: str = "") -> None:
        super().__init__(parent)
        self.title("离线装备方案")
        self.configure(fg_color=BG)
        self.minsize(900, 600)
        bind_geometry_memory(self, "loadout-workbench", "1180x800")
        self._closed = False
        self._generation = 0
        self._text_epoch = 0
        self._tree_epoch = 0
        self._scheduled: set[str] = set()
        self._report: LoadoutReport | None = None
        self._selection: LoadoutSelection | None = None
        self._fresh = False
        self._detail_text = ""
        self._find_start = "1.0"
        self._find_keyword = ""
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
        self._build_controls()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.bind("<Escape>", lambda _event: self.destroy())
        for key in ("f", "F"):
            self.bind(
                f"<Control-{key}>",
                lambda _event: self.find_entry.focus_set() or "break",
            )
        for key in ("a", "A"):
            self.bind(f"<Control-{key}>", self._select_all)
        for key in ("r", "R"):
            self.bind(f"<Control-{key}>", lambda _event: self.refresh() or "break")
        self.source_var.trace_add("write", self._invalidate_source)
        self.encoding_var.trace_add("write", self._invalidate_source)
        self.transient(parent)
        self._schedule(self._activate)
        if initial_path:
            self._schedule(self.refresh)
        elif _session_selection is not None:
            self._report = _session_selection.report
            self._receive_selection(_session_selection, self._generation, fresh=False)
            self.status.configure(
                text="显示本进程上次读取快照；点击「读取 / 刷新」后可导出。"
            )
        else:
            self._show_text(
                "# 离线装备方案\n\n选择六槽或九槽方案 JSON，然后点击「读取 / 刷新」。\n\n## 继续查证\n本窗口离线检查明确的 schema=1 与 codes/records 声明；保留全部槽位、数量、重复键与未知字段。没有方案文件时，可先从原工具导出或选择已保存的方案。"
            )

    def _activate(self) -> None:
        self.grab_set()
        self.focus_set()

    def _build_controls(self) -> None:
        ctk.CTkLabel(self, text="离线装备方案", font=(TITLE_FONT, 21, "bold")).pack(
            anchor="w", padx=14, pady=(12, 3)
        )
        ctk.CTkLabel(
            self,
            text="查看方案声明与完整原始证据；不连接游戏，不确认实际持有、可装备性或效果。",
            font=(FONT, 11),
            text_color=SUBTLE,
        ).pack(anchor="w", padx=14, pady=(0, 6))
        source = ctk.CTkFrame(self, fg_color=CARD)
        source.pack(fill="x", padx=12, pady=3)
        ctk.CTkLabel(source, text="方案 JSON", width=80).pack(side="left", padx=4)
        self.source_entry = ctk.CTkEntry(source, textvariable=self.source_var)
        self.source_entry.pack(side="left", fill="x", expand=True, padx=4, pady=5)
        ctk.CTkButton(source, text="选文件", width=80, command=self._pick_file).pack(
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
            placeholder_text="按完整方案搜索 ID、名称、数量或扩展字段；支持 &&、||",
        )
        self.query_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.query_entry.bind("<Return>", lambda _event: self.search())
        ctk.CTkButton(controls, text="搜索", width=65, command=self.search).pack(
            side="left", padx=3
        )
        ctk.CTkButton(
            controls, text="清空筛选", width=85, command=self._clear_query
        ).pack(side="left", padx=3)
        self.export_buttons: dict[str, ctk.CTkButton] = {}
        for format in ("json", "md", "tsv"):
            button = ctk.CTkButton(
                controls,
                text="导出 " + format.upper(),
                width=85,
                state="disabled",
                command=lambda selected=format: self.export_report(selected),
            )
            button.pack(side="left", padx=3)
            self.export_buttons[format] = button
        self.export_json_button = self.export_buttons["json"]
        self.export_md_button = self.export_buttons["md"]
        self.export_tsv_button = self.export_buttons["tsv"]
        self.export_button = self.export_json_button
        self.status = ctk.CTkLabel(
            self,
            text="请选择方案文件；无需运行训练器或游戏。",
            anchor="w",
            font=(FONT, 11),
            text_color=SUBTLE,
        )
        self.status.pack(fill="x", padx=14, pady=3)
        table = ctk.CTkFrame(self, fg_color=CARD)
        table.pack(fill="x", padx=12, pady=4)
        self.tree = ttk.Treeview(
            table,
            columns=("ordinal", "name", "unit", "slots", "state"),
            show="headings",
            height=5,
            selectmode="browse",
        )
        for column, label, width in (
            ("ordinal", "序号", 50),
            ("name", "原声明名称", 260),
            ("unit", "单位代码", 100),
            ("slots", "完整槽位数", 100),
            ("state", "声明状态", 160),
        ):
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, stretch=column == "name")
        self.tree.pack(side="left", fill="x", expand=True)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._show_selected())
        jump = ctk.CTkFrame(self, fg_color="transparent")
        jump.pack(fill="x", padx=12, pady=3)
        ctk.CTkButton(
            jump, text="全部匹配方案", width=110, command=self._show_all
        ).pack(side="left", padx=3)
        self.jump_buttons: dict[str, ctk.CTkButton] = {}
        for name in (
            "来源与状态",
            "完整记录与槽位",
            "全部诊断",
            "完整来源与证据",
            "继续查证",
        ):
            button = ctk.CTkButton(
                jump,
                text=name,
                width=110,
                fg_color="transparent",
                border_width=1,
                command=lambda section=name: self._jump(section),
            )
            button.pack(side="left", padx=3)
            self.jump_buttons[name] = button
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
            }
        )

    def _invalidate_source(self, *_args) -> None:
        self._generation += 1
        self._fresh = False
        self._cancel_gui_worker_group("loadout-read")
        self._cancel_gui_worker_group("loadout-query")
        for button in self.export_buttons.values():
            button.configure(state="disabled")
        self.status.configure(
            text="来源或编码已改变；请点击「读取 / 刷新」，当前内容为上次快照。"
        )

    def _pick_file(self) -> None:
        if path := filedialog.askopenfilename(
            parent=self,
            title="选择离线装备方案",
            filetypes=[("JSON", "*.json"), ("所有文件", "*.*")],
        ):
            self.source_var.set(path)
            self.refresh()

    def refresh(self) -> None:
        source = self.source_var.get().strip()
        if not source:
            self.status.configure(
                text="请选择明确的方案 JSON 文件；不会自动搜索个人配置。"
            )
            return
        self._memo()
        self._generation += 1
        generation = self._generation
        encoding = self.encoding_var.get()
        query = self.query_var.get()
        self._report = None
        self._selection = None
        self._fresh = False
        for button in self.export_buttons.values():
            button.configure(state="disabled")
        self._cancel_gui_worker_group("loadout-query")
        self._cancel_gui_worker_group("loadout-detail")
        self._tree_epoch += 1
        existing = self.tree.get_children()
        if existing:
            self.tree.delete(*existing)
        self.title(f"离线装备方案 · {Path(source).name}")
        self.status.configure(text="正在完整读取、解释声明并复验来源字节 …")
        self._show_text("# 离线装备方案\n\n后台正在读取所选文件。")

        def work(ticket: GuiWorkerTicket) -> None:
            started = monotonic()
            try:
                report = read_loadout_report(source, text_encoding=encoding)
                selection = select_loadout_report(report, query)
                text = format_loadout_report(selection)
                elapsed = monotonic() - started
                if not ticket.cancellation.is_set():
                    self._post_gui_worker(
                        ticket,
                        lambda: self._receive_selection(
                            selection, generation, text=text, elapsed=elapsed
                        ),
                    )
            except Exception as exc:  # BROAD_EXCEPT_OK - deliver worker failures with an actionable source retry.
                message = f"读取失败：{type(exc).__name__}: {exc}；请选择稳定的方案文件后重试。"
                self._post_gui_worker(
                    ticket,
                    lambda: (
                        self.status.configure(text=message)
                        if generation == self._generation
                        else None
                    ),
                )

        self._start_gui_worker("loadout-read", work, replace=True)

    def _receive_selection(
        self,
        selection: LoadoutSelection,
        generation: int,
        *,
        text: str | None = None,
        elapsed: float = 0,
        fresh: bool = True,
    ) -> None:
        global _session_selection
        if self._closed or generation != self._generation:
            return
        _session_selection = selection
        self._report = selection.report
        self._selection = selection
        self.title(f"离线装备方案 · {Path(selection.report.document.source).name}")
        self._fresh = fresh and selection.report.stable
        for button in self.export_buttons.values():
            button.configure(state="normal" if self._fresh else "disabled")
        self.status.configure(
            text=f"{selection.report.document.status} · 全部 {len(selection.report.document.records)} 条方案，匹配 {len(selection.records)} 条 · {elapsed:.3f} 秒 · 完整诊断与原始来源保留"
        )
        self._render_tree(selection)
        self._show_text(text if text is not None else format_loadout_report(selection))

    def _render_tree(self, selection: LoadoutSelection) -> None:
        self._tree_epoch += 1
        epoch = self._tree_epoch
        existing = self.tree.get_children()
        if existing:
            self.tree.delete(*existing)
        pending = iter(selection.records)

        def batch() -> None:
            if epoch != self._tree_epoch:
                return
            for _ in range(80):
                record = next(pending, None)
                if record is None:
                    return
                self.tree.insert(
                    "",
                    "end",
                    iid=str(record.ordinal),
                    values=(
                        record.ordinal,
                        record.name or "未声明名称",
                        record.unit_code or "未声明/空",
                        len(record.slots),
                        record.state,
                    ),
                )
            self._schedule(batch)

        self._schedule(batch)

    def search(self) -> None:
        if self._report is None:
            self.status.configure(text="请先读取方案文件，再按完整记录搜索。")
            return
        report, query, generation, fresh = (
            self._report,
            self.query_var.get(),
            self._generation,
            self._fresh,
        )
        self._memo()
        self._cancel_gui_worker_group("loadout-detail")

        def work(ticket: GuiWorkerTicket) -> None:
            try:
                selection = select_loadout_report(report, query)
                text = format_loadout_report(selection)
                if not ticket.cancellation.is_set():
                    self._post_gui_worker(
                        ticket,
                        lambda: self._receive_selection(
                            selection, generation, text=text, fresh=fresh
                        ),
                    )
            except ValueError as exc:
                message = str(exc)
                self._post_gui_worker(
                    ticket, lambda: self.status.configure(text=message)
                )

        self._start_gui_worker("loadout-query", work, replace=True)

    def _clear_query(self) -> None:
        self.query_var.set("")
        self.search()

    def _show_selected(self) -> None:
        selection = self._selection
        chosen = self.tree.selection()
        if selection is None or not chosen:
            return
        records = tuple(
            record for record in selection.records if str(record.ordinal) == chosen[0]
        )
        self._render_details(replace(selection, records=records))

    def _show_all(self) -> None:
        if self._selection is not None:
            self._render_details(self._selection)

    def _render_details(self, selection: LoadoutSelection) -> None:
        generation = self._generation

        def work(ticket: GuiWorkerTicket) -> None:
            text = format_loadout_report(selection)
            if not ticket.cancellation.is_set():
                self._post_gui_worker(
                    ticket,
                    lambda: (
                        self._show_text(text)
                        if generation == self._generation
                        else None
                    ),
                )

        self._start_gui_worker("loadout-detail", work, replace=True)

    def _show_text(self, text: str) -> None:
        self._text_epoch += 1
        epoch = self._text_epoch
        self._detail_text = text
        self._find_start = "1.0"
        self._find_keyword = ""
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.configure(state="disabled")
        offset = 0

        def batch() -> None:
            nonlocal offset
            if epoch != self._text_epoch:
                return
            self.details.configure(state="normal")
            self.details.insert("end", text[offset : offset + 32768])
            self.details.configure(state="disabled")
            offset += 32768
            if offset < len(text):
                self._schedule(batch)
            else:
                self.details.see("1.0")
                self._jump("来源与状态")

        self._schedule(batch)

    def _jump(self, section: str) -> None:
        found = self.details.search("## " + section, "1.0", stopindex="end")
        if found:
            self.details.see(found)
            self.details.tag_remove("section-current", "1.0", "end")
            self.details.tag_add("section-current", found, found + " lineend")
            for name, button in self.jump_buttons.items():
                button.configure(
                    fg_color="#245b4b" if name == section else "transparent"
                )

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
        else:
            self.status.configure(
                text="当前报告内没有匹配文字；可改搜名称、四码或诊断代码。"
            )

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
        selection = self._selection
        if selection is None or not self._fresh:
            self.status.configure(text="请先读取当前方案文件；刷新后可以导出。")
            return
        suffix = format or "json"
        path = filedialog.asksaveasfilename(
            parent=self,
            title="导出完整方案证据到新文件",
            initialfile="装备方案证据." + suffix,
            defaultextension="." + suffix,
            filetypes=[("JSON", "*.json"), ("Markdown", "*.md"), ("TSV", "*.tsv")],
        )
        if not path:
            return
        self.status.configure(text="导出前正在复验来源完整字节 …")
        generation = self._generation

        def work(ticket: GuiWorkerTicket) -> None:
            try:
                chosen_format = (
                    format or Path(path).suffix.lower().lstrip(".") or "json"
                )
                # Validate format before publication; no GUI calls occur here.
                loadout_report_payload(selection, chosen_format)
                if ticket.cancellation.is_set():
                    return
                output = write_loadout_export(path, selection, chosen_format)
                self._post_gui_worker(
                    ticket,
                    lambda: (
                        self.status.configure(text=f"已导出完整证据报告：{output}")
                        if generation == self._generation
                        else None
                    ),
                )
            except (OSError, ValueError) as exc:
                message = str(exc)

                def show_error() -> None:
                    if generation == self._generation:
                        self.status.configure(text="导出失败：" + message)
                        messagebox.showerror("装备方案导出失败", message, parent=self)

                self._post_gui_worker(ticket, show_error)

        self._start_gui_worker("loadout-export", work, replace=True)

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


def open_loadout_workbench(parent, *, initial_path: str = "") -> LoadoutWorkbench:
    return LoadoutWorkbench(parent, initial_path=initial_path)


__all__ = ("LoadoutWorkbench", "open_loadout_workbench")
