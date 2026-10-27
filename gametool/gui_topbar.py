"""Topbar layout for the GUI shell."""

from __future__ import annotations

from .query_coordinates import coordinates_from_text
from .query_object_codes import code_from_text

import os
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .theme import (
    ACCENT,
    BORDER,
    FONT,
    PANEL,
    SUBTLE,
    TEXT,
    TITLE_FONT,
    TOPBAR,
    primary_button_style,
    secondary_button_style,
)


from .gui_live_probe import open_live_probe_dialog
from .gui_profile_settings import open_extraction_profile_dialog  # 提取开关设置对话框


def build_topbar(app) -> None:
    """Build the always-visible top command bar."""
    bar = ctk.CTkFrame(
        app,
        fg_color=TOPBAR,
        corner_radius=0,
        height=64,
        border_width=1,
        border_color=BORDER,
    )
    bar.pack(fill="x", side="top")
    bar.pack_propagate(False)
    brand = ctk.CTkFrame(bar, fg_color="transparent")
    brand.pack(side="left", padx=(16, 14), pady=8)
    ctk.CTkLabel(
        brand, text="GAMEXRAY", font=(TITLE_FONT, 21, "bold"), text_color=ACCENT
    ).pack(anchor="w")
    ctk.CTkLabel(
        brand, text="Warcraft III map workbench", font=(FONT, 11), text_color=SUBTLE
    ).pack(anchor="w")
    app.open_map_button = ctk.CTkButton(
        bar,
        text="打开地图 / 战役",
        font=(FONT, 13, "bold"),
        width=140,
        height=36,
        command=app.on_open,
        **primary_button_style(),
    )
    _attach_tooltip(app.open_map_button, "打开本地地图或战役文件 (首次建议从这里开始)")
    app.open_map_button.pack(side="left", padx=(0, 12))
    app.current_map_button = ctk.CTkButton(
        bar,
        text="获取当前地图",
        font=(FONT, 13, "bold"),
        width=116,
        height=36,
        command=app.on_open_current_map,
        **secondary_button_style(),
    )
    _attach_tooltip(app.current_map_button, "探测运行中的游戏正在玩哪张图 (只读)")
    app.current_map_button.pack(side="left", padx=(0, 12))
    app.map_label = ctk.CTkLabel(
        bar,
        text="未打开",
        font=(FONT, 12),
        text_color=TEXT,
        fg_color=PANEL,
        corner_radius=6,
        height=32,
    )
    app.map_label.pack(side="left", fill="x", expand=True, padx=(0, 12))
    source_tools = ctk.CTkFrame(bar, fg_color="transparent")
    source_tools.pack(side="right", padx=(0, 8))
    _add_source_selector(source_tools, "外部listfile", app.on_pick_external_listfile)
    app.external_listfile_label = _source_label(source_tools, "listfile: 未选")
    app.external_listfile_clear = ctk.CTkButton(
        source_tools,
        text="×",
        width=24,
        height=26,
        font=(FONT, 14),
        command=app.on_clear_external_listfile,
        state="disabled",
        **secondary_button_style(),
    )
    app.external_listfile_clear.pack(side="left", padx=(0, 4))
    _add_source_selector(source_tools, "游戏数据", app.on_pick_game_data_dir)
    app.game_data_label = _source_label(source_tools, "游戏数据: 未选")
    app.data_tools_menu = tk.Menu(app, tearoff=False)
    app.data_tools_menu.add_command(
        label="浏览 CASC Root", command=app.on_browse_game_data
    )
    app.data_tools_menu.add_separator()
    app.data_tools_menu.add_command(
        label="选择作者明文补充包", command=app.on_pick_author_bundle
    )
    app.data_tools_menu.add_command(
        label="清除作者明文补充包", command=app.on_clear_author_bundle
    )
    app.data_tools_menu.add_separator()
    app.data_tools_menu.add_command(
        label="选择可信描述缓存", command=app.on_pick_description_cache
    )
    app.data_tools_menu.add_command(
        label="清除可信描述缓存", command=app.on_clear_description_cache
    )
    app.data_tools_menu.add_separator()
    app.data_tools_menu.add_command(
        label="分析真实存档文件", command=app.on_analyze_real_save_file
    )
    app.data_tools_menu.add_command(
        label="字段 / 对象 / 版本目录", command=lambda: _open_reference_catalog(app)
    )
    app.data_tools_menu.add_command(
        label="打开 / 比较实时报告（离线）",
        command=lambda: _open_live_probe(app, auto_start=False),
    )
    app.data_tools_menu.add_command(
        label="打开本地资料包查询（离线）",
        command=lambda: _open_local_pack_query(app),
    )
    app.data_tools_menu.add_separator()
    app.data_tools_menu.add_command(
        label="打开最近资料包目录", command=lambda: _open_last_pack(app)
    )
    app.data_tools_menu.add_command(
        label="导出运行时对象包 (词缀/注册)",
        command=app.on_dump_runtime_objects,
    )
    app.data_tools_menu.add_command(
        label="键盘速查", command=lambda: _show_hotkeys(app)
    )
    app.data_tools_menu.add_command(
        label="分析真实存档目录", command=app.on_analyze_real_save_directory
    )
    app.profile_settings_button = ctk.CTkButton(
        source_tools,
        text="提取设置",
        width=68,
        height=26,
        font=(FONT, 11),
        command=lambda: open_extraction_profile_dialog(app),
        **secondary_button_style(),
    )
    _attach_tooltip(
        app.profile_settings_button, "提取类目开关: 按组跳过资料包产物以提速"
    )
    app.profile_settings_button.pack(side="left", padx=(0, 4))
    app.pack_query_button = ctk.CTkButton(
        source_tools,
        text="包查询",
        width=68,
        height=26,
        font=(FONT, 11),
        command=app.on_pack_query,
        **secondary_button_style(),
    )
    _attach_tooltip(
        app.pack_query_button,
        "包查询 26 模式三排面板: 核心 10 (Ctrl+1..0) + 扩展 16 (where/drop/diff/price/quest/cmd/text/refs/affixes/registered 等)",
    )
    app.pack_query_button.pack(side="left", padx=(0, 4))
    app.live_probe_button = ctk.CTkButton(
        source_tools,
        text="live 探针",
        width=68,
        height=26,
        font=(FONT, 11),
        command=lambda: _open_live_probe(app),
        **secondary_button_style(),
    )
    _attach_tooltip(
        app.live_probe_button,
        "只读内存探针: 选中单位背包/在场单位/资源 (游戏运行中可用; JSON 自动复制)",
    )
    app.live_probe_button.pack(side="left", padx=(0, 4))
    app.minimap_button = ctk.CTkButton(
        source_tools,
        text="小地图",
        width=68,
        height=26,
        font=(FONT, 11),
        command=lambda: _render_minimap(app),
        **secondary_button_style(),
    )
    _attach_tooltip(app.minimap_button, "按当前地图生成小地图标注 PNG (商店/掉落点位)")
    app.minimap_button.pack(side="left", padx=(0, 4))
    app.guide_button = ctk.CTkButton(
        source_tools,
        text="攻略速查",
        width=76,
        height=26,
        font=(FONT, 11),
        command=lambda: _show_guide(app),
        **secondary_button_style(),
    )
    _attach_tooltip(
        app.guide_button,
        "一键玩家攻略: 指令/任务/英雄/配方/商店/掉落/开箱与兑换/线索 速查",
    )
    app.guide_button.pack(side="left", padx=(0, 4))
    # 未加载地图前禁用地图相关按钮 (加载成功后 lifecycle 统一启用)
    for _btn in (app.minimap_button, app.guide_button, app.pack_query_button):
        _btn.configure(state="disabled")
    app.data_tools_button = ctk.CTkButton(
        source_tools,
        text="数据工具",
        width=68,
        height=26,
        font=(FONT, 11),
        command=lambda: _popup_data_tools(app),
        **secondary_button_style(),
    )
    _attach_tooltip(
        app.data_tools_button, "本地资料包查询/离线报告/导出/存档分析/键盘速查"
    )
    app.data_tools_button.pack(side="left", padx=(0, 4))
    actions = ctk.CTkFrame(bar, fg_color="transparent")
    actions.pack(side="right", padx=(0, 12))
    for text, width, command in (
        ("导出全部", 88, app.on_export_all),
        ("导出脚本", 82, app.on_export_scripts),
        ("导出ID", 70, app.on_export_ids),
        ("资料包", 70, app.on_export_pack),
    ):
        ctk.CTkButton(
            actions,
            text=text,
            font=(FONT, 12),
            width=width,
            height=30,
            command=command,
            **secondary_button_style(),
        ).pack(side="left", padx=3)


def _add_source_selector(parent, text: str, command) -> None:
    ctk.CTkButton(
        parent,
        text=text,
        font=(FONT, 11),
        width=82,
        height=26,
        command=command,
        **secondary_button_style(),
    ).pack(side="left", padx=(0, 3))


def _source_label(parent, text: str):
    label = ctk.CTkLabel(
        parent, text=text, font=(FONT, 10), text_color=SUBTLE, width=92, anchor="w"
    )
    label.pack(side="left", padx=(0, 6))
    return label


def _popup_data_tools(app) -> None:
    button = app.data_tools_button
    app.data_tools_menu.tk_popup(
        button.winfo_rootx(), button.winfo_rooty() + button.winfo_height()
    )


def _open_live_probe(app, *, auto_start: bool = True) -> None:
    source = getattr(app, "map_data", None)
    offline_pack: str | None = None

    def pack_dir_provider():
        return app.current_map_pack_dir(source) if source is not None else offline_pack

    def query(code: str) -> None:
        nonlocal offline_pack
        prefix, separator, keyword = code.partition(" ")
        has_command = bool(separator) and prefix in {
            "near",
            "where",
            "drop",
            "item",
            "units",
            "heroes",
            "skills",
            "buffs",
            "tech",
        }
        prefill = keyword if has_command else code
        command = prefix if has_command else "doc"
        if source is not None:
            app.on_pack_query(
                prefill=prefill,
                prefill_command=command,
                source_map=source,
            )
        else:
            chosen = _open_local_pack_query(
                app,
                prefill=prefill,
                prefill_command=command,
                pack_dir=offline_pack,
            )
            if chosen is not None:
                offline_pack = chosen

    open_live_probe_dialog(
        app,
        pack_dir_provider(),
        query_callback=query,
        pack_dir_provider=pack_dir_provider,
        auto_start=auto_start,
    )


def _open_local_pack_query(
    app,
    *,
    prefill: str = "",
    prefill_command: str = "",
    pack_dir: str | None = None,
) -> str | None:
    """Open an explicitly chosen local pack without borrowing a loaded map."""
    from .gui_export_actions import load_last_pack_dir, save_last_pack_dir
    from .gui_pack_query import open_pack_query_dialog
    from .presentation_safety import format_user_exception

    target = pack_dir
    if target is None:
        previous = getattr(app, "_last_pack_dir", None)
        if not previous:
            try:
                previous = load_last_pack_dir()
            except OSError, UnicodeError:
                previous = ""  # fail-open: memo errors cannot block local queries.
        try:
            target = filedialog.askdirectory(
                parent=app,
                title="选择本地资料包（无需打开原地图）",
                initialdir=previous if previous and os.path.isdir(previous) else None,
            )
        except (OSError, tk.TclError) as exc:
            messagebox.showerror(
                "资料包查询",
                f"无法选择资料包：{format_user_exception(exc)}\n请重新选择本地目录。",
                parent=app,
            )
            return None
        if not target:
            return None
    if not os.path.isdir(target):
        messagebox.showerror(
            "资料包查询",
            f"资料包目录不存在或不可访问：{target}\n"
            "请从「数据工具 → 打开本地资料包查询（离线）」重新选择目录。",
            parent=app,
        )
        return None

    def unavailable() -> None:
        messagebox.showerror(
            "资料包查询",
            f"资料包目录已不可用：{target}\n请重新选择本地目录后查询。",
            parent=app,
        )

    try:
        open_pack_query_dialog(
            app,
            lambda: target,
            unavailable,
            prefill=prefill,
            prefill_command=prefill_command,
        )
    except (OSError, ValueError, tk.TclError) as exc:
        messagebox.showerror(
            "资料包查询",
            f"无法打开资料包查询：{format_user_exception(exc, paths=(target,))}\n"
            "可重新选择目录；旧版或部分资料包的来源诊断会在查询结果中保留。",
            parent=app,
        )
        return None
    app._last_pack_dir = target
    try:
        save_last_pack_dir(target)
    except OSError, UnicodeError:
        pass  # fail-open: keep the explicit session binding when disk is read-only.
    return target


def _open_reference_catalog(app) -> None:
    """Browse existing reference data, optionally alongside the current map pack."""
    from .gui_reference_catalog import open_reference_catalog_dialog

    source = getattr(app, "map_data", None)
    pack_dir = app.current_map_pack_dir(source) if source is not None else None
    open_reference_catalog_dialog(app, pack_dir=pack_dir)


_GUIDE_SCROLL: dict[str, str] = {}  # map_path -> 关闭时滚动位置


def _render_minimap(app) -> None:
    """生成当前地图的小地图标注 PNG (后台线程, 完成后打开文件)。"""
    md = getattr(app, "map_data", None)
    if not md or not getattr(md, "path", ""):
        messagebox.showinfo("小地图", "请先打开地图")
        return
    map_path = md.path
    app.status.configure(text="正在渲染小地图标注 …")
    app.minimap_button.configure(state="disabled")

    from .gui_worker_registry import GuiWorkerTicket

    def work(ticket: GuiWorkerTicket) -> None:
        from .api import tmp_extract_dir
        from .guide_minimap import write_guide_minimap
        from .presentation_safety import format_user_exception

        out = ""
        try:
            output_dir = tmp_extract_dir(md.name, "小地图")
            out = os.path.join(output_dir, "minimap.png")
            log = "\n".join(write_guide_minimap(md, out))
            rc = 0
        except Exception as exc:  # BROAD_EXCEPT_OK - GUI worker boundary.
            rc, log = 2, format_user_exception(exc, paths=(out, map_path))

        def finish():
            if getattr(app, "map_data", None) is not md:
                return
            app.minimap_button.configure(state="normal")
            if rc == 0 and os.path.exists(out):
                app.status.configure(text="小地图已生成: " + out)
                try:
                    os.startfile(out)
                except AttributeError, OSError:
                    messagebox.showinfo(
                        "小地图已生成", f"小地图已保存到临时目录：\n{out}"
                    )
            else:
                app.status.configure(text="小地图生成失败")
                messagebox.showerror("小地图", log or "生成失败")

        _ = app._post_gui_worker(ticket, finish)

    _ = app._start_gui_map_worker("render-minimap", md, work, replace=True)


def _show_guide(app, *, refresh: bool = False) -> None:
    """弹窗展示当前地图的攻略速查报告 (指令/任务/配方/商店/掉落)。"""
    md = getattr(app, "map_data", None)
    if not md or not getattr(md, "path", ""):
        messagebox.showinfo("攻略速查", "请先打开地图")
        return
    cached = getattr(app, "_guide_report_cache", None)
    if cached and cached[0] is md and not refresh:
        _open_guide_window(app, cached[1])
        app.status.configure(text="攻略速查（缓存）已就绪")
        return
    app.status.configure(text="正在整理攻略速查 …")
    app.guide_button.configure(state="disabled")

    from .gui_worker_registry import GuiWorkerTicket

    def work(ticket: GuiWorkerTicket) -> None:
        from .guide_report import format_guide_report

        try:
            log = format_guide_report(md)
            rc = 0
        except Exception as exc:  # BROAD_EXCEPT_OK - GUI worker boundary.
            from .presentation_safety import format_user_exception

            rc, log = 2, format_user_exception(exc, paths=(md.path,))

        def finish():
            if getattr(app, "map_data", None) is not md:
                return
            app.guide_button.configure(state="normal")
            if rc == 0 and log.strip():
                app._guide_report_cache = (md, log)
                app.status.configure(text="攻略速查已就绪")
                _open_guide_window(app, log)
            else:
                app.status.configure(text="攻略速查失败")
                messagebox.showerror("攻略速查", log or "生成失败")

        _ = app._post_gui_worker(ticket, finish)

    _ = app._start_gui_map_worker("show-guide", md, work, replace=True)


def _open_guide_window(app, text: str) -> None:
    import tkinter as tk

    from .guide_report import GUIDE_SECTION_TITLES

    import customtkinter as ctk

    win = ctk.CTkToplevel(app)
    closed = False

    def _guide_alive() -> bool:
        if closed:
            return False
        try:
            return bool(win.winfo_exists())
        except tk.TclError:
            return False  # The parent interpreter may already be shutting down.

    md = getattr(app, "map_data", None)
    map_name = getattr(md, "name", "") if md else ""
    source_path = md.path if md is not None else ""
    win.title(f"攻略速查 — {map_name}" if map_name else "攻略速查")
    from .gui_pack_query import bind_geometry_memory

    bind_geometry_memory(win, "guide", "860x640")
    win.transient(app)
    win.grab_set()
    win.bind(
        "<Control-f>",
        lambda _e=None: (
            (search_entry.focus_set() or "break") if _guide_alive() else "break"
        ),
    )
    # CapsLock 大写态变体 (Tk 绑定大小写敏感)
    win.bind(
        "<Control-F>",
        lambda _e=None: (
            (search_entry.focus_set() or "break") if _guide_alive() else "break"
        ),
    )
    win.bind(
        "<Control-a>",
        lambda _e=None: (
            (
                box.tag_add("sel", "1.0", "end"),
                box.mark_set("insert", "end"),
                "break",
            )[2]
            if _guide_alive()
            else "break"
        ),
    )
    # CapsLock 大写态变体 (Tk 绑定大小写敏感)
    win.bind(
        "<Control-A>",
        lambda _e=None: (
            (
                box.tag_add("sel", "1.0", "end"),
                box.mark_set("insert", "end"),
                "break",
            )[2]
            if _guide_alive()
            else "break"
        ),
    )
    search_row = ctk.CTkFrame(win, fg_color="transparent")
    search_row.pack(fill="x", padx=8, pady=(8, 0))
    search_var = ctk.StringVar()
    search_entry = ctk.CTkEntry(
        search_row,
        textvariable=search_var,
        placeholder_text="报告内搜索 (回车跳下一处)…",
        width=320,
    )
    search_entry.pack(side="left")
    state = {"start": "1.0"}

    def _find_next():
        if not _guide_alive():
            return
        needle = search_var.get().strip()
        if not needle:
            return
        pos = box.search(needle, state["start"], stopindex="end", nocase=True)
        if not pos:
            state["start"] = "1.0"
            pos = box.search(needle, "1.0", stopindex="end", nocase=True)
        if pos:
            box.see(pos)
            box.mark_set("insert", pos)
            end = f"{pos}+{len(needle)}c"
            box.tag_add("sel", pos, end)
            state["start"] = end

    search_entry.bind("<Return>", lambda _e=None: _find_next())
    bar = ctk.CTkFrame(win, fg_color="transparent")
    bar.pack(fill="x", padx=8, pady=(8, 0))
    section_buttons: dict[str, ctk.CTkButton] = {}

    def _mark_active(active_title: str) -> None:
        for t, btn in section_buttons.items():
            active = t == active_title
            btn.configure(
                fg_color=ACCENT if active else "transparent",
                text_color="#ffffff" if active else TEXT,
                border_width=0 if active else 1,
            )

    for key, title in GUIDE_SECTION_TITLES.items():
        btn = ctk.CTkButton(
            bar,
            text=title,
            width=72,
            height=24,
            font=(FONT, 11),
            fg_color="transparent",
            border_width=1,
            command=lambda t=title: (
                (
                    _jump_to_section(box, t),
                    _mark_active(t),
                )
                if _guide_alive()
                else None
            ),  # box 闭包 late-binding: 点击时已定义
        )
        btn.pack(side="left", padx=(0, 4))
        section_buttons[title] = btn
    box = ctk.CTkTextbox(win, font=("Consolas", 12), wrap="none")
    setattr(box, "_query_source_map", md)
    box.pack(fill="both", expand=True, padx=8, pady=8)
    box.insert("1.0", text)
    saved = _GUIDE_SCROLL.get(source_path)
    if saved:
        box.mark_set("insert", saved)
        box.see(saved)
    destroy_window = win.destroy

    def _close_guide(_event=None) -> None:
        nonlocal closed
        if not _guide_alive():
            closed = True
            return
        closed = True
        try:
            _GUIDE_SCROLL[source_path] = box.index("insert")
        except tk.TclError:
            pass  # Parent teardown may already have destroyed the text widget.
        # CTkToplevel schedules its titlebar icon on this window without saving
        # the timer ID. Cancel only callbacks registered by this guide before
        # Tk deletes those Tcl commands; the app's own queued work stays live.
        owned_commands = set(getattr(win, "_tclCommands", ()) or ())
        for after_id in win.tk.splitlist(win.tk.call("after", "info")):
            try:
                data = win.tk.call("after", "info", after_id)
                script = win.tk.splitlist(data)[0]
                commands = win.tk.splitlist(script)
                if commands and commands[0] in owned_commands:
                    win.after_cancel(after_id)
            except tk.TclError:
                pass  # A queued callback may already have completed.
        destroy_window()

    win.destroy = _close_guide
    win.protocol("WM_DELETE_WINDOW", _close_guide)
    guide_menu = tk.Menu(win, tearoff=0)
    guide_menu.add_command(
        label="复制选中",
        command=lambda: (
            (
                box.clipboard_clear(),
                box.clipboard_append(box.get("sel.first", "sel.last")),
            )
            if _guide_alive() and box.tag_ranges("sel")
            else None
        ),
    )
    guide_menu.add_command(
        label="复制全部",
        command=lambda: (
            (
                box.clipboard_clear(),
                box.clipboard_append(box.get("1.0", "end")),
            )
            if _guide_alive()
            else None
        ),
    )
    guide_menu.add_command(
        label="导出报告 (.md)",
        command=lambda: (
            _export_guide(app, box.get("1.0", "end")) if _guide_alive() else None
        ),
    )
    guide_menu.add_command(
        label="强制重算 (清缓存刷新报告)",
        command=lambda: _show_guide(app, refresh=True) if _guide_alive() else None,
    )
    guide_menu.add_separator()
    guide_menu.add_command(
        label="用选中/剪贴板码查包查询",
        command=lambda: _code_selected(app, box) if _guide_alive() else None,
    )
    guide_menu.add_command(
        label="用选中/剪贴板码 where 反查获取途径",
        command=lambda: _code_selected(app, box, "where") if _guide_alive() else None,
    )
    guide_menu.add_command(
        label="用选中/剪贴板码 drop 反查掉落",
        command=lambda: _code_selected(app, box, "drop") if _guide_alive() else None,
    )
    guide_menu.add_separator()
    guide_menu.add_command(
        label="用选中/剪贴板坐标 near 再查 (半径 500)",
        command=lambda: (
            _near_selected_coords(app, box, "500") if _guide_alive() else None
        ),
    )
    guide_menu.add_command(
        label="用选中坐标 near 再查 (半径 100, 更精细)",
        command=lambda: (
            _near_selected_coords(app, box, "100") if _guide_alive() else None
        ),
    )

    def _popup_guide_menu(event=None) -> None:
        if _guide_alive():
            guide_menu.tk_popup(
                event.x_root if event is not None else box.winfo_pointerx(),
                event.y_root if event is not None else box.winfo_pointery(),
            )

    box.bind("<Button-3>", _popup_guide_menu)
    win.bind("<Escape>", _close_guide)


def _code_selected(app, box, prefix: str = "") -> None:
    """取选中/剪贴板的四码, 打开包查询窗 (prefix 空则 doc 直达)。"""
    try:
        raw = box.get("sel.first", "sel.last")
    except Exception:
        raw = ""
    if not raw:
        try:
            raw = box.clipboard_get()
        except Exception:
            return
    code = code_from_text(raw)
    if code is None:
        return  # 多匹配拒猜测 (对齐探针 309)
    app.on_pack_query(
        prefill=code,
        prefill_command=(prefix if prefix else "doc"),
        source_map=getattr(box, "_query_source_map", None),
    )


def _near_selected_coords(app, box, radius: str = "") -> None:
    """Open a near query from one unambiguous, full-precision coordinate pair."""
    try:
        raw = box.get("sel.first", "sel.last").strip()
    except Exception:
        raw = ""
    if not raw:
        try:
            raw = box.clipboard_get().strip()
        except Exception:
            return
    point = coordinates_from_text(raw)
    if point is None:
        return
    app.on_pack_query(
        prefill=f"{point[0]} {point[1]}" + (f" {radius}" if radius else ""),
        prefill_command="near",
        source_map=getattr(box, "_query_source_map", None),
    )


def _jump_to_section(box, title: str) -> None:
    """滚动到【标题】段首; 无该段时状态不变 (报告按证据省略段落)。"""
    needle = f"【{title}】"
    pos = box.search(needle, "1.0", stopindex="end")
    if pos:
        box.see(pos)
        box.mark_set("insert", pos)


def _export_guide(app, text: str) -> None:
    """攻略速查报告落盘 .txt 并复制路径 (与查询窗口导出 .md 同目录语义)。"""
    from .archive_export import tmp_extract_dir

    name = "guide"
    md = getattr(app, "map_data", None)
    if md and getattr(md, "name", ""):
        name = "".join(ch if ch not in '\\/:*?"<>|' else "_" for ch in md.name)
    out_dir = tmp_extract_dir("guide-export")
    out_path = os.path.join(out_dir, name + "-guide.md")
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(text)
    app.status.configure(text="报告已导出: " + out_path)
    app.clipboard_clear()
    app.clipboard_append(out_path)


def _open_last_pack(app) -> None:
    """打开最近导出的资料包目录 (会话内或磁盘记忆)。"""
    from .gui_export_actions import load_last_pack_dir

    target = getattr(app, "_last_pack_dir", None) or load_last_pack_dir()
    if not target or not os.path.isdir(target):
        messagebox.showinfo("资料包目录", "尚未导出资料包——先点「包查询」触发一次导出")
        return
    os.startfile(target)


def _attach_tooltip(widget, text: str) -> None:
    """CTk 控件 hover 提示: Enter 显示 / Leave 销毁 (轻量 Toplevel)。"""
    import tkinter as tk

    state = {"tip": None}

    def _show(_e=None) -> None:
        if state["tip"] is not None:
            return
        x = widget.winfo_rootx() + 10
        y = widget.winfo_rooty() + widget.winfo_height() + 4
        tip = tk.Toplevel(widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tip,
            text=text,
            justify="left",
            bg="#2a2a2a",
            fg="#ffffff",
            font=("Microsoft YaHei UI", 9),
            padx=8,
            pady=4,
        )
        label.pack()
        state["tip"] = tip  # pyright: ignore[reportArgumentType]

    def _hide(_e=None) -> None:
        if state["tip"] is not None:
            state["tip"].destroy()
            state["tip"] = None

    widget.bind("<Enter>", _show, add="+")
    widget.bind("<Leave>", _hide, add="+")
    widget.bind("<ButtonPress>", _hide, add="+")


def _show_hotkeys(app) -> None:
    """键盘流速查弹窗 (与 README 速查表同源)。"""
    import customtkinter as ctk

    win = ctk.CTkToplevel(app)
    win.title("键盘速查")
    win.transient(app)
    from gametool.gui_pack_query import bind_geometry_memory

    bind_geometry_memory(win, "gui-hotkeys", "520x360")
    win.grab_set()
    win.bind("<Escape>", lambda _e: win.destroy())
    rows = (
        (
            "Ctrl+1..9, Ctrl+0",
            "直切 doc/search/list/buffs/export/synth/skills/units/locate/near 模式",
        ),
        (
            "包查询勾选 JSON",
            "输出 {section,lines} 单行 JSON 供脚本解析",
        ),
        (
            "pack-query again",
            "重跑最近一次成功查询 (CLI/GUI 共享记忆)",
        ),
        (
            "live 探针弹窗",
            "只读读局: Ctrl+R 重探; 勾选玩家/全单位/资源; JSON 自动复制",
        ),
        ("回车", "执行当前模式查询 / 跳下一处搜索命中"),
        ("Ctrl+F", "聚焦内搜框 (结果找完续搜收藏框)"),
        ("Esc", "关闭弹窗"),
        ("双击卡片", "对象全景查询"),
        ("右键卡片", "哪来/谁掉/全景 三键直达"),
        ("右键结果区", "复制全部 / 导出 .md"),
        ("右键收藏", "复制收藏 / 清空 / 导出收藏 .md"),
    )
    box = ctk.CTkTextbox(win, font=("Consolas", 13), wrap="word")
    box.pack(fill="both", expand=True, padx=10, pady=10)
    for key, desc in rows:
        box.insert("end", f"{key:<12} {desc}\n")
    box.configure(state="disabled")

    def _export_hotkeys_md(content: str) -> None:
        from .archive_export import tmp_extract_dir

        out_dir = tmp_extract_dir("hotkeys-export")
        out_path = os.path.join(out_dir, "键盘速查.md")
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write(content)
        win.clipboard_clear()
        win.clipboard_append(out_path)
        messagebox.showinfo("已导出", out_path)

    _bind_textbox_search(win, box, exporter=_export_hotkeys_md)


def _bind_textbox_search(win, box, exporter=None) -> None:
    """CTkTextbox 内搜: Ctrl+F 聚焦, 回车逐处跳并高亮 (定位双通道惯例)。"""
    import tkinter as tk

    bar = ctk.CTkFrame(win)
    bar.pack(fill="x", padx=10, pady=(10, 0))
    entry = ctk.CTkEntry(bar, placeholder_text="Ctrl+F 搜索… 回车跳下一处")
    entry.pack(side="left", fill="x", expand=True)
    state = {"pos": "1.0"}

    def _find(_event=None) -> None:
        kw = entry.get().strip()
        box.tag_remove("hit", "1.0", "end")
        if not kw:
            state["pos"] = "1.0"
            return
        start = box.search(kw, state["pos"], stopindex="end", nocase=True)
        if not start:
            state["pos"] = "1.0"
            start = box.search(kw, "1.0", stopindex="end", nocase=True)
            if not start:
                return
        end = f"{start}+{len(kw)}c"
        box.tag_add("hit", start, end)
        box.see(start)
        state["pos"] = end

    box.tag_config("hit", background="#8a6d00", foreground="white")
    menu = tk.Menu(win, tearoff=0)
    menu.add_command(
        label="复制全部",
        command=lambda: (
            win.clipboard_clear(),
            win.clipboard_append(box.get("1.0", "end")),
        ),
    )
    if exporter is not None:
        menu.add_command(
            label="导出 (.md)",
            command=lambda: exporter(box.get("1.0", "end")),
        )
    box.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))
    entry.bind("<Return>", _find)
    entry.bind(
        "<Escape>", lambda _e: (box.tag_remove("hit", "1.0", "end"), win.focus_set())
    )
    win.bind("<Control-f>", lambda _e: entry.focus_set() or None)

    # CapsLock 大写态变体 (Tk 绑定大小写敏感)
    win.bind("<Control-F>", lambda _e: entry.focus_set() or None)
