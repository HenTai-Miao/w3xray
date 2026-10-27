"""Responsive offline object/field/build reference browser."""

from __future__ import annotations

import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .cache_root import gamexray_cache_root
from .gui_pack_query import bind_geometry_memory
from .gui_worker_host import GuiWorkerHostMixin
from .gui_worker_registry import GuiWorkerTicket
from .pack_query_objects import OBJECT_TABLES
from .reference_catalog import load_reference_catalog, search_reference_catalog
from .reference_cli import format_reference_record, write_reference_export
from .reference_models import ReferenceSearchResult
from .theme import BG, CARD, FONT, PANEL, TEXT, TEXT_STRONG

_SESSION: dict[str, str] = {}


def _detail_text(result: ReferenceSearchResult, selected: int) -> str:
    record = result.records[selected]
    sources = [source for source in result.sources if source.id in record.sources]
    lines = ["== 详情 ==", format_reference_record(record), "", "== 原始记录 =="]
    lines.append(
        json.dumps(record.raw_rows, ensure_ascii=False, indent=2)
        if record.raw_rows
        else "本条为项目静态定义；完整原始文件见来源台账，未反推未记录的字段。"
    )
    lines.extend(("", "== 来源 =="))
    for source in sources:
        lines.extend(
            (
                source.path,
                "SHA-256: " + source.sha256,
                "指纹边界: " + source.fingerprint_basis,
                "磁盘源码独立观测: "
                + (source.source_file_sha256 or "无独立文件")
                + " · "
                + (source.source_file_state or "不适用"),
                "build: " + source.build,
                source.provenance,
                "",
            )
        )
    lines.extend(("== 诊断 ==", *record.diagnostics, *result.diagnostics))
    if not record.diagnostics and not result.diagnostics:
        lines.append("本次来源读取完整；静态目录不证明当前游戏的可用性或实时字段值。")
    return "\n".join(lines)


def _load_reference_memory() -> dict[str, str]:
    try:
        data = json.loads(
            (
                gamexray_cache_root() / "gui-query-memo" / "reference-settings.json"
            ).read_text(encoding="utf-8")
        )
        return (
            {
                key: value
                for key, value in data.items()
                if key in {"pack_dir", "profile_json"} and isinstance(value, str)
            }
            if isinstance(data, dict)
            else {}
        )
    except OSError, ValueError:
        return {}  # fail-open: malformed reference memory cannot block browsing.


def _save_reference_memory(pack_dir: str, profile_json: str) -> None:
    try:
        path = gamexray_cache_root() / "gui-query-memo" / "reference-settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"pack_dir": pack_dir, "profile_json": profile_json}, ensure_ascii=False
            ),
            encoding="utf-8",
        )
    except OSError, UnicodeError:
        pass  # fail-open: a read-only cache still permits the full reference UI.


def open_reference_catalog_dialog(parent, pack_dir: str | Path | None = None) -> None:
    """Open the complete local reference; a pack and running game are optional."""
    ReferenceCatalogWindow(parent, pack_dir)


class ReferenceCatalogWindow(ctk.CTkToplevel, GuiWorkerHostMixin):
    def __init__(self, parent, pack_dir: str | Path | None = None) -> None:
        super().__init__(parent)
        self._closed = False
        self._busy = False
        self._result: ReferenceSearchResult | None = None
        self._find_pos = "1.0"
        self._find_keyword = ""
        self._active_section = "详情"
        self._render_id: str | None = None
        self._detail_content = ""
        self._init_gui_worker_host()
        label = Path(pack_dir).name if pack_dir else "本地基础目录"
        self.title(f"离线字段与版本参考 — {label}")
        self.configure(fg_color=BG)
        self.transient(parent)
        self.grab_set()
        bind_geometry_memory(self, "reference-catalog", "1120x760")
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _event: self.destroy())
        for sequence in ("<Control-f>", "<Control-F>"):
            self.bind(sequence, lambda _event: self._find_entry.focus_set())
        for sequence in ("<Control-a>", "<Control-A>"):
            self.bind(sequence, self._select_all)
        for sequence in ("<Control-r>", "<Control-R>"):
            self.bind(sequence, lambda _event: self._run())

        heading = ctk.CTkLabel(
            self,
            text="完整本地目录 · 静态定义与导出值证据 · 双击记录查看全部字段/来源",
            font=(FONT, 13, "bold"),
            text_color=TEXT_STRONG,
        )
        heading.pack(anchor="w", padx=14, pady=(12, 6))
        pack_bar = ctk.CTkFrame(self, fg_color=CARD)
        pack_bar.pack(fill="x", padx=12, pady=(0, 6))
        self._pack_entry = ctk.CTkEntry(
            pack_bar, placeholder_text="可选知识包目录；留空看基础目录与版本档案"
        )
        self._pack_entry.pack(side="left", fill="x", expand=True, padx=8, pady=8)
        memory = _load_reference_memory()
        remembered = (
            str(pack_dir) if pack_dir is not None else memory.get("pack_dir", "")
        )
        self._pack_entry.insert(0, remembered)
        ctk.CTkButton(
            pack_bar, text="选知识包", width=90, command=self._choose_pack
        ).pack(side="left", padx=(0, 8))
        profile_bar = ctk.CTkFrame(self, fg_color=CARD)
        profile_bar.pack(fill="x", padx=12, pady=(0, 6))
        self._profile_entry = ctk.CTkEntry(
            profile_bar,
            placeholder_text="可选纯数据 JSON 档案；仅验证字段/偏移声明，不连接游戏",
        )
        self._profile_entry.pack(side="left", fill="x", expand=True, padx=8, pady=8)
        self._profile_entry.insert(0, memory.get("profile_json", ""))
        ctk.CTkButton(
            profile_bar, text="选 JSON 档案", width=100, command=self._choose_profile
        ).pack(side="left", padx=(0, 8))
        bar = ctk.CTkFrame(self, fg_color=CARD)
        bar.pack(fill="x", padx=12, pady=(0, 6))
        self._query_entry = ctk.CTkEntry(
            bar, placeholder_text='关键词/Boolean（&&、||、%、="精准词"）；空=全部'
        )
        self._query_entry.pack(side="left", fill="x", expand=True, padx=8, pady=8)
        self._query_entry.insert(0, _SESSION.get("query", ""))
        self._query_entry.bind("<Return>", lambda _event: self._run())
        self._run_button = ctk.CTkButton(
            bar, text="检索 / 刷新", width=100, command=self._run
        )
        self._run_button.pack(side="left", padx=(0, 6))
        ctk.CTkButton(bar, text="取消", width=60, command=self._cancel).pack(
            side="left", padx=(0, 6)
        )
        self._export_button = ctk.CTkButton(
            bar, text="导出全部匹配", width=110, command=self._export, state="disabled"
        )
        self._export_button.pack(side="left", padx=(0, 8))
        filters = ctk.CTkFrame(self, fg_color=CARD)
        filters.pack(fill="x", padx=12, pady=(0, 6))
        self._kind = ctk.StringVar(value=_SESSION.get("kind", "all"))
        ctk.CTkOptionMenu(
            filters,
            variable=self._kind,
            values=["all", "objects", "fields", "versions"],
            width=110,
        ).pack(side="left", padx=8, pady=7)
        self._category = ctk.StringVar(value=_SESSION.get("category", "全部"))
        ctk.CTkOptionMenu(
            filters, variable=self._category, values=["全部", *OBJECT_TABLES], width=110
        ).pack(side="left", padx=(0, 8))
        self._build_entry = ctk.CTkEntry(
            filters, placeholder_text="精确 build（空=全部）", width=215
        )
        self._build_entry.pack(side="left", padx=(0, 8))
        self._build_entry.insert(0, _SESSION.get("build", ""))
        self._source_entry = ctk.CTkEntry(
            filters, placeholder_text="来源路径/名称/SHA-256（空=全部）"
        )
        self._source_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._source_entry.insert(0, _SESSION.get("source", ""))
        self._status = ctk.CTkLabel(
            self, text="准备加载完整目录…", anchor="w", text_color=TEXT
        )
        self._status.pack(fill="x", padx=14, pady=(0, 5))

        content = tk.PanedWindow(
            self, orient="horizontal", sashwidth=7, bg=BG, borderwidth=0
        )
        content.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        listing = tk.Frame(content, bg=CARD)
        self._list = tk.Listbox(
            listing,
            exportselection=False,
            font=(FONT, 10),
            activestyle="none",
            bg=CARD,
            fg=TEXT,
            borderwidth=0,
        )
        scrollbar = tk.Scrollbar(listing, orient="vertical", command=self._list.yview)
        self._list.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self._list.pack(fill="both", expand=True)
        self._list.bind("<<ListboxSelect>>", lambda _event: self._show_selected())
        self._list.bind("<Double-Button-1>", lambda _event: self._show_selected())
        content.add(listing, minsize=230, width=340)
        details = ctk.CTkFrame(content, fg_color=CARD)
        content.add(details, minsize=300)
        navigation = ctk.CTkFrame(details, fg_color="transparent")
        navigation.pack(fill="x", padx=6, pady=(6, 3))
        self._sections: dict[str, ctk.CTkButton] = {}
        for section in ("详情", "原始记录", "来源", "诊断"):
            button = ctk.CTkButton(
                navigation,
                text=section,
                width=72,
                command=lambda key=section: self._jump(key),
            )
            button.pack(side="left", padx=(0, 5))
            self._sections[section] = button
        self._output = ctk.CTkTextbox(
            details, wrap="none", font=("Consolas", 11), fg_color=PANEL, text_color=TEXT
        )
        self._output.pack(fill="both", expand=True, padx=6, pady=(0, 5))
        self._output.configure(state="disabled")
        find_bar = ctk.CTkFrame(details, fg_color="transparent")
        find_bar.pack(fill="x", padx=6, pady=(0, 6))
        self._find_entry = ctk.CTkEntry(
            find_bar, placeholder_text="Ctrl+F 详情内搜；回车下一处（到尾回卷）"
        )
        self._find_entry.pack(side="left", fill="x", expand=True)
        self._find_entry.bind("<Return>", self._find_next)
        ctk.CTkButton(find_bar, text="下一处", width=75, command=self._find_next).pack(
            side="left", padx=(5, 0)
        )
        self._output.tag_config(
            "reference-hit", background="#8a6d00", foreground="white"
        )
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="复制选中", command=self._copy_selected)
        menu.add_command(
            label="复制全部详情",
            command=lambda: self._copy(self._detail_content),
        )
        menu.add_command(label="导出全部匹配 (.md/.json)", command=self._export)
        self._output.bind(
            "<Button-3>", lambda event: menu.tk_popup(event.x_root, event.y_root)
        )
        self._startup_id: str | None = self.after(0, self._run)

    def _choose_pack(self) -> None:
        path = filedialog.askdirectory(parent=self, title="选择 GameXRay 知识包目录")
        if path:
            self._pack_entry.delete(0, "end")
            self._pack_entry.insert(0, path)
            self._run()

    def _choose_profile(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title="选择纯数据只读档案", filetypes=[("JSON", "*.json")]
        )
        if path:
            self._profile_entry.delete(0, "end")
            self._profile_entry.insert(0, path)
            self._run()

    def _run(self) -> None:
        self._startup_id = None
        if self._closed or self._busy:
            return
        pack = self._pack_entry.get().strip()
        profile = self._profile_entry.get().strip()
        query = self._query_entry.get()
        kind = self._kind.get()
        category = self._category.get()
        build, source = (
            self._build_entry.get().strip(),
            self._source_entry.get().strip(),
        )
        _SESSION.update(
            query=query, kind=kind, category=category, build=build, source=source
        )
        _save_reference_memory(pack, profile)
        self.title(
            "离线字段与版本参考 — " + (Path(pack).name if pack else "本地基础目录")
        )
        self._busy = True
        self._cancel_gui_worker_group("reference-detail")
        self._run_button.configure(state="disabled")
        self._status.configure(text="后台读取全量目录并核对来源；可继续查看已有详情…")

        def work(ticket: GuiWorkerTicket) -> None:
            try:
                catalog = load_reference_catalog(
                    pack or None, profile_json=profile or None
                )
                if ticket.cancellation.is_set():
                    return
                result = search_reference_catalog(
                    catalog,
                    query,
                    kind=kind,
                    category="" if category == "全部" else category,
                    build=build,
                    source=source,
                )
                self._post_gui_worker(ticket, lambda: self._finish(result))
            except Exception as exc:  # BROAD_EXCEPT_OK - boundary reports a failed background query without killing Tk.
                error = str(exc)
                self._post_gui_worker(ticket, lambda: self._failed(error))

        self._start_gui_worker("reference-query", work, replace=True)

    def _finish(self, result: ReferenceSearchResult) -> None:
        # The user may have selected an old record while this query ran.
        # That worker belongs to the old view, including when this new view
        # has no selected record that would otherwise replace its generation.
        self._cancel_gui_worker_group("reference-detail")
        self._busy = False
        self._run_button.configure(state="normal")
        self._result = result
        self._export_button.configure(state="normal")
        self._list.delete(0, "end")
        if result.records:
            self._list.insert(
                "end",
                *(
                    f"[{record.id}] {record.label} · {record.category or record.kind}"
                    for record in result.records
                ),
            )
            self._list.selection_set(0)
            self._show_selected()
        else:
            self._set_output(
                "== 详情 ==\n未找到符合筛选的记录。\n"
                + "\n".join(result.recovery)
                + "\n\n== 诊断 ==\n"
                + "\n".join(result.diagnostics)
            )
        suffix = (
            f"；来源诊断 {len(result.diagnostics)} 条，请在详情核对"
            if result.diagnostics
            else ""
        )
        self._status.configure(
            text=f"完整列表 {len(result.records)} / 匹配 {result.matched}；本地已确认 {result.total} 条{suffix}"
        )

    def _failed(self, error: str) -> None:
        self._cancel_gui_worker_group("reference-detail")
        self._busy = False
        self._run_button.configure(state="normal")
        self._status.configure(
            text="读取失败；可检查知识包目录后重试，或清空目录查基础参考。"
        )
        self._set_output("== 诊断 ==\n" + error)

    def _cancel(self) -> None:
        self._cancel_gui_worker_group("reference-query")
        self._busy = False
        self._run_button.configure(state="normal")
        self._status.configure(text="已取消本次交付；已有列表可继续查看或导出。")

    def _show_selected(self) -> None:
        selection = self._list.curselection()
        if self._result is None or not selection:
            return
        result, selected = self._result, selection[0]

        def work(ticket: GuiWorkerTicket) -> None:
            text = _detail_text(result, selected)
            self._post_gui_worker(ticket, lambda: self._set_output(text))

        self._start_gui_worker("reference-detail", work, replace=True)

    def _set_output(self, text: str) -> None:
        if self._render_id is not None:
            self.after_cancel(self._render_id)
            self._render_id = None
        self._detail_content = text
        self._find_pos, self._find_keyword = "1.0", ""
        self._output.configure(state="normal")
        self._output.delete("1.0", "end")
        self._output.tag_remove("reference-hit", "1.0", "end")
        self._output.configure(state="disabled")
        self._output.see("1.0")
        self._mark_section("详情" if "== 详情 ==" in text else "诊断")

        def append(offset: int) -> None:
            self._render_id = None
            self._output.configure(state="normal")
            # This is a delivery chunk, never a display/result ceiling: all
            # characters are scheduled, with Tk regaining control in between.
            end = offset + 32768
            self._output.insert("end", text[offset:end])
            self._output.configure(state="disabled")
            if end < len(text):
                self._render_id = self.after(1, lambda: append(end))

        append(0)

    def _mark_section(self, section: str) -> None:
        self._active_section = section
        for key, button in self._sections.items():
            button.configure(fg_color="#2b739c" if key == section else "#698b9d")

    def _jump(self, section: str) -> None:
        position = self._output._textbox.search(
            f"== {section} ==", "1.0", stopindex="end"
        )
        if position:
            self._output.see(position)
            self._mark_section(section)

    def _find_next(self, _event=None) -> str:
        keyword = self._find_entry.get()
        self._output.tag_remove("reference-hit", "1.0", "end")
        if keyword != self._find_keyword:
            self._find_pos = "1.0"
            self._find_keyword = keyword
        if not keyword:
            self._find_pos = "1.0"
            return "break"
        box = self._output._textbox
        position = box.search(keyword, self._find_pos, stopindex="end", nocase=True)
        if not position:
            position = box.search(keyword, "1.0", stopindex="end", nocase=True)
        if position:
            end = f"{position}+{len(keyword)}c"
            self._output.tag_add("reference-hit", position, end)
            self._output.see(position)
            self._find_pos = end
        return "break"

    def _select_all(self, _event=None) -> str:
        self._output.tag_add("sel", "1.0", "end-1c")
        self._output.focus_set()
        return "break"

    def _copy(self, value: str) -> None:
        if value:
            self.clipboard_clear()
            self.clipboard_append(value)

    def _copy_selected(self) -> None:
        try:
            self._copy(self._output.get("sel.first", "sel.last"))
        except tk.TclError:
            pass  # An empty selection is an intentional no-op.

    def _export(self) -> None:
        result = self._result
        if result is None:
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="导出全部匹配与完整诊断",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("JSON", "*.json"), ("Text", "*.txt")],
        )
        if not path:
            return
        self._export_button.configure(state="disabled")

        def work(ticket: GuiWorkerTicket) -> None:
            try:
                write_reference_export(path, result)
                self._post_gui_worker(ticket, lambda: self._export_finished(path, ""))
            except (OSError, ValueError) as exc:
                error = str(exc)
                self._post_gui_worker(
                    ticket, lambda: self._export_finished(path, error)
                )

        self._start_gui_worker("reference-export", work, replace=True)

    def _export_finished(self, path: str, error: str) -> None:
        self._export_button.configure(state="normal")
        if error:
            messagebox.showerror("参考报告导出失败", error, parent=self)
        else:
            self._status.configure(text="已导出全部匹配与完整来源诊断: " + path)

    def destroy(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._startup_id is not None:
            self.after_cancel(self._startup_id)
            self._startup_id = None
        if self._render_id is not None:
            self.after_cancel(self._render_id)
            self._render_id = None
        self._shutdown_gui_worker_host(0)
        super().destroy()
