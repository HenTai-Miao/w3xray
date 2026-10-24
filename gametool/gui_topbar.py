"""Topbar layout for the GUI shell."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox

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
from .gui_pack_query import open_pack_query_dialog
from .gui_export_actions import load_last_pack_dir
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
        command=lambda: open_pack_query_dialog(
            app,
            lambda: getattr(app, "_last_pack_dir", None) or load_last_pack_dir(),
            app.on_export_pack,
        ),
        **secondary_button_style(),
    )
    _attach_tooltip(
        app.pack_query_button,
        "九模式查询: doc/search/list/buffs/export/synth/skills/units/locate (Ctrl+1..9)",
    )
    app.pack_query_button.pack(side="left", padx=(0, 4))
    app.live_probe_button = ctk.CTkButton(
        source_tools,
        text="live 探针",
        width=68,
        height=26,
        font=(FONT, 11),
        command=lambda: open_live_probe_dialog(
            app,
            getattr(app, "_last_pack_dir", None) or load_last_pack_dir(),
            query_callback=lambda code: open_pack_query_dialog(
                app,
                lambda: getattr(app, "_last_pack_dir", None) or load_last_pack_dir(),
                app.on_export_pack,
                prefill=code,
                # near 坐标直达 near 模式, 其余按四码走 doc
                prefill_command=(
                    "near"
                    if code.startswith("near ")
                    else "where"
                    if code.startswith("where ")
                    else "drop"
                    if code.startswith("drop ")
                    else "doc"
                ),
            ),
        ),
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
    _attach_tooltip(app.guide_button, "一键玩家攻略: 指令/任务/配方/商店/掉落/线索速查")
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
        app.data_tools_button, "导出/存档分析/运行时对象/最近资料包/键盘速查"
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


_GUIDE_CACHE: dict[str, str] = {}  # map_path -> 全量报告文本 (进程级, 秒开重开窗口)
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
        import contextlib
        import io

        from .guide_cli import GuideCliOptions, run_guide_cli
        from .presentation_safety import format_user_exception

        out = os.path.splitext(map_path)[0] + "-minimap.png"
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                rc = run_guide_cli(
                    GuideCliOptions(
                        map_path=map_path,
                        section=None,
                        refresh=False,
                        minimap_marks=out,
                    )
                )
        except Exception as exc:  # BROAD_EXCEPT_OK - GUI worker boundary.
            rc, log = 2, format_user_exception(exc, paths=(out, map_path))
        else:
            log = buffer.getvalue()

        def finish():
            app.minimap_button.configure(state="normal")
            if rc == 0 and os.path.exists(out):
                app.status.configure(text="小地图已生成: " + out)
                os.startfile(out)
            else:
                app.status.configure(text="小地图生成失败")
                messagebox.showerror("小地图", log[-2000:] or "生成失败")

        _ = app._post_gui_worker(ticket, finish)

    _ = app._start_gui_worker("render-minimap", work, replace=True)


def _show_guide(app, *, refresh: bool = False) -> None:
    """弹窗展示当前地图的攻略速查报告 (指令/任务/配方/商店/掉落)。"""
    md = getattr(app, "map_data", None)
    if not md or not getattr(md, "path", ""):
        messagebox.showinfo("攻略速查", "请先打开地图")
        return
    map_path = md.path
    cached = _GUIDE_CACHE.get(map_path)
    if cached and not refresh:
        _open_guide_window(app, cached)
        app.status.configure(text="攻略速查（缓存）已就绪")
        return
    app.status.configure(text="正在整理攻略速查 …")
    app.guide_button.configure(state="disabled")

    from .gui_worker_registry import GuiWorkerTicket

    def work(ticket: GuiWorkerTicket) -> None:
        import contextlib
        import io

        from .guide_cli import GuideCliOptions, run_guide_cli

        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                rc = run_guide_cli(
                    GuideCliOptions(
                        map_path=map_path,
                        section=None,
                        refresh=refresh,
                        minimap_marks=None,
                    )
                )
        except Exception as exc:  # BROAD_EXCEPT_OK - GUI worker boundary.
            from .presentation_safety import format_user_exception

            rc, log = 2, format_user_exception(exc, paths=(map_path,))
        else:
            log = buffer.getvalue()

        def finish():
            app.guide_button.configure(state="normal")
            if rc == 0 and log.strip():
                _GUIDE_CACHE[map_path] = log
                app.status.configure(text="攻略速查已就绪")
                _open_guide_window(app, log)
            else:
                app.status.configure(text="攻略速查失败")
                messagebox.showerror("攻略速查", log[-2000:] or "生成失败")

        _ = app._post_gui_worker(ticket, finish)

    _ = app._start_gui_worker("show-guide", work, replace=True)


def _open_guide_window(app, text: str) -> None:
    import tkinter as tk

    from .guide_report import GUIDE_SECTION_TITLES

    import customtkinter as ctk

    win = ctk.CTkToplevel(app)
    md = getattr(app, "map_data", None)
    map_name = getattr(md, "name", "") if md else ""
    win.title(f"攻略速查 — {map_name}" if map_name else "攻略速查")
    from .gui_pack_query import bind_geometry_memory

    bind_geometry_memory(win, "guide", "860x640")
    win.transient(app)
    win.grab_set()
    win.bind("<Escape>", lambda _e: win.destroy())
    win.bind("<Control-f>", lambda _e: search_entry.focus_set() or "break")
    win.bind(
        "<Control-a>",
        lambda _e: (
            box.tag_add("sel", "1.0", "end"),
            box.mark_set("insert", "end"),
            "break",
        )[2],
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

    search_entry.bind("<Return>", lambda _e: _find_next())
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
                _jump_to_section(box, t),
                _mark_active(t),
            ),  # box 闭包 late-binding: 点击时已定义
        )
        btn.pack(side="left", padx=(0, 4))
        section_buttons[title] = btn
    box = ctk.CTkTextbox(win, font=("Consolas", 12), wrap="none")
    box.pack(fill="both", expand=True, padx=8, pady=8)
    box.insert("1.0", text)
    saved = _GUIDE_SCROLL.get(md.path if (md := getattr(app, "map_data", None)) else "")
    if saved:
        box.mark_set("insert", saved)
        box.see(saved)
    win.bind(
        "<Destroy>",
        lambda _e: _GUIDE_SCROLL.update(
            {
                (
                    getattr(app, "map_data", None).path  # pyright: ignore[reportOptionalMemberAccess]
                    if getattr(app, "map_data", None)
                    else ""
                ): box.index("insert")
            }
        ),
    )
    guide_menu = tk.Menu(win, tearoff=0)
    guide_menu.add_command(
        label="复制选中",
        command=lambda: (
            (
                box.clipboard_clear(),
                box.clipboard_append(box.get("sel.first", "sel.last")),
            )
            if box.tag_ranges("sel")
            else None
        ),
    )
    guide_menu.add_command(
        label="复制全部",
        command=lambda: (
            box.clipboard_clear(),
            box.clipboard_append(box.get("1.0", "end")),
        ),
    )
    guide_menu.add_command(
        label="导出报告 (.md)",
        command=lambda: _export_guide(app, box.get("1.0", "end")),
    )
    guide_menu.add_command(
        label="强制重算 (清缓存刷新报告)",
        command=lambda: (_GUIDE_CACHE.clear(), _show_guide(app, refresh=True)),
    )
    guide_menu.add_separator()
    guide_menu.add_command(
        label="用选中/剪贴板坐标 near 反查",
        command=lambda: _near_selected_coords(app, box),
    )
    box.bind("<Button-3>", lambda e: guide_menu.tk_popup(e.x_root, e.y_root))
    win.bind("<Escape>", lambda _e: win.destroy())


def _near_selected_coords(app, box) -> None:
    """取选中/剪贴板的前两个数字, 打开包查询窗 near 模式反查。"""
    try:
        raw = box.get("sel.first", "sel.last").strip()
    except Exception:
        raw = ""
    if not raw:
        try:
            raw = box.clipboard_get().strip()
        except Exception:
            return
    import re  # noqa: PLC0415

    nums = re.findall(r"-?\d+(?:\.\d+)?", raw)
    if len(nums) < 2:
        return

    open_pack_query_dialog(
        app,
        lambda: getattr(app, "_last_pack_dir", None) or load_last_pack_dir(),
        app.on_export_pack,
        prefill=f"near {nums[0]} {nums[1]}",
        prefill_command="near",
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
