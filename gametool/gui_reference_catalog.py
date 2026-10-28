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


def _source_lines(result: ReferenceSearchResult, source_ids=None) -> list[str]:
    lines: list[str] = []
    for source in result.sources:
        if source_ids is not None and source.id not in source_ids:
            continue
        lines.extend(
            (
                source.path,
                "来源ID: " + source.id,
                "来源状态: " + source.state,
                "归档成员: " + (source.member_path or "无独立成员"),
                "SHA-256: " + source.sha256,
                "容器 SHA-256: " + (source.container_sha256 or "不适用"),
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
    return lines


def _scope_lines(result: ReferenceSearchResult) -> list[str]:
    lines: list[str] = []
    for scope in result.map_scopes:
        lines.extend(
            (
                f"范围: {scope.scope} · {scope.name or '未记录名称'}",
                "读取状态: " + ("完整" if scope.complete else "不完整，请核对诊断"),
                "地图文件: " + scope.archive_path,
                "成员路径: " + (scope.member_path or "容器自身"),
                "范围 SHA-256: " + scope.sha256,
                "已确认分类数: "
                + "；".join(
                    f"{category} {count}" for category, count in scope.category_counts
                ),
            )
        )
        if scope.shared_scope:
            lines.append("共享对象范围: " + scope.shared_scope)
        lines.extend(
            f"共享引用: {category} [{code}]"
            for category, code in scope.shared_references
        )
        lines.extend("范围诊断: " + diagnostic for diagnostic in scope.diagnostics)
        lines.append("")
    return lines


def _catalog_text(result: ReferenceSearchResult) -> str:
    lines = [
        "== 详情 ==",
        "来源读取: "
        + ("完整" if result.catalog_complete else "不完整；保留已确认记录"),
        f"显示 {len(result.records)} / 匹配 {result.matched}；本地已确认 {result.total} 条",
    ]
    if result.map_path:
        lines.append("所选地图: " + result.map_path)
    lines.extend("输入文件: " + path for path in result.input_files)
    lines.extend(
        f"来源范围计数: {scope} {count}" for scope, count in result.source_counts
    )
    if not result.records:
        lines.extend(("未找到符合筛选的记录。", *result.recovery))
    lines.extend(("", "== 原始记录 ==", "选中左侧记录查看完整字段与原始记录。"))
    lines.extend(("", "== 来源 ==", *_scope_lines(result), *_source_lines(result)))
    lines.extend(("== 诊断 ==", *result.diagnostics))
    if not result.catalog_complete and not result.diagnostics:
        lines.append("来源不完整；请核对上方每个范围的读取状态。")
    elif not result.diagnostics:
        lines.append("本次来源读取完整；静态目录不证明当前游戏的可用性或实时字段值。")
    return "\n".join(lines)


def _detail_text(result: ReferenceSearchResult, selected: int) -> str:
    record = result.records[selected]
    lines = ["== 详情 ==", format_reference_record(record), "", "== 原始记录 =="]
    lines.append(
        json.dumps(record.raw_rows, ensure_ascii=False, indent=2)
        if record.raw_rows
        else "本条为项目静态定义；完整原始文件见来源台账，未反推未记录的字段。"
    )
    lines.extend(("", "== 来源 =="))
    lines.extend(_source_lines(result, record.sources))
    if result.map_scopes:
        lines.append("全部地图/章节分类计数与诊断见「来源总览」。")
    lines.extend(("== 诊断 ==", *record.diagnostics, *result.diagnostics))
    if not result.catalog_complete and not result.diagnostics:
        lines.append("来源不完整；保留已确认记录，请在来源总览核对范围诊断。")
    elif not record.diagnostics and not result.diagnostics:
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
                if key in {"pack_dir", "profile_json", "map_path"}
                and isinstance(value, str)
            }
            if isinstance(data, dict)
            else {}
        )
    except OSError, ValueError:
        return {}  # fail-open: malformed reference memory cannot block browsing.


def _save_reference_memory(
    pack_dir: str, profile_json: str, map_path: str = ""
) -> None:
    try:
        path = gamexray_cache_root() / "gui-query-memo" / "reference-settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "pack_dir": pack_dir,
                    "profile_json": profile_json,
                    "map_path": map_path,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError, UnicodeError:
        pass  # fail-open: a read-only cache still permits the full reference UI.


def _load_id_sources() -> tuple[str, ...]:
    """Restore only explicitly selected local sources, independently of packs."""
    try:
        payload = json.loads(
            (
                gamexray_cache_root() / "gui-query-memo" / "reference-id-sources.json"
            ).read_text(encoding="utf-8")
        )
    except OSError, ValueError:
        return ()
    if not isinstance(payload, list) or any(
        not isinstance(value, str) or not value for value in payload
    ):
        return ()
    return tuple(dict.fromkeys(payload))


def _save_id_sources(paths: tuple[str, ...]) -> None:
    try:
        destination = (
            gamexray_cache_root() / "gui-query-memo" / "reference-id-sources.json"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(list(paths), ensure_ascii=False), encoding="utf-8"
        )
    except OSError, UnicodeError:
        pass  # Source memory is optional; a read-only cache cannot block queries.


def open_reference_catalog_dialog(
    parent,
    pack_dir: str | Path | None = None,
    *,
    map_path: str | Path | None = None,
    id_tables: tuple[str, ...] | None = None,
) -> None:
    """Open the complete local reference; a pack and running game are optional."""
    ReferenceCatalogWindow(parent, pack_dir, map_path=map_path, id_tables=id_tables)


class ReferenceCatalogWindow(ctk.CTkToplevel, GuiWorkerHostMixin):
    def __init__(
        self,
        parent,
        pack_dir: str | Path | None = None,
        *,
        map_path: str | Path | None = None,
        id_tables: tuple[str, ...] | None = None,
    ) -> None:
        if map_path and pack_dir:
            raise ValueError("地图与知识包目录不能同时选择")
        super().__init__(parent)
        self._closed = False
        self._busy = False
        self._query_generation = 0
        self._result: ReferenceSearchResult | None = None
        self._result_request: tuple[object, ...] | None = None
        self._source_controls: list[ctk.CTkButton] = []
        self._input_controls = []
        self._source_changing = False
        self._find_pos = "1.0"
        self._find_keyword = ""
        self._active_section = "详情"
        self._render_id: str | None = None
        self._detail_content = ""
        self._id_tables = _load_id_sources() if id_tables is None else id_tables
        self._init_gui_worker_host()
        initial_source = map_path or pack_dir
        label = Path(initial_source).name if initial_source else "本地基础目录"
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
        memory = _load_reference_memory()
        remembered_map = (
            str(map_path)
            if map_path is not None
            else ("" if pack_dir is not None else memory.get("map_path", ""))
        )
        remembered_pack = (
            str(pack_dir)
            if pack_dir is not None
            else (
                ""
                if map_path is not None or remembered_map
                else memory.get("pack_dir", "")
            )
        )
        self._map_var = tk.StringVar(self, value=remembered_map)
        self._pack_var = tk.StringVar(self, value=remembered_pack)
        map_bar = ctk.CTkFrame(self, fg_color=CARD)
        map_bar.pack(fill="x", padx=12, pady=(0, 6))
        self._map_entry = ctk.CTkEntry(
            map_bar,
            textvariable=self._map_var,
            placeholder_text="可直接选地图 / 战役 .w3x / .w3m / .w3n；读取完整对象与章节来源",
        )
        self._map_entry.pack(side="left", fill="x", expand=True, padx=8, pady=8)
        self._map_button = ctk.CTkButton(
            map_bar, text="选地图", width=90, command=self._choose_map
        )
        self._map_button.pack(side="left", padx=(0, 6))
        self._clear_source_button = ctk.CTkButton(
            map_bar, text="清空地图 / 包", width=110, command=self._clear_source
        )
        self._clear_source_button.pack(side="left", padx=(0, 8))
        self._source_controls.extend((self._map_button, self._clear_source_button))
        pack_bar = ctk.CTkFrame(self, fg_color=CARD)
        pack_bar.pack(fill="x", padx=12, pady=(0, 6))
        self._pack_entry = ctk.CTkEntry(
            pack_bar,
            textvariable=self._pack_var,
            placeholder_text="可选知识包目录；与地图互斥，均留空看基础目录与版本档案",
        )
        self._pack_entry.pack(side="left", fill="x", expand=True, padx=8, pady=8)
        self._pack_button = ctk.CTkButton(
            pack_bar, text="选知识包", width=90, command=self._choose_pack
        )
        self._pack_button.pack(side="left", padx=(0, 8))
        self._source_controls.append(self._pack_button)
        profile_bar = ctk.CTkFrame(self, fg_color=CARD)
        profile_bar.pack(fill="x", padx=12, pady=(0, 6))
        self._profile_entry = ctk.CTkEntry(
            profile_bar,
            placeholder_text="可选纯数据 JSON 档案；仅验证字段/偏移声明，不连接游戏",
        )
        self._profile_entry.pack(side="left", fill="x", expand=True, padx=8, pady=8)
        self._profile_entry.insert(0, memory.get("profile_json", ""))
        self._profile_button = ctk.CTkButton(
            profile_bar, text="选 JSON 档案", width=100, command=self._choose_profile
        )
        self._profile_button.pack(side="left", padx=(0, 8))
        self._source_controls.append(self._profile_button)
        id_bar = ctk.CTkFrame(self, fg_color=CARD)
        id_bar.pack(fill="x", padx=12, pady=(0, 6))
        self._id_sources_entry = ctk.CTkEntry(
            id_bar,
            placeholder_text="可选盒子兼容 ID 文本；外部名称与地图证据分别保留",
        )
        self._id_sources_entry.pack(side="left", fill="x", expand=True, padx=8, pady=8)
        self._id_controls: list[ctk.CTkButton] = []
        for label, command in (
            ("加 ID 文件", self._choose_id_files),
            ("加 ID 目录", self._choose_id_directory),
            ("清空 ID", self._clear_id_sources),
        ):
            button = ctk.CTkButton(id_bar, text=label, width=85, command=command)
            button.pack(side="left", padx=(0, 6))
            self._id_controls.append(button)
        self._render_id_sources()
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
        kind_menu = ctk.CTkOptionMenu(
            filters,
            variable=self._kind,
            values=["all", "objects", "fields", "versions"],
            width=110,
        )
        kind_menu.pack(side="left", padx=8, pady=7)
        self._category = ctk.StringVar(value=_SESSION.get("category", "全部"))
        category_menu = ctk.CTkOptionMenu(
            filters, variable=self._category, values=["全部", *OBJECT_TABLES], width=110
        )
        category_menu.pack(side="left", padx=(0, 8))
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
        self._overview_button = ctk.CTkButton(
            filters,
            text="来源总览",
            width=90,
            command=self._show_overview,
            state="disabled",
        )
        self._overview_button.pack(side="left", padx=(0, 8))
        self._input_controls = [
            self._map_entry,
            self._pack_entry,
            self._profile_entry,
            self._query_entry,
            self._build_entry,
            self._source_entry,
            kind_menu,
            category_menu,
        ]
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
        horizontal = tk.Scrollbar(
            listing, orient="horizontal", command=self._list.xview
        )
        self._list.configure(
            yscrollcommand=scrollbar.set, xscrollcommand=horizontal.set
        )
        scrollbar.pack(side="right", fill="y")
        horizontal.pack(side="bottom", fill="x")
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
        self._source_traces = (
            (
                self._map_var,
                self._map_var.trace_add(
                    "write", lambda *_args: self._source_changed("map")
                ),
            ),
            (
                self._pack_var,
                self._pack_var.trace_add(
                    "write", lambda *_args: self._source_changed("pack")
                ),
            ),
        )
        self._startup_id: str | None = self.after(0, self._run)

    def _source_changed(self, kind: str) -> None:
        if self._closed or self._source_changing:
            return
        self._source_changing = True
        try:
            if kind == "map" and self._map_var.get().strip():
                self._pack_var.set("")
            elif kind == "pack" and self._pack_var.get().strip():
                self._map_var.set("")
        finally:
            self._source_changing = False
        self._cancel()
        self._result_request = None
        self._export_button.configure(state="disabled")
        self._status.configure(text="来源已更改；请检索 / 刷新后查看和导出本次来源。")

    def _choose_map(self) -> None:
        if self._closed or self._busy:
            return
        path = filedialog.askopenfilename(
            parent=self,
            title="选择 Warcraft III 地图或战役",
            filetypes=[("地图与战役", "*.w3x *.w3m *.w3n"), ("所有文件", "*.*")],
        )
        if path and not self._closed and not self._busy:
            self._map_var.set(path)
            self._run()

    def _clear_source(self) -> None:
        if self._closed or self._busy:
            return
        self._map_var.set("")
        self._pack_var.set("")
        self._run()

    def _choose_pack(self) -> None:
        if self._closed or self._busy:
            return
        path = filedialog.askdirectory(parent=self, title="选择 GameXRay 知识包目录")
        if path and not self._closed and not self._busy:
            self._pack_var.set(path)
            self._run()

    def _choose_profile(self) -> None:
        if self._closed or self._busy:
            return
        path = filedialog.askopenfilename(
            parent=self, title="选择纯数据只读档案", filetypes=[("JSON", "*.json")]
        )
        if path and not self._closed and not self._busy:
            self._profile_entry.delete(0, "end")
            self._profile_entry.insert(0, path)
            self._run()

    def _render_id_sources(self) -> None:
        self._id_sources_entry.configure(state="normal")
        self._id_sources_entry.delete(0, "end")
        self._id_sources_entry.insert(0, " | ".join(self._id_tables))
        self._id_sources_entry.configure(state="disabled")

    def _add_id_sources(self, paths: tuple[str, ...]) -> None:
        if self._closed or self._busy or not paths:
            return
        self._id_tables = tuple(dict.fromkeys((*self._id_tables, *paths)))
        self._render_id_sources()
        _save_id_sources(self._id_tables)
        self._run()

    def _choose_id_files(self) -> None:
        if self._closed or self._busy:
            return
        paths = filedialog.askopenfilenames(
            parent=self,
            title="选择盒子兼容 ID 文本（保留完整外部来源）",
            filetypes=[("ID 文本", "*.txt"), ("所有文件", "*.*")],
        )
        self._add_id_sources(tuple(paths))

    def _choose_id_directory(self) -> None:
        if self._closed or self._busy:
            return
        path = filedialog.askdirectory(parent=self, title="选择盒子兼容 ID 目录")
        if path:
            self._add_id_sources((path,))

    def _clear_id_sources(self) -> None:
        if self._closed or self._busy:
            return
        self._id_tables = ()
        self._render_id_sources()
        _save_id_sources(())
        self._run()

    def _set_id_controls(self, state: str) -> None:
        for control in (
            *self._id_controls,
            *self._source_controls,
            *self._input_controls,
        ):
            control.configure(state=state)

    def _request_state(self) -> tuple[object, ...]:
        return (
            self._map_entry.get().strip(),
            self._pack_entry.get().strip(),
            self._profile_entry.get().strip(),
            self._id_tables,
            self._query_entry.get(),
            self._kind.get(),
            self._category.get(),
            self._build_entry.get().strip(),
            self._source_entry.get().strip(),
        )

    def _result_is_current(self) -> bool:
        return (
            self._result is not None and self._result_request == self._request_state()
        )

    def _query_current(self, generation: int, request: tuple[object, ...]) -> bool:
        return (
            not self._closed
            and self._busy
            and generation == self._query_generation
            and request == self._request_state()
        )

    def _deliver_query(
        self,
        result: ReferenceSearchResult,
        generation: int,
        request: tuple[object, ...],
    ) -> None:
        if self._query_current(generation, request):
            self._result_request = request
            self._finish(result)

    def _deliver_failure(
        self, error: str, generation: int, request: tuple[object, ...]
    ) -> None:
        if self._query_current(generation, request):
            self._failed(error)

    def _progress(
        self, text: str, generation: int, request: tuple[object, ...]
    ) -> None:
        if self._query_current(generation, request):
            self._status.configure(text=text)

    def _run(self) -> None:
        self._startup_id = None
        if self._closed or self._busy:
            return
        map_path = self._map_entry.get().strip()
        pack = self._pack_entry.get().strip()
        profile = self._profile_entry.get().strip()
        id_tables = self._id_tables
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
        _save_reference_memory(pack, profile, map_path)
        self.title(
            "离线字段与版本参考 — "
            + (Path(map_path or pack).name if map_path or pack else "本地基础目录")
        )
        self._busy = True
        self._query_generation += 1
        generation = self._query_generation
        request = self._request_state()
        self._result_request = None
        self._cancel_gui_worker_group("reference-detail")
        self._cancel_gui_worker_group("reference-export")
        self._run_button.configure(state="disabled")
        self._export_button.configure(state="disabled")
        self._set_id_controls("disabled")
        self._status.configure(text="后台读取全量目录并核对来源；可继续查看已有详情…")

        def work(ticket: GuiWorkerTicket) -> None:
            def progress(text: str) -> None:
                self._post_gui_worker(
                    ticket, lambda: self._progress(text, generation, request)
                )

            try:
                catalog = load_reference_catalog(
                    pack or None,
                    map_path=map_path or None,
                    profile_json=profile or None,
                    id_tables=id_tables,
                    cancelled=ticket.cancellation.is_set,
                    progress=progress,
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
                self._post_gui_worker(
                    ticket, lambda: self._deliver_query(result, generation, request)
                )
            except Exception as exc:  # BROAD_EXCEPT_OK - boundary reports a failed background query without killing Tk.
                error = str(exc)
                self._post_gui_worker(
                    ticket, lambda: self._deliver_failure(error, generation, request)
                )

        self._start_gui_worker("reference-query", work, replace=True)

    def _finish(self, result: ReferenceSearchResult) -> None:
        # The user may have selected an old record while this query ran.
        # That worker belongs to the old view, including when this new view
        # has no selected record that would otherwise replace its generation.
        self._cancel_gui_worker_group("reference-detail")
        self._busy = False
        self._run_button.configure(state="normal")
        self._set_id_controls("normal")
        self._result = result
        self._overview_button.configure(state="normal")
        self._export_button.configure(state="normal")
        self._list.delete(0, "end")
        if result.records:
            self._list.insert(
                "end",
                *(
                    f"[{record.id}] {record.label} · {record.category or record.kind} · {record.scope}"
                    for record in result.records
                ),
            )
            self._list.selection_set(0)
            self._show_selected()
        else:
            self._set_output(_catalog_text(result))
        suffix = (
            f"；来源诊断 {len(result.diagnostics)} 条，请在详情核对"
            if result.diagnostics
            else ""
        )
        self._status.configure(
            text=f"已显示 {len(result.records)} / 匹配 {result.matched}；本地已确认 {result.total} 条；"
            + (
                "来源读取完整"
                if result.catalog_complete
                else "来源不完整，保留已确认记录"
            )
            + suffix
        )

    def _failed(self, error: str) -> None:
        self._cancel_gui_worker_group("reference-detail")
        self._busy = False
        self._run_button.configure(state="normal")
        self._set_id_controls("normal")
        self._result_request = None
        self._export_button.configure(state="disabled")
        self._status.configure(
            text="读取失败；请检查地图 / 知识包后重试，或清空地图 / 包查基础参考。"
        )
        self._set_output("== 诊断 ==\n" + error)

    def _cancel(self) -> None:
        if self._closed:
            return
        self._query_generation += 1
        self._cancel_gui_worker_group("reference-query")
        self._cancel_gui_worker_group("reference-detail")
        self._cancel_gui_worker_group("reference-export")
        if self._render_id is not None:
            self.after_cancel(self._render_id)
            self._render_id = None
        self._busy = False
        self._run_button.configure(state="normal")
        self._set_id_controls("normal")
        self._export_button.configure(
            state="normal" if self._result_is_current() else "disabled"
        )
        self._status.configure(
            text="已取消本次交付；可重新选择来源并检索，已有列表为上次结果。"
        )

    def _show_overview(self) -> None:
        if self._closed or self._result is None:
            return
        result, generation = self._result, self._query_generation

        def work(ticket: GuiWorkerTicket) -> None:
            text = _catalog_text(result)
            self._post_gui_worker(
                ticket, lambda: self._deliver_detail(text, result, generation)
            )

        self._start_gui_worker("reference-detail", work, replace=True)

    def _deliver_detail(
        self, text: str, result: ReferenceSearchResult, generation: int
    ) -> None:
        if (
            not self._closed
            and self._result is result
            and generation == self._query_generation
        ):
            self._set_output(text)

    def _show_selected(self) -> None:
        selection = self._list.curselection()
        if self._result is None or not selection:
            return
        result, selected = self._result, selection[0]
        generation = self._query_generation

        def work(ticket: GuiWorkerTicket) -> None:
            text = _detail_text(result, selected)
            self._post_gui_worker(
                ticket, lambda: self._deliver_detail(text, result, generation)
            )

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
        if self._closed or self._busy or result is None:
            return
        if not self._result_is_current():
            self._export_button.configure(state="disabled")
            self._status.configure(
                text="筛选或来源已更改；请检索 / 刷新后导出当前结果。"
            )
            return
        generation = self._query_generation
        path = filedialog.asksaveasfilename(
            parent=self,
            title="导出全部匹配与完整诊断",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("JSON", "*.json"), ("Text", "*.txt")],
        )
        if (
            not path
            or self._closed
            or self._busy
            or generation != self._query_generation
            or self._result is not result
            or not self._result_is_current()
        ):
            return
        self._export_button.configure(state="disabled")

        def work(ticket: GuiWorkerTicket) -> None:
            try:
                write_reference_export(path, result)
                self._post_gui_worker(
                    ticket,
                    lambda: self._export_finished(
                        path, "", generation=generation, result=result
                    ),
                )
            except (OSError, ValueError) as exc:
                error = str(exc)
                self._post_gui_worker(
                    ticket,
                    lambda: self._export_finished(
                        path, error, generation=generation, result=result
                    ),
                )

        self._start_gui_worker("reference-export", work, replace=True)

    def _export_finished(
        self,
        path: str,
        error: str,
        *,
        generation: int,
        result: ReferenceSearchResult,
    ) -> None:
        if (
            self._closed
            or self._query_generation != generation
            or self._result is not result
            or not self._result_is_current()
        ):
            return
        self._export_button.configure(state="normal")
        if error:
            messagebox.showerror("参考报告导出失败", error, parent=self)
        else:
            self._status.configure(text="已导出全部匹配与完整来源诊断: " + path)

    def destroy(self) -> None:
        if self._closed:
            return
        _save_reference_memory(
            self._pack_entry.get().strip(),
            self._profile_entry.get().strip(),
            self._map_entry.get().strip(),
        )
        for variable, trace in self._source_traces:
            variable.trace_remove("write", trace)
        self._closed = True
        from .gui_tk_callbacks import cancel_widget_callbacks

        cancel_widget_callbacks(self)
        if self._startup_id is not None:
            self.after_cancel(self._startup_id)
            self._startup_id = None
        if self._render_id is not None:
            self.after_cancel(self._render_id)
            self._render_id = None
        self._shutdown_gui_worker_host(0)
        super().destroy()
