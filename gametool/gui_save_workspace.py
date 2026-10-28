"""Independent offline save browser with Tk-safe workers and complete file views."""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path, PurePosixPath
from time import monotonic
import tkinter as tk
from tkinter import TclError, filedialog, messagebox, ttk
from typing import TYPE_CHECKING

import customtkinter as ctk

from .api import load_map
from .cache_root import gamexray_cache_root
from .gui_pack_query import bind_geometry_memory
from .gui_worker_host import GuiWorkerHostMixin
from .gui_worker_registry import GuiWorkerTicket
from .gui_tk_callbacks import cancel_widget_callbacks
from .pack_query_options import parse_query_limit
from .real_save_files import (
    RealSaveFile,
    RealSaveReport,
    SaveFileKind,
    analyze_real_save_path,
)
from .safe_output_models import SafeWriteStatus
from .save_report_query import (
    SaveReportSelection,
    format_save_file_details,
    select_save_report,
    verify_save_report_sources,
    write_save_report,
)
from .theme import BG, CARD, FONT, MONO_FONT, SUBTLE, TEXT, TITLE_FONT

if TYPE_CHECKING:
    from .map_data import MapData


def _load_workspace_memo() -> dict[str, str]:
    try:
        value = json.loads(
            (
                gamexray_cache_root() / "gui-query-memo" / "save-workspace.json"
            ).read_text(encoding="utf-8")
        )
    except OSError, ValueError:
        return {}
    return (
        {
            key: item
            for key, item in value.items()
            if isinstance(key, str) and isinstance(item, str)
        }
        if isinstance(value, dict)
        else {}
    )


def _save_workspace_memo(value: dict[str, str]) -> None:
    try:
        destination = gamexray_cache_root() / "gui-query-memo" / "save-workspace.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    except OSError, UnicodeError:
        pass  # fail-open: a memo failure never prevents save analysis or closing.


class SaveWorkspace(ctk.CTkToplevel, GuiWorkerHostMixin):
    """A map-optional save workspace; no worker ever calls a Tk method."""

    def __init__(
        self, parent, *, initial_path: str = "", map_data: MapData | None = None
    ) -> None:
        super().__init__(parent)
        self.title("离线存档工作台")
        self.configure(fg_color=BG)
        self.minsize(860, 570)
        bind_geometry_memory(self, "save-workspace", "1180x760")
        self._closed = False
        self._scheduled: set[str] = set()
        self._tree_epoch = 0
        self._text_epoch = 0
        self._generation = 0
        self._report: RealSaveReport | None = None
        self._selection: SaveReportSelection | None = None
        self._row_records: dict[str, RealSaveFile] = {}
        self._find_start = "1.0"
        self._find_keyword = ""
        self._detail_text = ""
        self._init_gui_worker_host()
        memo = _load_workspace_memo()
        self.source_var = tk.StringVar(value=initial_path or memo.get("source", ""))
        self.map_var = tk.StringVar(
            value=map_data.path if map_data is not None else memo.get("map", "")
        )
        self.query_var = tk.StringVar(value=memo.get("query", ""))
        self.kind_var = tk.StringVar(value=memo.get("kind", "全部"))
        self.limit_var = tk.StringVar(value=memo.get("limit", "0"))
        self.find_var = tk.StringVar()
        self._build_controls()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.bind("<Escape>", lambda _event: self.destroy())
        for key in ("f", "F"):
            self.bind(f"<Control-{key}>", lambda _event: self.find_entry.focus_set())
        for key in ("a", "A"):
            self.bind(f"<Control-{key}>", self._select_all)
        for key in ("r", "R"):
            self.bind(f"<Control-{key}>", lambda _event: self.refresh())
        self.transient(parent)
        self._schedule(self._activate)
        self._show_text(
            "# 离线存档工作台\n\n选择存档文件或目录，然后点击「读取 / 刷新」。地图为可选关联来源。\n\n读取过程中不会执行存档中的文本或脚本；未知私有格式保留来源、大小、SHA256 与诊断。"
        )
        if initial_path:
            self._schedule(self.refresh)

    def _activate(self) -> None:
        self.grab_set()
        self.focus_set()

    def _build_controls(self) -> None:
        ctk.CTkLabel(
            self, text="离线存档工作台", font=(TITLE_FONT, 21, "bold"), text_color=TEXT
        ).pack(anchor="w", padx=14, pady=(12, 4))
        source_row = ctk.CTkFrame(self, fg_color=CARD)
        source_row.pack(fill="x", padx=12, pady=3)
        ctk.CTkLabel(source_row, text="存档来源", width=72, font=(FONT, 12)).pack(
            side="left", padx=4
        )
        self.source_entry = ctk.CTkEntry(source_row, textvariable=self.source_var)
        self.source_entry.pack(side="left", fill="x", expand=True, padx=4, pady=5)
        ctk.CTkButton(
            source_row, text="选目录", width=72, command=self._pick_directory
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            source_row, text="选文件", width=72, command=self._pick_file
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            source_row, text="读取 / 刷新", width=100, command=self.refresh
        ).pack(side="left", padx=(3, 7))
        self.source_entry.bind("<Return>", lambda _event: self.refresh())
        map_row = ctk.CTkFrame(self, fg_color=CARD)
        map_row.pack(fill="x", padx=12, pady=3)
        ctk.CTkLabel(map_row, text="可选地图", width=72, font=(FONT, 12)).pack(
            side="left", padx=4
        )
        self.map_entry = ctk.CTkEntry(
            map_row, textvariable=self.map_var, placeholder_text="留空即可独立读取存档"
        )
        self.map_entry.pack(side="left", fill="x", expand=True, padx=4, pady=5)
        ctk.CTkButton(map_row, text="关联地图", width=84, command=self._pick_map).pack(
            side="left", padx=3
        )
        ctk.CTkButton(map_row, text="清除关联", width=84, command=self._clear_map).pack(
            side="left", padx=(3, 7)
        )
        filter_row = ctk.CTkFrame(self, fg_color=CARD)
        filter_row.pack(fill="x", padx=12, pady=3)
        self.query_entry = ctk.CTkEntry(
            filter_row,
            textvariable=self.query_var,
            placeholder_text="搜索文件 / 记录 / 载体 / 偏移；支持 &&、||、%、括号",
        )
        self.query_entry.pack(side="left", fill="x", expand=True, padx=6, pady=5)
        self.query_entry.bind("<Return>", lambda _event: self.search())
        self.kind_menu = ctk.CTkOptionMenu(
            filter_row,
            variable=self.kind_var,
            values=["全部", *(kind.value for kind in SaveFileKind)],
            width=115,
            command=lambda _value: self.search(),
        )
        self.kind_menu.pack(side="left", padx=3)
        ctk.CTkLabel(filter_row, text="文件数 0=全部", font=(FONT, 11)).pack(
            side="left", padx=4
        )
        self.limit_entry = ctk.CTkEntry(
            filter_row, textvariable=self.limit_var, width=65
        )
        self.limit_entry.pack(side="left", padx=3)
        self.limit_entry.bind("<Return>", lambda _event: self.search())
        ctk.CTkButton(filter_row, text="搜索", width=62, command=self.search).pack(
            side="left", padx=3
        )
        self.export_button = ctk.CTkButton(
            filter_row,
            text="导出报告",
            width=88,
            state="disabled",
            command=self.export_report,
        )
        self.export_button.pack(side="left", padx=(3, 6))
        self.status = ctk.CTkLabel(
            self,
            text="选择来源；地图可选。",
            anchor="w",
            text_color=SUBTLE,
            font=(FONT, 12),
            wraplength=1120,
        )
        self.status.pack(fill="x", padx=14, pady=(3, 5))
        split = tk.PanedWindow(self, orient="horizontal", sashwidth=6, bg=BG, bd=0)
        split.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        left = ctk.CTkFrame(split, fg_color=CARD)
        right = ctk.CTkFrame(split, fg_color=CARD)
        split.add(left, width=400, minsize=250)
        split.add(right, minsize=400)
        ctk.CTkLabel(
            left, text="目录与完整文件列表", anchor="w", font=(FONT, 12, "bold")
        ).pack(fill="x", padx=6, pady=4)
        tree_frame = tk.Frame(left, bg=CARD)
        tree_frame.pack(fill="both", expand=True, padx=5, pady=(0, 5))
        self.tree = ttk.Treeview(
            tree_frame,
            columns=("kind", "size", "state"),
            show="tree headings",
            selectmode="browse",
        )
        self.tree.heading("#0", text="文件 / 容器")
        self.tree.heading("kind", text="类型")
        self.tree.heading("size", text="字节")
        self.tree.heading("state", text="状态")
        for column, width in (("#0", 200), ("kind", 75), ("size", 80), ("state", 90)):
            self.tree.column(column, width=width, minwidth=50)
        scroll_y = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        scroll_x = ttk.Scrollbar(
            tree_frame, orient="horizontal", command=self.tree.xview
        )
        self.tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._select_file)
        tree_menu = tk.Menu(self, tearoff=False)
        tree_menu.add_command(label="查看完整文件详情", command=self._select_file)
        tree_menu.add_command(label="复制来源路径", command=self._copy_source)
        tree_menu.add_command(
            label="导出当前完整文件 (.json)", command=self.export_file
        )
        self.tree.bind("<Button-3>", lambda event: self._tree_context(event, tree_menu))
        jumps = ctk.CTkFrame(right, fg_color="transparent")
        jumps.pack(fill="x", padx=5, pady=4)
        self.jump_buttons: dict[str, ctk.CTkButton] = {}
        for name in ("概览", "来源与状态", "完整结构与记录", "全部诊断"):
            button = ctk.CTkButton(
                jumps,
                text=name,
                width=100,
                command=lambda section=name: self._jump(section),
            )
            button.pack(side="left", padx=2)
            self.jump_buttons[name] = button
        find_row = ctk.CTkFrame(right, fg_color="transparent")
        find_row.pack(fill="x", padx=6, pady=(0, 4))
        self.find_entry = ctk.CTkEntry(
            find_row,
            textvariable=self.find_var,
            placeholder_text="Ctrl+F 内搜详情，回车逐处跳转",
        )
        self.find_entry.pack(side="left", fill="x", expand=True)
        self.find_entry.bind("<Return>", self._find_next)
        ctk.CTkButton(find_row, text="下一处", width=64, command=self._find_next).pack(
            side="left", padx=(4, 0)
        )
        self.details = ctk.CTkTextbox(
            right, font=(MONO_FONT, 12), wrap="none", fg_color=CARD, text_color=TEXT
        )
        self.details.pack(fill="both", expand=True, padx=5, pady=(0, 5))
        self.details.configure(state="disabled")
        self.details.tag_config(
            "search-hit", background="#fff0ab", foreground="#1b3550"
        )
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="复制选中", command=self._copy_selected)
        menu.add_command(
            label="复制全部", command=lambda: self._copy(self._detail_text)
        )
        menu.add_command(label="导出当前完整文件 (.json)", command=self.export_file)
        menu.add_command(
            label="导出完整报告 (.md/.json/.tsv)", command=self.export_report
        )
        self.details.bind(
            "<Button-3>", lambda event: menu.tk_popup(event.x_root, event.y_root)
        )

    def _memo(self) -> None:
        _save_workspace_memo(
            {
                "source": self.source_var.get(),
                "map": self.map_var.get(),
                "query": self.query_var.get(),
                "kind": self.kind_var.get(),
                "limit": self.limit_var.get(),
            }
        )

    def _schedule(self, callback: Callable[[], object]) -> None:
        if self._closed:
            return
        identifier = ""

        def deliver() -> None:
            self._scheduled.discard(identifier)
            if not self._closed:
                callback()

        identifier = self.after(1, deliver)
        self._scheduled.add(identifier)

    def _pick_directory(self) -> None:
        if path := filedialog.askdirectory(parent=self, title="选择真实存档目录"):
            self.source_var.set(path)
            self.refresh()

    def _pick_file(self) -> None:
        if path := filedialog.askopenfilename(
            parent=self, title="选择真实存档文件", filetypes=[("所有文件", "*.*")]
        ):
            self.source_var.set(path)
            self.refresh()

    def _pick_map(self) -> None:
        if path := filedialog.askopenfilename(
            parent=self,
            title="选择用于静态关联的地图",
            filetypes=[
                ("Warcraft 地图 / 战役", "*.w3x *.w3m *.w3n"),
                ("所有文件", "*.*"),
            ],
        ):
            self.map_var.set(path)
            if self.source_var.get().strip():
                self.refresh()

    def _clear_map(self) -> None:
        self.map_var.set("")
        if self.source_var.get().strip():
            self.refresh()

    def refresh(self) -> None:
        source = self.source_var.get().strip()
        if not source:
            self.status.configure(text="请选择存档目录或文件；地图可留空。")
            return
        try:
            limit = parse_query_limit(self.limit_var.get())
            query, kind = self.query_var.get(), self.kind_var.get()
            _ = select_save_report(
                RealSaveReport("", (), ()), query, "" if kind == "全部" else kind, limit
            )
        except ValueError as exc:
            self.status.configure(text=str(exc))
            return
        self._memo()
        self._generation += 1
        generation = self._generation
        self._report = None
        self._selection = None
        self.export_button.configure(state="disabled")
        self._cancel_gui_worker_group("save-query")
        self._cancel_gui_worker_group("save-detail")
        self._cancel_gui_worker_group("save-export")
        self._tree_epoch += 1
        self._row_records.clear()
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        map_path = self.map_var.get().strip()
        self.title(f"离线存档工作台 · {Path(source).name or source}")
        self.status.configure(
            text="正在读取全部文件、容器与记录，并复验完整输入 SHA256 …"
        )
        self._show_text("# 概览\n\n正在后台读取来源。完成后目录与文件将逐步显示。")

        def work(ticket: GuiWorkerTicket) -> None:
            md = None
            owned = False
            started = monotonic()
            try:
                if map_path:
                    md = load_map(map_path)
                    owned = True
                if ticket.cancellation.is_set():
                    return
                report = analyze_real_save_path(source, md)
                if ticket.cancellation.is_set():
                    return
                elapsed = monotonic() - started
                self._post_gui_worker(
                    ticket, lambda: self._receive_report(report, generation, elapsed)
                )
            except Exception as exc:  # BROAD_EXCEPT_OK - worker boundary delivers the complete actionable error to Tk.
                message = f"{type(exc).__name__}: {exc}"
                self._post_gui_worker(
                    ticket,
                    lambda: self.status.configure(
                        text="读取失败：" + message + "；可更换来源后重试。"
                    ),
                )
            finally:
                if owned and md is not None:
                    md.close()

        self._start_gui_worker("save-analysis", work, replace=True)

    def _receive_report(
        self, report: RealSaveReport, generation: int, elapsed: float
    ) -> None:
        if self._closed or generation != self._generation:
            return
        self._report = report
        self.status.configure(
            text=f"{'已完成' if report.complete else '未完成，保留已确认记录'} · 读取 {len(report.files)} 个稳定文件 · {len(report.unverified_files)} 个已变化来源 · {elapsed:.3f} 秒 · {'已关联地图' if report.map_associated else '未做地图关联'}"
        )
        self.search()

    def search(self) -> None:
        report = self._report
        if report is None:
            if self.source_var.get().strip():
                self.status.configure(
                    text="请先点击「读取 / 刷新」；已有读取任务时请等待读取完成。"
                )
            return
        try:
            limit = parse_query_limit(self.limit_var.get())
        except ValueError as exc:
            self.status.configure(text=str(exc))
            return
        query, kind = self.query_var.get(), self.kind_var.get()
        kind = "" if kind == "全部" else kind
        self._memo()
        self.status.configure(text="正在按完整文件检索全部证据字段 …")

        def work(ticket: GuiWorkerTicket) -> None:
            try:
                selection = select_save_report(report, query, kind, limit)
                if not ticket.cancellation.is_set():
                    self._post_gui_worker(
                        ticket, lambda: self._receive_selection(selection, report)
                    )
            except ValueError as exc:
                message = str(exc)
                self._post_gui_worker(
                    ticket, lambda: self.status.configure(text=message)
                )

        self._start_gui_worker("save-query", work, replace=True)

    def _receive_selection(
        self, selection: SaveReportSelection, report: RealSaveReport
    ) -> None:
        if self._closed or self._report is not report:
            return
        self._selection = selection
        self.export_button.configure(state="normal")
        self.status.configure(
            text=f"{'完整' if report.complete else '未完成，见全部诊断'} · 全部 {selection.total_files} 个文件，匹配 {selection.matched_files}，显示 {len(selection.files)}，显式省略 {selection.omitted_files} · {'已关联地图' if report.map_associated else '未做地图关联'}"
        )
        self._show_text(
            "# 概览\n\n"
            + f"来源: {report.source}\n地图: {report.map_path if report.map_associated else '未选择，未做地图关联'}\n完整性: {report.complete}\n"
            + f"总文件数: {selection.total_files}\n匹配: {selection.matched_files}\n显示: {len(selection.files)}\n显式限制省略: {selection.omitted_files}\n\n"
            + (
                "从左侧选择一个文件查看其全部记录、SHA256、容器和偏移。"
                if selection.files
                else "没有匹配文件；清空搜索和类型筛选，或选择其他来源。"
            )
            + "\n\n# 全部诊断\n\n"
            + "\n\n".join(
                selection.diagnostics
                or ("来源复验未发现问题；请核对每个文件的格式和记录状态。",)
            )
        )
        self._render_tree(selection)

    def _render_tree(self, selection: SaveReportSelection) -> None:
        self._tree_epoch += 1
        epoch = self._tree_epoch
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        self._row_records.clear()
        pending = iter(enumerate(selection.files))
        directories: dict[str, str] = {".": ""}

        def batch() -> None:
            if self._closed or epoch != self._tree_epoch:
                return
            deadline = monotonic() + 0.008
            while monotonic() < deadline:
                try:
                    index, record = next(pending)
                except StopIteration:
                    return
                path = PurePosixPath(record.relative_path)
                parent = ""
                for directory in reversed(path.parents):
                    key = str(directory)
                    if key == ".":
                        continue
                    if key not in directories:
                        iid = f"directory-{len(directories)}"
                        self.tree.insert(
                            parent, "end", iid=iid, text=directory.name, open=True
                        )
                        directories[key] = iid
                    parent = directories[key]
                iid = f"file-{index}"
                self.tree.insert(
                    parent,
                    "end",
                    iid=iid,
                    text=path.name,
                    values=(
                        record.kind.value,
                        str(record.size),
                        "来源已变化"
                        if not record.source_stable
                        else "完整"
                        if record.complete
                        else "未完整解析",
                    ),
                )
                self._row_records[iid] = record
            self._schedule(batch)

        self._schedule(batch)

    def _selected_record(self) -> RealSaveFile | None:
        selected = self.tree.selection()
        return self._row_records.get(selected[0]) if selected else None

    def _select_file(self, _event=None) -> None:
        record = self._selected_record()
        if record is None:
            return
        report = self._report
        self._show_text(
            f"# 来源与状态\n\n正在后台展开 {record.relative_path} 的完整证据 …"
        )

        def work(ticket: GuiWorkerTicket) -> None:
            text = format_save_file_details(record)
            if not ticket.cancellation.is_set():
                self._post_gui_worker(
                    ticket,
                    lambda: (
                        self._show_text(text)
                        if self._report is report and self._selected_record() is record
                        else None
                    ),
                )

        self._start_gui_worker("save-detail", work, replace=True)

    def _show_text(self, text: str) -> None:
        self._text_epoch += 1
        epoch = self._text_epoch
        self._detail_text = text
        self._find_start = "1.0"
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.configure(state="disabled")
        offset = 0

        def batch() -> None:
            nonlocal offset
            if self._closed or epoch != self._text_epoch:
                return
            self.details.configure(state="normal")
            self.details.insert("end", text[offset : offset + 32768])
            self.details.configure(state="disabled")
            offset += 32768
            if offset < len(text):
                self._schedule(batch)
            else:
                self.details.see("1.0")

        self._schedule(batch)

    def _find_next(self, _event=None) -> None:
        self.details.tag_remove("search-hit", "1.0", "end")
        keyword = self.find_var.get()
        if keyword != self._find_keyword:
            self._find_keyword = keyword
            self._find_start = "1.0"
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

    def _jump(self, section: str) -> None:
        if section == "概览":
            self.details.see("1.0")
            for name, button in self.jump_buttons.items():
                button.configure(fg_color="#2ebbd9" if name == section else "#60849b")
            return
        found = self.details.search("# " + section, "1.0", stopindex="end")
        if found:
            self.details.see(found)
            for name, button in self.jump_buttons.items():
                button.configure(fg_color="#2ebbd9" if name == section else "#60849b")

    def _select_all(self, _event=None) -> str | None:
        focus = self.focus_get()
        for entry in (
            self.source_entry,
            self.map_entry,
            self.query_entry,
            self.limit_entry,
            self.find_entry,
        ):
            if focus is entry._entry:
                entry.select_range(0, "end")
                entry.icursor("end")
                return "break"
        self.details.focus_set()
        self.details.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _copy(self, text: str) -> None:
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)

    def _copy_selected(self) -> None:
        try:
            self._copy(self.details.get("sel.first", "sel.last"))
        except TclError:
            pass  # Empty selection is an ordinary no-op.

    def _copy_source(self) -> None:
        if record := self._selected_record():
            report = self._report
            if report is not None:
                root = (
                    Path(report.source)
                    if report.source_is_directory
                    else Path(report.source).parent
                )
                self._copy(str(root / record.relative_path))

    def _tree_context(self, event, menu: tk.Menu) -> None:
        if row := self.tree.identify_row(event.y):
            self.tree.selection_set(row)
        menu.tk_popup(event.x_root, event.y_root)

    def export_file(self) -> None:
        record = self._selected_record()
        if record is None:
            self.status.configure(
                text="先从左侧文件列表选择一个文件，再导出其完整证据。"
            )
            return
        self.export_report(only_file=record)

    def export_report(self, *, only_file: RealSaveFile | None = None) -> None:
        selection = self._selection
        if selection is None:
            self.status.configure(text="请先读取来源；解析不完整时也可导出全部诊断。")
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="导出离线存档证据报告",
            initialfile="存档文件证据.json"
            if only_file is not None
            else "离线存档报告.json",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("Markdown", "*.md"), ("TSV", "*.tsv")],
        )
        if not path:
            return
        self.status.configure(text="导出前正在复验全部来源 SHA256 …")
        generation = self._generation

        def work(ticket: GuiWorkerTicket) -> None:
            try:
                report = verify_save_report_sources(selection.report)
                refreshed = select_save_report(
                    report, selection.query, selection.kind, selection.limit
                )
                if only_file is not None:
                    from dataclasses import replace

                    match = tuple(
                        record
                        for record in (*report.files, *report.unverified_files)
                        if record.relative_path == only_file.relative_path
                        and record.sha256 == only_file.sha256
                    )
                    refreshed = replace(
                        refreshed,
                        files=match,
                        matched_files=len(match),
                        omitted_files=0,
                    )
                if ticket.cancellation.is_set():
                    return
                result = write_save_report(
                    refreshed, path, Path(path).suffix.lstrip(".").lower() or "json"
                )
                if result.status is not SafeWriteStatus.WRITTEN:
                    raise ValueError(result.error or result.status.value)
                refreshed = result.selection
                report = refreshed.report
                text = f"已导出 {len(refreshed.files)} 个完整文件记录与全部诊断：{result.path} · {'完整' if report.complete else '来源/解析未完成，见报告诊断'}"

                def deliver() -> None:
                    if (
                        generation == self._generation
                        and self._report is selection.report
                    ):
                        self.status.configure(text=text)

                self._post_gui_worker(ticket, deliver)
            except (OSError, ValueError) as exc:
                message = str(exc)

                def show_error() -> None:
                    if (
                        generation == self._generation
                        and self._report is selection.report
                    ):
                        messagebox.showerror("存档报告导出失败", message, parent=self)

                self._post_gui_worker(ticket, show_error)

        self._start_gui_worker("save-export", work, replace=True)

    def _on_destroy(self, event) -> None:
        if event.widget is self and not self._closed:
            self._stop_workspace()

    def _stop_workspace(self) -> None:
        self._closed = True
        self._generation += 1
        for identifier in tuple(self._scheduled):
            try:
                self.after_cancel(identifier)
            except TclError:
                pass  # A callback already delivered while the window closed.
        self._scheduled.clear()
        self._shutdown_gui_worker_host(0)

    def destroy(self) -> None:
        _ = cancel_widget_callbacks(self)
        if self._closed:
            return
        self._memo()
        self._stop_workspace()
        super().destroy()


def open_save_workspace(
    parent, *, initial_path: str = "", map_data: MapData | None = None
) -> SaveWorkspace:
    """Open the independent workspace; a loaded map is an optional convenience."""
    return SaveWorkspace(parent, initial_path=initial_path, map_data=map_data)


__all__ = ("SaveWorkspace", "open_save_workspace")
