"""live 探针 GUI 弹窗: 只读内存读取 → 输出区 + JSON 自动复制。

只读纪律: 背后是 live_cli.run_live_cli (ReadProcessMemory/PrintWindow 快照),
绝不注入、绝不写游戏内存。
"""

from __future__ import annotations

from .query_coordinates import coordinates_from_text
from .query_object_codes import code_from_text
from .gui_live_subprocess import (
    LiveProbeChild,
    build_live_probe_command,
    build_live_probe_environment,
)
from .gui_live_evidence import (
    LiveDialogMemory,
    format_live_details,
    item_records,
    object_query,
    parse_live_output,
    preferred_selection,
    record_label,
    selected_records,
    selection_status,
    unit_near_query,
)

from collections.abc import Callable, Mapping
import os
import pathlib
import re
import tkinter as tk
from tkinter import filedialog
import threading

import customtkinter as ctk

from .theme import BG, CARD, TEXT, TEXT_STRONG

_FONT = ("Microsoft YaHei UI", 11)
_SESSION_VIEWS: dict[str, LiveDialogMemory] = {}


class LiveProbeWindow(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        pack_dir: str | None,
        query_callback: "Callable[[str], None] | None" = None,
        pack_dir_provider: Callable[[], str | None] | None = None,
        *,
        auto_start: bool = True,
    ) -> None:
        super().__init__(master)
        self._probe_child: LiveProbeChild | None = None
        self._probe_start_id: str | None = None
        self._probe_poll_id: str | None = None
        self._probe_closed = False
        self._pack_dir = pack_dir
        self._pack_dir_provider = pack_dir_provider
        self._query_callback = query_callback
        self._report: Mapping[str, object] | None = None
        self._selected_rows: tuple[Mapping[str, object], ...] = ()
        self._item_rows: tuple[Mapping[str, object], ...] = ()
        self._selected_index: int | None = None
        self._item_index: int | None = None
        self._report_source = ""
        self._raw_report_text = "点击「开始探针」读取当前对局 (需游戏运行中)。"
        self._memory_key = str(pack_dir) if pack_dir else f"unbound@{id(master)}"
        pack_name = pathlib.Path(pack_dir).name if pack_dir else ""
        self.title(
            "live 探针 — 只读内存读取" + (f" · {pack_name}" if pack_name else "")
        )
        self.geometry("1120x760")
        self.minsize(920, 600)
        self.configure(fg_color=BG)
        self.transient(master)
        self.grab_set()
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Control-r>", lambda _e: self._start())
        # CapsLock 大写态变体 (Tk 绑定大小写敏感)
        self.bind("<Control-R>", lambda _e: self._start())
        from .gui_pack_query import bind_geometry_memory

        bind_geometry_memory(self, "gui-live-probe", "1120x760")

        header = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        header.pack(fill="x", padx=14, pady=(14, 8))
        ctk.CTkLabel(
            header,
            text="live 探针 (只读)",
            font=(*_FONT, "bold"),
            text_color=TEXT_STRONG,
        ).pack(side="left", padx=12, pady=8)
        ctk.CTkLabel(
            header,
            text="ReadProcessMemory 只读快照 · 不注入不写内存 · 输出尾部 JSON 自动复制",
            font=("Microsoft YaHei UI", 10),
            text_color=TEXT,
        ).pack(side="right", padx=12)

        bar = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        bar.pack(fill="x", padx=14, pady=(0, 8))
        self._probe_button = ctk.CTkButton(
            bar,
            text="开始探针 (Ctrl+R 重探)",
            width=110,
            font=_FONT,
            command=self._start,
        )
        self._probe_button.pack(side="left", padx=(12, 6), pady=8)
        self._map_entry = ctk.CTkEntry(
            bar,
            placeholder_text="地图路径可空 (空=自动定位正在使用的图)…",
            width=300,
            font=("Microsoft YaHei UI", 10),
        )
        self._map_entry.pack(side="left", padx=(0, 8))
        self._map_entry.insert(0, self._load_last_map_path())
        self._unit_entry = ctk.CTkEntry(
            bar,
            placeholder_text="单位过滤 (名/四码, 可空)…",
            width=170,
            font=("Microsoft YaHei UI", 10),
        )
        self._unit_entry.pack(side="left", padx=(0, 8))
        self._unit_entry.insert(0, self._load_last_unit_query())
        options_bar = ctk.CTkFrame(self, fg_color="transparent")
        options_bar.pack(fill="x", padx=14, pady=(0, 4))
        self._var_players = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            options_bar,
            text="玩家列表",
            variable=self._var_players,
            font=("Microsoft YaHei UI", 10),
        ).pack(side="left", padx=(0, 6))
        self._var_all_units = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            options_bar,
            text="全单位",
            variable=self._var_all_units,
            font=("Microsoft YaHei UI", 10),
        ).pack(side="left", padx=(0, 6))
        self._var_resources = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            options_bar,
            text="资源对齐 (自动差分)",
            variable=self._var_resources,
            font=("Microsoft YaHei UI", 10),
        ).pack(side="left", padx=(0, 6))
        self._copy_hint = ctk.CTkLabel(
            options_bar,
            text="",
            font=("Microsoft YaHei UI", 10),
            text_color=TEXT,
            anchor="w",
        )
        self._copy_hint.pack(side="left", padx=12, fill="x", expand=True)

        report_bar = ctk.CTkFrame(self, fg_color="transparent")
        report_bar.pack(fill="x", padx=14, pady=(0, 4))
        self._save_report_button = ctk.CTkButton(
            report_bar,
            text="保存结构化报告…",
            width=130,
            command=self._save_structured_report,
            state="disabled",
        )
        self._save_report_button.pack(side="left", padx=(0, 6))
        self._open_report_button = ctk.CTkButton(
            report_bar,
            text="打开离线报告…",
            width=130,
            command=self._open_structured_report,
        )
        self._open_report_button.pack(side="left", padx=(0, 6))
        self._compare_report_button = ctk.CTkButton(
            report_bar,
            text="与旧报告比较…",
            width=130,
            command=self._compare_structured_report,
            state="disabled",
        )
        self._compare_report_button.pack(side="left", padx=(0, 6))
        self._reference_button = ctk.CTkButton(
            report_bar,
            text="字段 / 版本参考",
            width=130,
            command=self._open_reference,
        )
        self._reference_button.pack(side="left", padx=(0, 6))
        self._report_label = ctk.CTkLabel(report_bar, text="尚未读取报告", anchor="w")
        self._report_label.pack(side="left", fill="x", expand=True)

        self._tabs = ctk.CTkTabview(self, command=self._reset_search)
        self._tabs.pack(fill="both", expand=True, padx=14, pady=(0, 6))
        evidence_tab = self._tabs.add("选中与证据")
        raw_tab = self._tabs.add("完整输出")
        compare_tab = self._tabs.add("离线比较")
        self._build_evidence_tab(evidence_tab)
        self._output = ctk.CTkTextbox(
            raw_tab, fg_color=CARD, text_color=TEXT, font=_FONT
        )
        self._output.pack(fill="both", expand=True)
        self._output.insert("1.0", "点击「开始探针」读取当前对局 (需游戏运行中)。")
        self._output.configure(state="disabled")
        self._comparison_output = ctk.CTkTextbox(
            compare_tab, fg_color=CARD, text_color=TEXT, font=_FONT
        )
        self._comparison_output.pack(fill="both", expand=True)
        self._comparison_output.insert(
            "1.0",
            "先探针或打开报告，再选择「与旧报告比较」。比较方向：旧报告 → 当前报告。",
        )
        self._comparison_output.configure(state="disabled")

        # GUI 惯例: Ctrl+F 内搜 + 右键复制/导出
        find_row = ctk.CTkFrame(self, fg_color="transparent")
        find_row.pack(fill="x", padx=14, pady=(0, 4))
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

        def _find_next() -> None:
            needle = self._find_var.get().strip()
            if not needle:
                return
            start = self._find_state["start"]
            box = self._active_textbox()
            box.tag_remove("sel", "1.0", "end")
            pos = box.search(needle, start, stopindex="end", nocase=True)
            if not pos:
                pos = box.search(needle, "1.0", stopindex="end", nocase=True)  # 回卷
            if pos:
                box.see(pos)
                end = f"{pos}+{len(needle)}c"
                box.tag_add("sel", pos, end)
                self._find_state["start"] = end

        find_entry.bind("<Return>", lambda _e: _find_next())
        self.bind_all("<Control-f>", lambda _e: find_entry.focus_set() or "break")
        # CapsLock 大写态变体 (Tk 绑定大小写敏感)
        self.bind_all("<Control-F>", lambda _e: find_entry.focus_set() or "break")
        # Ctrl+A 全选输出 (CTkTextbox 不默认绑)
        self.bind_all(
            "<Control-a>",
            lambda _e: (
                self._active_textbox().tag_add("sel", "1.0", "end"),
                self._active_textbox().mark_set("insert", "end"),
                "break",
            )[2],
        )
        # CapsLock 大写态变体 (Tk 绑定大小写敏感)
        self.bind_all(
            "<Control-A>",
            lambda _e: (
                self._active_textbox().tag_add("sel", "1.0", "end"),
                self._active_textbox().mark_set("insert", "end"),
                "break",
            )[2],
        )
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label="复制全部",
            command=lambda: (
                self._output.clipboard_clear(),
                self._output.clipboard_append(self._output.get("1.0", "end").strip()),
            ),
        )
        menu.add_command(
            label="复制选中",
            command=lambda: (
                (
                    self._output.clipboard_clear(),
                    self._output.clipboard_append(
                        self._output.get("sel.first", "sel.last")
                    ),
                )
                if self._output.tag_ranges("sel")
                else None
            ),
        )
        menu.add_command(label="导出为 .md", command=self._export_md)
        menu.add_separator()
        menu.add_command(
            label="用选中/剪贴板码查包查询",
            command=self._query_selected_code,
        )
        menu.add_command(
            label="用选中/剪贴板坐标 near 反查",
            command=self._near_selected_coords,
        )
        menu.add_command(
            label="用选中/剪贴板码 where 反查获取途径",
            command=self._where_selected_code,
        )
        menu.add_command(
            label="用选中/剪贴板码 drop 反查掉落",
            command=self._drop_selected_code,
        )
        menu.add_command(
            label="用选中/剪贴板坐标 near 再查 (半径 500)",
            command=lambda: self._near_rerun_selected("500"),
        )
        menu.add_command(
            label="用选中/剪贴板坐标 near 再查 (半径 100, 更精细)",
            command=lambda: self._near_rerun_selected("100"),
        )
        self._output.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

        for box in (self._detail_output, self._comparison_output):
            self._attach_content_menu(box)

        self._section_positions: dict[str, str] = {"顶部": "1.0"}
        self._section_menu = ctk.CTkOptionMenu(
            find_row,
            values=["顶部"],
            command=self._jump_section,
            width=180,
        )
        self._section_menu.pack(side="left", padx=8)
        self._refresh_sections()

        self._restore_session_view()

        if auto_start:
            self._probe_start_id = self.after(120, self._start)
        else:
            self._copy_hint.configure(
                text="离线模式：打开 / 比较已保存报告；手动点击才会开始探针。"
            )

    def _build_evidence_tab(self, tab) -> None:
        self._selection_status = ctk.CTkLabel(
            tab,
            text="尚未读取选中列表；可开始探针或打开离线报告。",
            anchor="w",
        )
        self._selection_status.pack(fill="x", pady=(0, 4))
        body = ctk.CTkFrame(tab, fg_color="transparent")
        body.pack(fill="both", expand=True)
        left = ctk.CTkFrame(body, fg_color=CARD, width=290)
        left.pack(side="left", fill="both", padx=(0, 8))
        ctk.CTkLabel(left, text="选中单位（选择具体实例）", anchor="w").pack(
            fill="x", padx=8
        )
        self._unit_list = self._instance_list(left)
        self._unit_list.bind("<<ListboxSelect>>", self._choose_unit)
        ctk.CTkLabel(left, text="当前单位背包（选择具体物品）", anchor="w").pack(
            fill="x", padx=8
        )
        self._item_list = self._instance_list(left)
        self._item_list.bind("<<ListboxSelect>>", self._choose_item)

        right = ctk.CTkFrame(body, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)
        unit_actions = ctk.CTkFrame(right, fg_color="transparent")
        unit_actions.pack(fill="x", pady=(0, 4))
        self._unit_detail_button = ctk.CTkButton(
            unit_actions,
            text="单位字段",
            width=90,
            command=lambda: self._query_instance("detail"),
            state="disabled",
        )
        self._unit_detail_button.pack(side="left", padx=(0, 4))
        self._unit_drop_button = ctk.CTkButton(
            unit_actions,
            text="单位掉落 / 来源",
            width=120,
            command=lambda: self._query_instance("where"),
            state="disabled",
        )
        self._unit_drop_button.pack(side="left", padx=(0, 4))
        self._unit_near_buttons = []
        for radius, label in (("500", "坐标 near 500"), ("100", "坐标 near 100")):
            button = ctk.CTkButton(
                unit_actions,
                text=label,
                width=115,
                command=lambda r=radius: self._near_instance(r),
                state="disabled",
            )
            button.pack(side="left", padx=(0, 4))
            self._unit_near_buttons.append(button)
        item_actions = ctk.CTkFrame(right, fg_color="transparent")
        item_actions.pack(fill="x", pady=(0, 4))
        self._item_buttons = []
        for action, label in (
            ("detail", "物品字段"),
            ("where", "物品获取途径"),
            ("drop", "物品掉落"),
        ):
            button = ctk.CTkButton(
                item_actions,
                text=label,
                width=115,
                command=lambda a=action: self._query_instance(a, item=True),
                state="disabled",
            )
            button.pack(side="left", padx=(0, 4))
            self._item_buttons.append(button)
        self._detail_output = ctk.CTkTextbox(
            right, fg_color=CARD, text_color=TEXT, font=_FONT
        )
        self._detail_output.pack(fill="both", expand=True)
        self._detail_output.insert(
            "1.0", "选择单位后可查看所属玩家、坐标、完整背包与字段证据。"
        )
        self._detail_output.configure(state="disabled")

    def _restore_session_view(self) -> None:
        previous = _SESSION_VIEWS.get(self._memory_key)
        if previous is None:
            return
        self._raw_report_text = previous.raw_text
        self._replace_text(self._output, previous.raw_text)
        self._replace_text(self._comparison_output, previous.comparison_text)
        if previous.report is not None:
            self._set_report(previous.report, previous.source)
            index = preferred_selection(
                previous.report, previous.selected_unit, previous.report
            )
            if index is not None:
                self._unit_list.selection_clear(0, "end")
                self._unit_list.selection_set(index)
                self._choose_unit()
            if previous.selected_item is not None:
                matches = [
                    ordinal
                    for ordinal, row in enumerate(self._item_rows)
                    if row.get("addr") == previous.selected_item.get("addr")
                    and row.get("code") == previous.selected_item.get("code")
                ]
                if len(matches) == 1:
                    self._item_list.selection_clear(0, "end")
                    self._item_list.selection_set(matches[0])
                    self._choose_item()
            self._report_label.configure(text="上次会话快照 · " + previous.source)
        if previous.tab in {"选中与证据", "完整输出", "离线比较"}:
            self._tabs.set(previous.tab)
        self._reset_search()

    def _remember_session_view(self) -> None:
        _SESSION_VIEWS[self._memory_key] = LiveDialogMemory(
            report=self._report,
            source=self._report_source,
            raw_text=self._raw_report_text,
            comparison_text=self._comparison_output.get("1.0", "end"),
            selected_unit=self._current_unit(),
            selected_item=self._current_item(),
            tab=self._tabs.get(),
        )

    def _instance_list(self, parent) -> tk.Listbox:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        vertical = tk.Scrollbar(frame, orient="vertical")
        vertical.pack(side="right", fill="y")
        horizontal = tk.Scrollbar(frame, orient="horizontal")
        horizontal.pack(side="bottom", fill="x")
        box = tk.Listbox(
            frame,
            selectmode="browse",
            exportselection=False,
            height=6,
            width=32,
            font=_FONT,
            yscrollcommand=vertical.set,
            xscrollcommand=horizontal.set,
        )
        box.pack(side="left", fill="both", expand=True)
        vertical.configure(command=box.yview)
        horizontal.configure(command=box.xview)
        return box

    def _active_textbox(self):
        tab = self._tabs.get()
        return (
            self._output
            if tab == "完整输出"
            else self._comparison_output
            if tab == "离线比较"
            else self._detail_output
        )

    def _reset_search(self) -> None:
        if hasattr(self, "_find_state"):
            self._find_state["start"] = "1.0"
        if hasattr(self, "_section_menu"):
            self._refresh_sections()

    def _replace_text(self, box, text: str) -> None:
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text)
        box.see("1.0")
        box.configure(state="disabled")
        self._reset_search()

    def _refresh_sections(self) -> None:
        text = self._active_textbox().get("1.0", "end")
        positions = {"顶部": "1.0"}
        for line, content in enumerate(text.splitlines(), 1):
            if re.match(r"^【[^】]+】", content):
                label = (
                    content if content not in positions else f"{content} · 行 {line}"
                )
                positions[label] = f"{line}.0"
            elif content.startswith("{"):
                positions.setdefault("完整 JSON", f"{line}.0")
        self._section_positions = positions
        self._section_menu.configure(values=list(positions))
        self._section_menu.set("顶部")

    def _jump_section(self, label: str) -> None:
        box = self._active_textbox()
        position = self._section_positions.get(label, "1.0")
        box.see(position)
        box.tag_remove("sel", "1.0", "end")
        box.tag_add("sel", position, f"{position} lineend")
        self._find_state["start"] = position

    def _attach_content_menu(self, box) -> None:
        menu = tk.Menu(self, tearoff=0)

        def copy_text(selected: bool = False) -> None:
            if selected and not box.tag_ranges("sel"):
                return
            text = (
                box.get("sel.first", "sel.last") if selected else box.get("1.0", "end")
            )
            self.clipboard_clear()
            self.clipboard_append(text)

        menu.add_command(label="复制选中", command=lambda: copy_text(True))
        menu.add_command(label="复制全部", command=copy_text)
        menu.add_command(label="导出为 .md", command=lambda: self._export_content(box))
        box.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

    def _current_unit(self) -> Mapping[str, object] | None:
        index = self._selected_index
        return (
            self._selected_rows[index]
            if index is not None and index < len(self._selected_rows)
            else None
        )

    def _current_item(self) -> Mapping[str, object] | None:
        index = self._item_index
        return (
            self._item_rows[index]
            if index is not None and index < len(self._item_rows)
            else None
        )

    def _choose_unit(self, _event=None) -> None:
        indices = self._unit_list.curselection()
        self._selected_index = indices[0] if indices else None
        unit = self._current_unit()
        self._item_rows = item_records(unit) if unit is not None else ()
        self._item_index = 0 if self._item_rows else None
        self._item_list.delete(0, "end")
        for index, item in enumerate(self._item_rows):
            self._item_list.insert("end", record_label(item, index, item=True))
        if self._item_index is not None:
            self._item_list.selection_set(self._item_index)
        self._render_instance()

    def _choose_item(self, _event=None) -> None:
        indices = self._item_list.curselection()
        self._item_index = indices[0] if indices else None
        self._render_instance()

    def _render_instance(self) -> None:
        unit, item = self._current_unit(), self._current_item()
        callback = self._query_callback is not None
        unit_state = (
            "normal"
            if callback and unit is not None and object_query(unit, "detail")
            else "disabled"
        )
        self._unit_detail_button.configure(state=unit_state)
        self._unit_drop_button.configure(state=unit_state)
        near_state = (
            "normal"
            if callback and unit is not None and unit_near_query(unit)
            else "disabled"
        )
        for button in self._unit_near_buttons:
            button.configure(state=near_state)
        item_state = (
            "normal"
            if callback and item is not None and object_query(item, "detail", item=True)
            else "disabled"
        )
        for button in self._item_buttons:
            button.configure(state=item_state)
        if self._report is not None:
            self._replace_text(
                self._detail_output, format_live_details(self._report, unit, item)
            )

    def _set_report(self, report: Mapping[str, object], source: str) -> None:
        index = preferred_selection(self._report, self._current_unit(), report)
        self._report, self._report_source = report, source
        self._selected_rows = selected_records(report)
        self._selected_index = index
        self._unit_list.delete(0, "end")
        for ordinal, row in enumerate(self._selected_rows):
            self._unit_list.insert("end", record_label(row, ordinal))
        if index is not None:
            self._unit_list.selection_set(index)
            self._unit_list.see(index)
        self._selection_status.configure(text=selection_status(report))
        self._report_label.configure(text=source)
        self._save_report_button.configure(state="normal")
        self._compare_report_button.configure(state="normal")
        self._choose_unit()
        self._tabs.set("选中与证据")
        self._reset_search()

    def _query_instance(self, action: str, *, item: bool = False) -> None:
        record = self._current_item() if item else self._current_unit()
        command = (
            object_query(record, action, item=item) if record is not None else None
        )
        if command and self._query_callback is not None:
            self._query_callback(command)
        else:
            self._copy_hint.configure(
                text="请选择具有明确四码的实例，并打开对应地图资料包。"
            )

    def _near_instance(self, radius: str = "500") -> None:
        unit = self._current_unit()
        command = unit_near_query(unit, radius) if unit is not None else None
        if command and self._query_callback is not None:
            self._query_callback(command)
        else:
            self._copy_hint.configure(
                text="该实例没有确认的 X/Y；请查看字段证据或重新探针。"
            )

    def _open_reference(self) -> None:
        from .gui_reference_catalog import open_reference_catalog_dialog

        pack = (
            self._pack_dir_provider()
            if self._pack_dir_provider is not None
            else self._pack_dir
        )
        open_reference_catalog_dialog(self, pack_dir=pack)

    def _save_structured_report(self) -> None:
        current = self._report
        if current is None:
            self._copy_hint.configure(
                text="没有可保存的结构化报告；可先探针或打开报告。"
            )
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="保存当前结构化报告（选择新文件）",
            defaultextension=".json",
            filetypes=[("JSON 报告", "*.json")],
            initialfile="live-report.json",
        )
        if not path:
            return
        from .gui_live_reports import save_report

        try:
            saved = save_report(path, current)
        except (ValueError, OSError) as exc:
            self._copy_hint.configure(text=f"保存失败: {exc}")
            return
        self._copy_hint.configure(text=f"报告已保存: {saved}")

    def _open_structured_report(self) -> None:
        # A native file picker can run a nested Tk event loop. Cancel first so
        # the initial auto-probe cannot start while the user chooses a file.
        self._cancel_live_probe()
        self._probe_button.configure(state="normal")
        path = filedialog.askopenfilename(
            parent=self,
            title="打开离线 live 报告（不读取游戏）",
            filetypes=[("JSON 报告", "*.json"), ("全部文件", "*")],
        )
        if not path:
            return
        from .gui_live_reports import open_report

        try:
            report, raw = open_report(path)
        except (ValueError, OSError) as exc:
            self._copy_hint.configure(text=f"打开报告失败: {exc}")
            return
        self._replace_text(self._output, raw)
        self._raw_report_text = raw
        self._set_report(report, "离线报告 · " + path)
        self._copy_hint.configure(text="已打开离线报告；显示的是保存时的快照。")

    def _compare_structured_report(self) -> None:
        current, current_source = self._report, self._report_source
        if current is None:
            self._copy_hint.configure(text="请先探针或打开当前报告，再选择旧报告比较。")
            return
        path = filedialog.askopenfilename(
            parent=self,
            title="选择旧报告（旧 → 当前）",
            filetypes=[("JSON 报告", "*.json"), ("全部文件", "*")],
        )
        if not path:
            return
        from .gui_live_reports import compare_report

        try:
            text = compare_report(path, current)
        except (ValueError, OSError) as exc:
            self._copy_hint.configure(text=f"比较报告失败: {exc}")
            return
        self._replace_text(
            self._comparison_output,
            f"【比较来源】\n旧报告: {path}\n当前: {current_source}\n\n{text}",
        )
        self._tabs.set("离线比较")
        self._reset_search()
        self._copy_hint.configure(
            text="离线比较完成；未知、不完整和身份不符请查看比较诊断。"
        )

    def _cancel_live_probe(self) -> None:
        child = self._probe_child
        self._probe_child = None
        if child is not None:
            child.cancel()
        for field in ("_probe_start_id", "_probe_poll_id"):
            after_id = getattr(self, field, None)
            setattr(self, field, None)
            if after_id is not None:
                try:
                    self.after_cancel(after_id)
                except tk.TclError:
                    pass  # Parent teardown may already have removed the timer.

    def destroy(self) -> None:
        if self._probe_closed:
            return
        self._probe_closed = True
        self._cancel_live_probe()
        self._remember_session_view()
        # Save the edited values even when the user closes without re-probing.
        self._save_last_map_path(self._map_entry.get().strip())
        self._save_last_unit_query(self._unit_entry.get().strip())
        super().destroy()

    def _last_unit_query_file(self) -> pathlib.Path:
        from .gui_pack_query import _memo_dir

        base = _memo_dir()
        if not base:
            raise OSError("GUI memory directory is unavailable")
        return pathlib.Path(base) / "live-probe-unit.txt"

    def _load_last_unit_query(self) -> str:
        try:
            return (
                pathlib.Path(self._last_unit_query_file())
                .read_text(encoding="utf-8")
                .strip()
            )
        except OSError, UnicodeError:
            return ""

    def _save_last_unit_query(self, query: str | None) -> None:
        try:
            target = self._last_unit_query_file()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(query or "", encoding="utf-8")
        except OSError, UnicodeError:
            pass  # fail-open: 记忆失败不影响探针

    def _last_map_path_file(self) -> pathlib.Path:
        from .gui_pack_query import _memo_dir

        base = _memo_dir()
        if not base:
            raise OSError("GUI memory directory is unavailable")
        return pathlib.Path(base) / "live-probe-map.txt"

    def _load_last_map_path(self) -> str:
        try:
            return (
                pathlib.Path(self._last_map_path_file())
                .read_text(encoding="utf-8")
                .strip()
            )
        except OSError, UnicodeError:
            return ""

    def _save_last_map_path(self, path: str | None) -> None:
        try:
            target = self._last_map_path_file()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(path or "", encoding="utf-8")
        except OSError, UnicodeError:
            pass  # fail-open: 记忆失败不影响探针

    def _start(self) -> None:
        if self._probe_closed:
            return
        if self._probe_start_id is not None:
            try:
                self.after_cancel(self._probe_start_id)
            except tk.TclError:
                pass  # The scheduled callback may be executing this method now.
            self._probe_start_id = None
        if self._probe_button.cget("state") == "disabled":
            return
        self._probe_button.configure(state="disabled")
        self._copy_hint.configure(text="")
        self._output.configure(state="normal")
        self._output.delete("1.0", "end")
        self._output.insert("1.0", "探针中 … (读内存 + 自动定位资料包)")
        self._output.configure(state="disabled")
        if hasattr(self, "_reset_search"):
            self._reset_search()
        if getattr(self, "_report", None) is not None:
            self._report_label.configure(text="重新探针中；详情仍为上一份快照")

        pack_dir = (
            self._pack_dir_provider()
            if self._pack_dir_provider is not None
            else self._pack_dir
        )
        want_players = self._var_players.get()
        want_all = self._var_all_units.get()
        want_resources = self._var_resources.get()
        map_path = self._map_entry.get().strip() or None
        unit_query = self._unit_entry.get().strip() or None
        self._save_last_unit_query(unit_query)  # 注意: 上一行缩进已同块
        self._save_last_map_path(map_path)
        done: list[str] = []
        from .live_cli import LiveCliOptions

        try:
            options = LiveCliOptions(
                map_path=map_path,
                unit_query=unit_query,
                pack_dir=pack_dir,
                players=want_players,
                all_units=want_all,
                resources=("auto", "") if want_resources else None,
            )
            child = LiveProbeChild(
                build_live_probe_command(options),
                env=build_live_probe_environment(),
                cwd=os.getcwd(),
            )
        except Exception as exc:  # BROAD_EXCEPT_OK - report a failed request setup through the existing GUI result path.
            self._finish(f"探针异常: {type(exc).__name__}: {exc}")
            return
        self._probe_child = child

        def _worker() -> None:
            try:
                result = child.run()
            except Exception as exc:  # BROAD_EXCEPT_OK - isolate this owned child failure from Tk and other probes.
                done.append(f"探针异常: {type(exc).__name__}: {exc}")
                return
            code = 2 if result.cancelled else result.exit_code
            body = result.stdout
            if code != 0 and result.stderr.strip():
                # 出路口径走 stderr (无图/未运行/主菜单提示) — GUI 用户必须看到
                # Keep the structured report last, including failed partial probes.
                body = result.stderr.rstrip() + "\n" + body
            done.append(f"{code}" + chr(0) + body)

        threading.Thread(target=_worker, daemon=True).start()

        def _poll() -> None:
            self._probe_poll_id = None
            if (
                self._probe_closed
                or self._probe_child is not child
                or not self.winfo_exists()
            ):
                return
            if not done:
                self._probe_poll_id = self.after(80, _poll)
                return
            self._probe_child = None
            self._finish(done[0])

        self._probe_poll_id = self.after(80, _poll)

    def _finish(self, text: str) -> None:
        if self._probe_closed:
            return
        self._probe_button.configure(state="normal")
        if chr(0) in text:
            code_str, body = text.split(chr(0), 1)
            body = body or "(无输出)"
        else:
            code_str, body = "1", text
        copied = ""
        parsed = parse_live_output(body)
        self._raw_report_text = body
        self._replace_text(
            self._output, body if body.strip() else f"(退出码 {code_str})"
        )
        if parsed.report is not None:
            self._set_report(parsed.report, f"探针快照 · 退出码 {code_str}")
        else:
            self._report = None
            self._selected_rows = ()
            self._selected_index = None
            self._item_rows = ()
            self._item_index = None
            self._unit_list.delete(0, "end")
            self._item_list.delete(0, "end")
            self._selection_status.configure(text=parsed.diagnostic)
            self._report_label.configure(text="没有完整结构化报告")
            self._save_report_button.configure(state="disabled")
            self._compare_report_button.configure(state="disabled")
            self._render_instance()
            self._replace_text(self._detail_output, parsed.diagnostic)
            self._tabs.set("完整输出")
            self._reset_search()
        if parsed.report is not None and code_str == "0":
            try:
                self.clipboard_clear()
                self.clipboard_append(parsed.json_text)
                copied = "  ·  探针 JSON 已复制 (near 可提取坐标)"
                probe = parsed.report
                units = probe.get("units")
                if isinstance(units, list):
                    unit_count = len(units)
                    item_count = sum(
                        len(item_records(unit))
                        for unit in units
                        if isinstance(unit, Mapping)
                    )
                    owned = probe.get("owned_units")
                    extra = (
                        f" · 在场单位 {len(owned)}" if isinstance(owned, list) else ""
                    )
                    copied = f" · 带物单位 {unit_count} · 物品 {item_count}{extra} · JSON 已复制 (near 可提取坐标)"
            except tk.TclError:
                copied = ""
        self._copy_hint.configure(text=copied or parsed.diagnostic)

    def _near_selected_coords(self) -> None:
        """Use selected JSON or annotated coordinates, preserving exponent notation."""
        self._near_rerun_selected("")

    def _near_rerun_selected(self, radius: str = "500") -> None:
        try:
            raw = self._output.get("sel.first", "sel.last").strip()
        except tk.TclError:
            raw = ""
        if not raw:
            try:
                raw = self.clipboard_get().strip()
            except Exception:
                return
        point = coordinates_from_text(raw)
        if point is not None and self._query_callback is not None:
            suffix = f" {radius}" if radius else ""
            self._query_callback(f"near {point[0]} {point[1]}{suffix}")

    def _extract_code(self) -> str:
        """取输出区选中文本 (退剪贴板) 的四码, 无则空串。"""
        try:
            code = self._output.get("sel.first", "sel.last")
        except tk.TclError:
            code = ""
        if not code:
            try:
                code = self.clipboard_get()
            except Exception:
                return ""
        parsed = code_from_text(code)
        if parsed is None:
            # 全选/长选区含多个码 — 猜一个会误导 (JSON 尾部首个码是随机条目)
            self._copy_hint.configure(
                text="选区含多个码或未明确标注四码——请精确选中一个"
            )
            return ""
        return parsed

    def _query_selected_code(self) -> None:
        """取选中/剪贴板四码, 交给包查询窗 doc 模式。"""
        code = self._extract_code()
        if code and self._query_callback is not None:
            self._query_callback(code)

    def _where_selected_code(self) -> None:
        """四码 where 反查: 物品获取途径 (合成/掉落/商店/脚本奖励)。"""
        code = self._extract_code()
        if code and self._query_callback is not None:
            self._query_callback("where " + code)

    def _drop_selected_code(self) -> None:
        """四码 drop 反查: 谁掉/谁给 (死亡触发+关系表证据)。"""
        code = self._extract_code()
        if code and self._query_callback is not None:
            self._query_callback("drop " + code)

    def _export_md(self) -> None:
        """输出区导出为 .md (桌面优先, fail-open)。"""
        import time

        text = self._output.get("1.0", "end").strip()
        if not text:
            return
        home = os.path.expanduser("~")
        target_dir = os.path.join(home, "Desktop")
        if not os.path.isdir(target_dir):
            target_dir = os.environ.get("TEMP", home)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = os.path.join(target_dir, f"live-probe-{stamp}.md")
        try:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(
                    "# live 探针输出"
                    + chr(10) * 2
                    + chr(96) * 3
                    + chr(10)
                    + text
                    + chr(10)
                    + chr(96) * 3
                    + chr(10)
                )

            self._copy_hint.configure(text="已导出: " + path)
        except OSError:
            self._copy_hint.configure(text="导出失败 (目录不可写)")

    def _export_content(self, box) -> None:
        text = box.get("1.0", "end").strip()
        if not text:
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="导出当前内容",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md")],
        )
        if not path:
            return
        try:
            pathlib.Path(path).write_text(text + "\n", encoding="utf-8")
        except OSError as exc:
            self._copy_hint.configure(text=f"导出失败: {exc}")
            return
        self._copy_hint.configure(text="已导出: " + path)


def open_live_probe_dialog(
    master,
    pack_dir: str | None = None,
    query_callback: "Callable[[str], None] | None" = None,
    pack_dir_provider: Callable[[], str | None] | None = None,
    *,
    auto_start: bool = True,
) -> None:
    LiveProbeWindow(
        master,
        pack_dir,
        query_callback=query_callback,
        pack_dir_provider=pack_dir_provider,
        auto_start=auto_start,
    )
