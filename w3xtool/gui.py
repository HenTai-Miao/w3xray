"""魔兽地图提取器 GUI（CustomTkinter，深色卡片风）。

编辑器式工作台：
- 总览：地图库存、脚本/触发、场景与风险快照
- 对象编辑器：模糊搜索 单位/物品/技能/科技 等，看详情、导出
- 地图信息 / 场景放置 / 触发指令 / 合成配方 / 孤立对象
- 分析报告：汇总审计、兼容、资源、命令、崩溃、秘籍等只读报告
"""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

import customtkinter as ctk

from collections import Counter

from .api import export_all_files, tmp_extract_dir, quick_map_name, MapData
from .search import compile_query
from .deferred_paned import add_deferred_pane, build_deferred_horizontal_paned
from .gui_load_settings import LoadSettingsMixin
from .gui_icon_cache import IconCacheMixin
from .gui_loader_runner import BackgroundLoaderMixin
from .gui_module_refresh import ModuleRefreshMixin
from .gui_object_filter_runner import ObjectFilterRunnerMixin
from .gui_pane_state import OBJECT_EDITOR_PANE_KEY, PaneStateMixin
from .gui_report_tabs import ReportTabsMixin
from .map_directory import scan_battle_maps
from .map_gallery import MapEntry, build_map_gallery, render_map_gallery
from .map_info import format_map_info
from .object_gallery import build_object_gallery, render_object_gallery
from .theme import (
    ACCENT,
    ACCENT_DARK,
    ACCENT_HOVER,
    BG,
    BORDER,
    CARD,
    CARD_RAISED,
    FONT,
    HEADER,
    INFO,
    MONO_FONT,
    MUTED,
    PANEL,
    PARALLEL_CATS,
    ROW_ALT,
    SECONDARY,
    SECONDARY_HOVER,
    SEL_BG,
    SEL_TEXT,
    SUBTLE,
    TEXT,
    TEXT_STRONG,
    TITLE_FONT,
    TOPBAR,
    card_style,
    entry_style,
    primary_button_style,
    secondary_button_style,
)
from PIL import Image
try:
    from .base_names import BASE_NAMES
except Exception:
    BASE_NAMES = {}

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("green")


class App(
    LoadSettingsMixin,
    IconCacheMixin,
    ModuleRefreshMixin,
    ObjectFilterRunnerMixin,
    PaneStateMixin,
    BackgroundLoaderMixin,
    ReportTabsMixin,
    ctk.CTk,
):
    def __init__(self):
        super().__init__()
        self.title("W3XRAY 魔兽地图提取器")
        self.geometry("1440x860")
        self.minsize(1040, 640)
        self.configure(fg_color=BG)

        self.map_data: MapData | None = None
        self.current_category = "全部"
        self.results = []
        self.commands = []
        self.recipes = []
        self.icons = None
        self.mode = "battle"            # battle=对战图 / campaign=战役图
        self._campaign_views = None     # 当前显示中战役: [(label, MapData)]
        self._campaign_path = None      # 当前打开的 .w3n 路径（图标跨档查找用）
        self._dir_campaigns = []        # 战役图左侧: [{path,name,loaded,views}]
        self._node_map = {}             # 树节点 iid -> (kind, payload)
        self._cur_dir = {"battle": None, "campaign": None}   # 各模式各记各的目录
        self._pil_icon_cache = {}  # icon path -> PIL image
        self._photo_cache = {}     # icon path/size/kind -> Tk image
        self._row_imgs = []        # 保持引用防止被回收
        self._blank = None
        self._init_load_options()
        self._init_background_loader()
        self._init_object_filter_runner()
        self._init_pane_state()
        self._build_topbar()
        self._build_tabs()
        self._build_statusbar()
        self._setup_tree_style()
        # 恢复上次的窗口大小/位置
        cfg = self._load_config()
        geo = cfg.get("geometry")
        if geo:
            try:
                self.geometry(geo)
            except Exception:
                pass
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(300, self._restore_last_dir)    # 启动后自动恢复上次的地图目录
        self.after(500, self._restore_pane_sashes)      # 恢复上次拖拽的分隔位置

    # ---------- 顶栏 ----------
    def _build_topbar(self):
        bar = ctk.CTkFrame(self, fg_color=TOPBAR, corner_radius=0, height=78,
                           border_width=1, border_color=BORDER)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)
        brand = ctk.CTkFrame(bar, fg_color="transparent")
        brand.pack(side="left", padx=(18, 14), pady=10)
        ctk.CTkLabel(brand, text="W3XRAY", font=(TITLE_FONT, 22, "bold"),
                     text_color=ACCENT).pack(anchor="w")
        ctk.CTkLabel(brand, text="魔兽地图提取器", font=(FONT, 12),
                     text_color=SUBTLE).pack(anchor="w", pady=(1, 0))

        ctk.CTkButton(bar, text="打开地图 / 战役", font=(FONT, 14, "bold"),
                      width=150, height=42, command=self.on_open,
                      **primary_button_style()).pack(side="left", padx=(0, 14))
        self.map_label = ctk.CTkLabel(
            bar, text="未打开", font=(FONT, 13), text_color=TEXT,
            fg_color=PANEL, corner_radius=6, height=34)
        self.map_label.pack(side="left", fill="x", expand=True, padx=(0, 16))

        actions = ctk.CTkFrame(bar, fg_color="transparent")
        actions.pack(side="right", padx=(0, 16))
        ctk.CTkButton(actions, text="导出全部", font=(FONT, 13), width=96, height=34,
                      command=self.on_export_all,
                      **secondary_button_style()).pack(side="right", padx=4)
        ctk.CTkButton(actions, text="导出脚本", font=(FONT, 13), width=88, height=34,
                      command=self.on_export_scripts,
                      **secondary_button_style()).pack(side="right", padx=4)
        ctk.CTkButton(actions, text="导出ID", font=(FONT, 13), width=78, height=34,
                      command=self.on_export_ids,
                      **secondary_button_style()).pack(side="right", padx=4)

    def _build_tabs(self):
        shell = ctk.CTkFrame(self, fg_color=BG)
        shell.pack(fill="both", expand=True, padx=14, pady=(10, 8))

        source = ctk.CTkFrame(shell, fg_color=TOPBAR, corner_radius=22,
                              border_width=1, border_color=BORDER, height=54)
        source.pack(fill="x", pady=(0, 8))
        source.pack_propagate(False)
        ctk.CTkLabel(source, text="图源", font=(FONT, 11, "bold"),
                     text_color=MUTED).pack(side="left", padx=(16, 8))
        self.mode_seg = ctk.CTkSegmentedButton(
            source, values=["对战图", "战役图"], command=self._on_mode_change,
            font=(FONT, 12, "bold"), height=32,
            selected_color=ACCENT_DARK, selected_hover_color=ACCENT_HOVER,
            unselected_color=CARD, unselected_hover_color=CARD_RAISED,
            fg_color=PANEL, text_color=TEXT)
        self.mode_seg.set("对战图")
        self.mode_seg.pack(side="left", pady=10)

        self.tabs = ctk.CTkTabview(
            shell, fg_color=BG,
            segmented_button_selected_color=ACCENT_DARK,
            segmented_button_selected_hover_color=ACCENT_HOVER,
            segmented_button_unselected_color=CARD,
            segmented_button_unselected_hover_color=CARD_RAISED,
            text_color=TEXT,
        )
        self.tabs.pack(fill="both", expand=True, padx=0, pady=(0, 2))
        self.editor_tab_labels = (
            "总览", "对象编辑器", "地图信息", "场景放置", "触发指令",
            "合成配方", "孤立对象", "分析报告")
        self.tab_overview = self.tabs.add("总览")
        self.tab_obj = self.tabs.add("对象编辑器")
        self.tab_info = self.tabs.add("地图信息")
        self.tab_pre = self.tabs.add("场景放置")
        self.tab_cmd = self.tabs.add("触发指令")
        self.tab_rec = self.tabs.add("合成配方")
        self.tab_orphan = self.tabs.add("孤立对象")
        self.tab_analysis = self.tabs.add("分析报告")
        self._build_overview_tab(self.tab_overview)
        self._build_obj_tab(self.tab_obj)
        self._build_info_tab(self.tab_info)
        self._build_preplaced_tab(self.tab_pre)
        self._build_cmd_tab(self.tab_cmd)
        self._build_rec_tab(self.tab_rec)
        self._build_orphan_tab(self.tab_orphan)
        self._build_analysis_tab(self.tab_analysis)
        self._refresh_editor_reports()

    def _build_obj_tab(self, parent):
        head = ctk.CTkFrame(parent, fg_color=BG)
        head.pack(fill="x", padx=2, pady=(2, 6))
        ctk.CTkLabel(head, text="对象解剖台", font=(TITLE_FONT, 18, "bold"),
                     text_color=TEXT_STRONG, anchor="w").pack(side="left")
        ctk.CTkLabel(head, text="单位 · 物品 · 技能 · 科技 · 可破坏物 · 装饰物 · 增益", font=(FONT, 12),
                     text_color=SUBTLE).pack(side="left", padx=12)

        # 顶部搜索（过滤所有列）
        ctrl = ctk.CTkFrame(parent, fg_color=BG)
        ctrl.pack(fill="x", padx=2, pady=(0, 8))
        self.search_var = tk.StringVar()
        se = ctk.CTkEntry(ctrl, textvariable=self.search_var, height=40, font=(FONT, 13),
                          justify="center",
                          placeholder_text='回车搜索：名称 / ID / 字段内容    %词%=包含    ="…"=精准    && / ||',
                          **entry_style())
        se.pack(fill="x")
        se.bind("<Return>", lambda *_: self._refresh_list())   # 回车再搜：逐键不重建，大图不卡
        self._attach_ctx_menu(se, paste=True)

        body = ctk.CTkFrame(parent, fg_color=BG)
        body.pack(fill="both", expand=True)
        # 可拖拽分隔：地图列表 | 物品 | 单位 | 技能 | 科技 | 描述，拖动中间分隔条调宽
        paned = build_deferred_horizontal_paned(body)
        paned.pack(fill="both", expand=True)
        self.paned = paned
        self._register_paned_window(OBJECT_EDITOR_PANE_KEY, paned)

        # 左：地图列表（对战图=文件夹地图；战役图=战役共享+各子图）
        leftp = ctk.CTkFrame(paned, width=150, **card_style())
        self.left_brow = ctk.CTkFrame(leftp, fg_color="transparent")
        self.left_brow.pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkButton(self.left_brow, text="选择目录", height=32, font=(FONT, 12, "bold"),
                      command=self.on_pick_dir,
                      **secondary_button_style()).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(self.left_brow, text="⟳", width=30, height=30, font=(FONT, 14),
                      fg_color=SECONDARY, hover_color=SECONDARY_HOVER, text_color=TEXT,
                      corner_radius=6,
                      command=self.on_refresh_dir).pack(side="right", padx=(4, 0))
        self.left_title = ctk.CTkLabel(leftp, text="地图列表", font=(FONT, 12, "bold"),
                                       text_color=TEXT_STRONG, anchor="w")
        self.left_title.pack(fill="x", padx=10)
        self.map_search = tk.StringVar()
        mse = ctk.CTkEntry(leftp, textvariable=self.map_search, height=28, font=(FONT, 11),
                           justify="center", placeholder_text="回车搜索地图",
                           **entry_style())
        mse.pack(fill="x", padx=8, pady=(0, 4))
        mse.bind("<Return>", lambda *_: self._populate_left())   # 回车再过滤地图列表
        self._attach_ctx_menu(mse, paste=True)
        self.map_gallery = build_map_gallery(leftp)
        legacy_maps = tk.Frame(leftp, bg=CARD)
        self.map_list = ttk.Treeview(legacy_maps, show="tree", selectmode="browse")
        self.map_list.column("#0", stretch=False)        # 配合横向滚动看全长地图名
        mvsb = ttk.Scrollbar(legacy_maps, orient="vertical", command=self.map_list.yview)
        mhsb = ttk.Scrollbar(legacy_maps, orient="horizontal", command=self.map_list.xview)
        self.map_list.configure(yscrollcommand=mvsb.set, xscrollcommand=mhsb.set)
        self.map_list.bind("<Double-1>", self._on_map_pick)   # 双击才加载/切换
        self.map_list.bind("<<TreeviewOpen>>", self._on_tree_open)
        self._map_gallery_entries = []
        self._render_map_gallery()
        self._dir_maps = []
        add_deferred_pane(paned, leftp, minsize=130, stretch="never")

        # 中：对象卡片网格。旧 Treeview 保留在隐藏兼容层，主视觉不再是四个竖向表格。
        self.col_trees = {}
        self.col_results = {}
        self.col_headers = {}
        self.active_object_category = PARALLEL_CATS[0]
        self.object_gallery = build_object_gallery(paned, self._on_object_category)
        self.object_gallery_hint = self.object_gallery.hint
        self.object_cat_buttons = self.object_gallery.buttons
        self.object_cards = self.object_gallery.cards
        add_deferred_pane(paned, self.object_gallery.container, minsize=360, stretch="always")

        legacy = tk.Frame(self.object_gallery.container)
        for cat in PARALLEL_CATS:
            hdr = ctk.CTkLabel(self.object_gallery.container, text=cat)
            self.col_headers[cat] = hdr
            tv = ttk.Treeview(legacy, show="tree", selectmode="browse")
            tv.column("#0", width=80, minwidth=50, stretch=False, anchor="w")
            hsb = ttk.Scrollbar(legacy, orient="horizontal", command=tv.xview)
            tv.configure(xscrollcommand=hsb.set)
            tv.bind("<<TreeviewSelect>>", lambda e, c=cat: self._on_col_select(c))
            self._attach_tree_copy(tv)
            self.col_trees[cat] = tv
            self.col_results[cat] = []

        # 右：描述
        rightp = ctk.CTkFrame(paned, width=340, **card_style())
        detail_head = ctk.CTkFrame(rightp, fg_color="transparent")
        detail_head.pack(fill="x", padx=12, pady=(12, 2))
        blank_icon = Image.new("RGBA", (36, 36), (0, 0, 0, 0))
        self.detail_blank_icon = ctk.CTkImage(
            light_image=blank_icon, dark_image=blank_icon, size=(36, 36)
        )
        self.detail_icon_image = self.detail_blank_icon
        self.detail_icon = ctk.CTkLabel(
            detail_head, text="", image=self.detail_icon_image, width=42, height=42,
            fg_color=PANEL, corner_radius=10,
        )
        self.detail_icon.pack(side="left", padx=(0, 10))
        detail_text = ctk.CTkFrame(detail_head, fg_color="transparent")
        detail_text.pack(side="left", fill="x", expand=True)
        self.detail_title = ctk.CTkLabel(detail_text, text="选择对象查看详情",
                                         font=(FONT, 15, "bold"),
                                         text_color=TEXT_STRONG, anchor="w",
                                         justify="left", wraplength=390)
        self.detail_title.pack(fill="x")
        self.detail_sub = ctk.CTkLabel(rightp, text="", font=(FONT, 11),
                                       text_color=SUBTLE, anchor="w", wraplength=420, justify="left")
        self.detail_sub.pack(fill="x", padx=12)
        self.detail = ctk.CTkTextbox(rightp, font=(MONO_FONT, 12),
                                     fg_color=PANEL, text_color=TEXT,
                                     border_width=1, border_color=BORDER, wrap="word")
        self.detail.pack(fill="both", expand=True, padx=10, pady=10)
        self.detail.configure(state="disabled")
        self._attach_ctx_menu(self.detail, copy_all=True)
        add_deferred_pane(paned, rightp, minsize=260, stretch="never")
        self._render_object_cards()

    def _build_cmd_tab(self, parent):
        top = ctk.CTkFrame(parent, fg_color=BG)
        top.pack(fill="x", padx=2, pady=(8, 6))
        self.cmd_search = tk.StringVar()
        cse = ctk.CTkEntry(top, textvariable=self.cmd_search, height=40, font=(FONT, 13),
                           justify="center",
                           placeholder_text='回车搜索：指令 / 说明    %词%=包含    ="…"=精准',
                           **entry_style())
        cse.pack(fill="x")
        cse.bind("<Return>", lambda *_: self._refresh_cmds())   # 回车再搜
        self._attach_ctx_menu(cse, paste=True)
        self.cmd_hint = ctk.CTkLabel(parent, text="打开地图后这里列出脚本里的全部聊天指令（含隐藏指令）",
                                     font=(FONT, 12), text_color=SUBTLE, anchor="w")
        self.cmd_hint.pack(fill="x", padx=6, pady=(0, 6))
        wrap = ctk.CTkFrame(parent, **card_style())
        wrap.pack(fill="both", expand=True)
        inner = tk.Frame(wrap, bg=CARD)
        inner.pack(fill="both", expand=True, padx=8, pady=8)
        self.cmd_tree = ttk.Treeview(inner, columns=("cmd", "match", "hint"),
                                     show="headings", selectmode="browse")
        for c, t, w, a in (("cmd", "指令", 180, "w"), ("match", "匹配", 70, "center"),
                           ("hint", "说明(脚本提示)", 420, "w")):
            self.cmd_tree.heading(c, text=t)
            self.cmd_tree.column(c, width=w, anchor=a, stretch=False)
        vsb = ttk.Scrollbar(inner, orient="vertical", command=self.cmd_tree.yview)
        hsb = ttk.Scrollbar(inner, orient="horizontal", command=self.cmd_tree.xview)
        self.cmd_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.cmd_tree.pack(side="left", fill="both", expand=True)
        self._attach_tree_copy(self.cmd_tree)

    def _build_rec_tab(self, parent):
        top = ctk.CTkFrame(parent, fg_color=BG)
        top.pack(fill="x", padx=2, pady=(8, 6))
        self.rec_search = tk.StringVar()
        rse = ctk.CTkEntry(top, textvariable=self.rec_search, height=40, font=(FONT, 13),
                           justify="center",
                           placeholder_text='回车搜索：材料 / 成品名称    %词%=包含    ="…"=精准',
                           **entry_style())
        rse.pack(fill="x")
        rse.bind("<Return>", lambda *_: self._refresh_recipes())   # 回车再搜
        self._attach_ctx_menu(rse, paste=True)
        self.rec_hint = ctk.CTkLabel(parent, text="打开地图后这里列出脚本里识别到的物品合成配方",
                                     font=(FONT, 12), text_color=SUBTLE, anchor="w")
        self.rec_hint.pack(fill="x", padx=6, pady=(0, 6))
        wrap = ctk.CTkFrame(parent, **card_style())
        wrap.pack(fill="both", expand=True)
        inner = tk.Frame(wrap, bg=CARD)
        inner.pack(fill="both", expand=True, padx=8, pady=8)
        self.rec_tree = ttk.Treeview(inner, columns=("result", "ingredients"),
                                     show="headings", selectmode="browse")
        self.rec_tree.heading("result", text="成品")
        self.rec_tree.heading("ingredients", text="材料（合成所需）")
        self.rec_tree.column("result", width=220, anchor="w", stretch=False)
        self.rec_tree.column("ingredients", width=620, anchor="w", stretch=False)
        vsb = ttk.Scrollbar(inner, orient="vertical", command=self.rec_tree.yview)
        hsb = ttk.Scrollbar(inner, orient="horizontal", command=self.rec_tree.xview)
        self.rec_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.rec_tree.pack(side="left", fill="both", expand=True)
        self._attach_tree_copy(self.rec_tree)

    def _build_orphan_tab(self, parent):
        """孤立对象：定义了、但没被任何对象/脚本/预放置引用的自定义对象（只读报告）。"""
        top = ctk.CTkFrame(parent, fg_color=BG)
        top.pack(fill="x", padx=2, pady=(8, 6))
        self.orphan_search = tk.StringVar()
        ose = ctk.CTkEntry(top, textvariable=self.orphan_search, height=40, font=(FONT, 13),
                           justify="center",
                           placeholder_text='回车搜索：名称 / ID / 分类    %词%=包含    ="…"=精准',
                           **entry_style())
        ose.pack(fill="x")
        ose.bind("<Return>", lambda *_: self._refresh_orphans())
        self._attach_ctx_menu(ose, paste=True)
        self.orphan_hint = ctk.CTkLabel(
            parent, text="打开地图后这里列出「孤立」自定义对象——定义了但没被任何对象/脚本/预放置引用的废弃对象",
            font=(FONT, 12), text_color=SUBTLE, anchor="w")
        self.orphan_hint.pack(fill="x", padx=6, pady=(0, 6))
        wrap = ctk.CTkFrame(parent, **card_style())
        wrap.pack(fill="both", expand=True)
        inner = tk.Frame(wrap, bg=CARD)
        inner.pack(fill="both", expand=True, padx=8, pady=8)
        self.orphan_tree = ttk.Treeview(inner, columns=("cat", "id", "name"),
                                        show="headings", selectmode="browse")
        for c, t, w, a in (("cat", "分类", 90, "center"), ("id", "ID", 80, "center"),
                           ("name", "名称", 480, "w")):
            self.orphan_tree.heading(c, text=t)
            self.orphan_tree.column(c, width=w, anchor=a, stretch=False)
        vsb = ttk.Scrollbar(inner, orient="vertical", command=self.orphan_tree.yview)
        hsb = ttk.Scrollbar(inner, orient="horizontal", command=self.orphan_tree.xview)
        self.orphan_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.orphan_tree.pack(side="left", fill="both", expand=True)
        self._attach_tree_copy(self.orphan_tree)

    def _refresh_orphans(self):
        if not hasattr(self, "orphan_tree"):
            return
        self.orphan_tree.delete(*self.orphan_tree.get_children())
        orphans = getattr(self.map_data, "orphans", []) if self.map_data else []
        q = self.orphan_search.get().strip()
        cq = compile_query(q)
        n = 0
        for o in orphans:
            blob = f"{o.category} {o.obj_id} {o.name}"
            if q and cq.score(blob) is None:
                continue
            self.orphan_tree.insert("", "end", values=(o.category, o.obj_id, o.name),
                                    tags=("odd" if n % 2 else "even",))
            n += 1
        self.orphan_tree.tag_configure("odd", background=ROW_ALT)
        self.orphan_tree.tag_configure("even", background=CARD)
        total = len(orphans)
        low = bool(getattr(self.map_data, "ref_low_coverage", False))
        if total and low:
            self.orphan_hint.configure(
                text=f"孤立自定义对象：{n}/{total} —— ⚠ 此图引用覆盖低（疑为 SLK 优化图，"
                     "单位→技能等引用在未解析的 .slk 里），下列多为误报，仅供参考")
        elif total:
            self.orphan_hint.configure(
                text=f"孤立自定义对象：{n}/{total} —— 定义了但没被任何对象/脚本/预放置引用"
                     "（只读报告，不会改图；可能是作者留下的废弃对象）")
        else:
            self.orphan_hint.configure(
                text="未发现孤立自定义对象（每个自定义对象都被引用，或此图无自定义对象数据）")

    def _build_info_tab(self, parent):
        """地图信息：war3map.w3i 解析出的名/作者/描述/玩家/队伍/脚本语言等，只读文本。"""
        self.info_box = ctk.CTkTextbox(parent, font=(MONO_FONT, 13),
                                       fg_color=PANEL, text_color=TEXT,
                                       border_width=1, border_color=BORDER, wrap="word")
        self.info_box.pack(fill="both", expand=True, padx=4, pady=8)
        self.info_box.configure(state="disabled")
        self._attach_ctx_menu(self.info_box, copy_all=True)

    def _refresh_info(self):
        self.info_box.configure(state="normal")
        self.info_box.delete("1.0", "end")
        self.info_box.insert("end", format_map_info(self.map_data))
        self.info_box.configure(state="disabled")

    def _build_preplaced_tab(self, parent):
        """预放置实例：上=单位(war3mapUnits.doo)，下=装饰物/可破坏物(war3map.doo)，共用搜索框。"""
        top = ctk.CTkFrame(parent, fg_color=BG)
        top.pack(fill="x", padx=2, pady=(8, 6))
        self.pre_search = tk.StringVar()
        pse = ctk.CTkEntry(top, textvariable=self.pre_search, height=40, font=(FONT, 13),
                           justify="center",
                           placeholder_text='回车搜索：类型名 / ID    %词%=包含    ="…"=精准',
                           **entry_style())
        pse.pack(fill="x")
        pse.bind("<Return>", lambda *_: self._refresh_preplaced())
        self._attach_ctx_menu(pse, paste=True)
        self.pre_hint = ctk.CTkLabel(parent, text="打开地图后这里列出地图上预放置的单位与装饰物（摆在哪、归谁、初始属性）",
                                     font=(FONT, 12), text_color=SUBTLE, anchor="w")
        self.pre_hint.pack(fill="x", padx=6, pady=(0, 6))

        # 上：预放置单位
        self.unit_title = ctk.CTkLabel(parent, text="预放置单位", font=(FONT, 12, "bold"),
                                       text_color=INFO, anchor="w")
        self.unit_title.pack(fill="x", padx=8)
        uw = ctk.CTkFrame(parent, **card_style())
        uw.pack(fill="both", expand=True, padx=4, pady=(0, 6))
        ui = tk.Frame(uw, bg=CARD)
        ui.pack(fill="both", expand=True, padx=8, pady=8)
        self.unit_tree = ttk.Treeview(
            ui, columns=("name", "id", "player", "pos", "hp", "mana", "lv"),
            show="headings", selectmode="browse")
        for c, t, w, a in (("name", "类型", 220, "w"), ("id", "ID", 60, "center"),
                           ("player", "玩家", 50, "center"), ("pos", "坐标(x, y)", 150, "center"),
                           ("hp", "生命", 70, "center"), ("mana", "魔法", 70, "center"),
                           ("lv", "等级", 50, "center")):
            self.unit_tree.heading(c, text=t)
            self.unit_tree.column(c, width=w, anchor=a, stretch=False)
        uvsb = ttk.Scrollbar(ui, orient="vertical", command=self.unit_tree.yview)
        uhsb = ttk.Scrollbar(ui, orient="horizontal", command=self.unit_tree.xview)
        self.unit_tree.configure(yscrollcommand=uvsb.set, xscrollcommand=uhsb.set)
        uvsb.pack(side="right", fill="y")
        uhsb.pack(side="bottom", fill="x")
        self.unit_tree.pack(side="left", fill="both", expand=True)
        self._attach_tree_copy(self.unit_tree)

        # 下：装饰物/可破坏物
        self.doodad_title = ctk.CTkLabel(parent, text="装饰物 / 可破坏物", font=(FONT, 12, "bold"),
                                         text_color=ACCENT, anchor="w")
        self.doodad_title.pack(fill="x", padx=8)
        dw = ctk.CTkFrame(parent, **card_style())
        dw.pack(fill="both", expand=True, padx=4, pady=(0, 6))
        di = tk.Frame(dw, bg=CARD)
        di.pack(fill="both", expand=True, padx=8, pady=8)
        self.doodad_tree = ttk.Treeview(
            di, columns=("name", "id", "pos", "scale", "life", "drops"),
            show="headings", selectmode="browse")
        for c, t, w, a in (("name", "类型", 220, "w"), ("id", "ID", 60, "center"),
                           ("pos", "坐标(x, y)", 150, "center"), ("scale", "缩放", 70, "center"),
                           ("life", "生命%", 60, "center"), ("drops", "掉落", 200, "w")):
            self.doodad_tree.heading(c, text=t)
            self.doodad_tree.column(c, width=w, anchor=a, stretch=False)
        dvsb = ttk.Scrollbar(di, orient="vertical", command=self.doodad_tree.yview)
        dhsb = ttk.Scrollbar(di, orient="horizontal", command=self.doodad_tree.xview)
        self.doodad_tree.configure(yscrollcommand=dvsb.set, xscrollcommand=dhsb.set)
        dvsb.pack(side="right", fill="y")
        dhsb.pack(side="bottom", fill="x")
        self.doodad_tree.pack(side="left", fill="both", expand=True)
        self._attach_tree_copy(self.doodad_tree)

    def _refresh_preplaced(self):
        if not self.map_data:
            return
        q = self.pre_search.get().strip()
        cq = compile_query(q)
        units = getattr(self.map_data, "units", []) or []
        doodads = getattr(self.map_data, "doodads", []) or []

        self.unit_tree.delete(*self.unit_tree.get_children())
        nu = 0
        for u in units:
            name = self._item_name(u.type_id)
            blob = name + " " + u.type_id
            if q and cq.score(blob) is None:
                continue
            hp = "默认" if u.hp < 0 else str(u.hp)
            mana = "默认" if u.mana < 0 else str(u.mana)
            self.unit_tree.insert(
                "", "end",
                values=(name, u.type_id, u.player, f"{u.x:.0f}, {u.y:.0f}",
                        hp, mana, u.hero_level),
                tags=("odd" if nu % 2 else "even",))
            nu += 1
        self.unit_tree.tag_configure("odd", background=ROW_ALT)
        self.unit_tree.tag_configure("even", background=CARD)

        self.doodad_tree.delete(*self.doodad_tree.get_children())
        nd = 0
        for d in doodads:
            name = self._item_name(d.type_id)
            blob = name + " " + d.type_id
            if q and cq.score(blob) is None:
                continue
            drops = "  ".join(f"{self._item_name(i)}×{c}%" for i, c in d.drops)
            scale = f"{d.scale[0]:.2g}" if d.scale else "1"
            self.doodad_tree.insert(
                "", "end",
                values=(name, d.type_id, f"{d.x:.0f}, {d.y:.0f}", scale, d.life, drops),
                tags=("odd" if nd % 2 else "even",))
            nd += 1
        self.doodad_tree.tag_configure("odd", background=ROW_ALT)
        self.doodad_tree.tag_configure("even", background=CARD)

        self.unit_title.configure(text=f"预放置单位  ({nu})")
        self.doodad_title.configure(text=f"装饰物 / 可破坏物  ({nd})")
        if units or doodads:
            self.pre_hint.configure(
                text=f"预放置：{len(units)} 单位 · {len(doodads)} 装饰物/可破坏物"
                     "（坐标为地图世界坐标；生命=默认表示用对象定义里的满血）")
        else:
            self.pre_hint.configure(text="此图无预放置数据（war3mapUnits.doo / war3map.doo 缺失或为空）")

    def _item_name(self, code):
        if self.map_data:
            o = self.map_data.obj_index.get(code)
            if o and o.name and o.name != code:
                return f"{o.name}({code})"
        bn = BASE_NAMES.get(code)
        return f"{bn}({code})" if bn else code

    def _measure_font(self):
        """缓存一个与表格行同字体的测量用 Font，用来算列该多宽。"""
        if not hasattr(self, "_rec_font"):
            self._rec_font = tkfont.Font(family=FONT, size=11)
        return self._rec_font

    def _autosize_tree(self, tree, col="#0", minw=120, pad=46):
        """按 col 列(默认树主列 #0)里最长文本自适应列宽，配合横向滚动条把长名字看全。

        stretch=False 让列保持该宽度而非压回可视宽度——内容更宽时横向滚动条才有可滚区间。"""
        f = self._measure_font()
        widest = 0
        stack = list(tree.get_children(""))
        while stack:
            iid = stack.pop()
            widest = max(widest, f.measure(tree.item(iid, "text")))
            stack.extend(tree.get_children(iid))
        tree.column(col, width=max(minw, widest + pad), stretch=False)

    def _refresh_recipes(self):
        q = self.rec_search.get().strip()
        cq = compile_query(q)                 # 编译一次，下面每条配方复用
        self.rec_tree.delete(*self.rec_tree.get_children())
        n = 0
        widest = 0
        f = self._measure_font()
        for r in self.recipes:
            res_name = self._item_name(r.result)
            counts = Counter(r.ingredients)
            ing_parts = []
            for code, cnt in counts.items():
                nm = self._item_name(code)
                ing_parts.append(f"{nm}×{cnt}" if cnt > 1 else nm)
            ing_str = "  +  ".join(ing_parts)
            if q and cq.score(res_name + " " + ing_str) is None:
                continue
            self.rec_tree.insert("", "end", values=(res_name, ing_str),
                                 tags=("odd" if n % 2 else "even",))
            widest = max(widest, f.measure(ing_str))
            n += 1
        # 材料列按最长内容自适应宽度，配合横向滚动条看全（不会自动换行）
        self.rec_tree.column("ingredients", width=max(620, widest + 28))
        self.rec_tree.tag_configure("odd", background=ROW_ALT)
        self.rec_tree.tag_configure("even", background=CARD)
        if self.recipes:
            self.rec_hint.configure(text=f"识别到 {len(self.recipes)} 个合成配方"
                                    "（尽力识别，标准 YDWE 写法准确；非标准写法可能漏检）")
        else:
            self.rec_hint.configure(text="未识别到合成配方（此图可能无合成，或用了非标准写法）")

    def _build_statusbar(self):
        bar = ctk.CTkFrame(self, fg_color=TOPBAR, corner_radius=0, height=34,
                           border_width=1, border_color=BORDER)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        self.status = ctk.CTkLabel(bar, text="就绪 · 点击「打开地图」开始", anchor="w",
                                   font=(FONT, 12), text_color=SUBTLE)
        self.status.pack(fill="both", expand=True, padx=16)

    def _setup_tree_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", background=CARD, fieldbackground=CARD,
                        foreground=TEXT, rowheight=31, borderwidth=0,
                        relief="flat", font=(FONT, 11))
        style.configure("Treeview.Heading", background=HEADER, foreground=TEXT_STRONG,
                        font=(FONT, 11, "bold"), borderwidth=0, relief="flat")
        style.map("Treeview", background=[("selected", SEL_BG)],
                  foreground=[("selected", SEL_TEXT)])
        style.map("Treeview.Heading", background=[("active", CARD_RAISED)])
        # 细化滚动条，融入深色
        style.configure("Vertical.TScrollbar", background=SECONDARY,
                        troughcolor=PANEL, borderwidth=0, arrowsize=11)
        style.configure("Horizontal.TScrollbar", background=SECONDARY,
                        troughcolor=PANEL, borderwidth=0, arrowsize=11)

    # ---------- 右键菜单 ----------
    def _attach_ctx_menu(self, ctk_widget, paste=False, copy_all=False):
        """给输入框/文本框挂右键复制/粘贴菜单。"""
        inner = (getattr(ctk_widget, "_entry", None)
                 or getattr(ctk_widget, "_textbox", None) or ctk_widget)
        menu = tk.Menu(self, tearoff=0)
        if copy_all:
            menu.add_command(label="复制全部",
                             command=lambda: self._copy_all_text(ctk_widget))
        menu.add_command(label="复制", command=lambda: inner.event_generate("<<Copy>>"))
        if paste:
            menu.add_command(label="粘贴", command=lambda: inner.event_generate("<<Paste>>"))

        def popup(e):
            try:
                menu.tk_popup(e.x_root, e.y_root)
            finally:
                menu.grab_release()
        inner.bind("<Button-3>", popup)

    def _copy_all_text(self, textbox):
        try:
            txt = textbox.get("1.0", "end-1c")
            self.clipboard_clear()
            self.clipboard_append(txt)
        except Exception:
            pass

    def _attach_tree_copy(self, tree):
        """给表格(Treeview)挂右键「复制选中行」。"""
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="复制", command=lambda: self._copy_tree_row(tree))

        def popup(e):
            row = tree.identify_row(e.y)
            if row and row not in tree.selection():
                tree.selection_set(row)
                tree.focus(row)
            try:
                menu.tk_popup(e.x_root, e.y_root)
            finally:
                menu.grab_release()
        tree.bind("<Button-3>", popup)

    def _copy_tree_row(self, tree):
        sel = tree.selection()
        if not sel:
            return
        lines = []
        for iid in sel:
            text = str(tree.item(iid, "text")).strip()
            vals = [str(v) for v in tree.item(iid, "values") if str(v).strip()]
            parts = ([text] if text else []) + vals
            lines.append("\t".join(parts))
        if lines:
            self.clipboard_clear()
            self.clipboard_append("\n".join(lines))

    # ---------- 地图目录列表 ----------
    def _config_path(self):
        return os.path.join(os.path.expanduser("~"), ".w3x_extractor.json")

    def _save_config(self, **kw):
        import json
        cfg = {}
        try:
            with open(self._config_path(), "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
        cfg.update(kw)
        try:
            with open(self._config_path(), "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False)
        except Exception:
            pass

    def _load_config(self):
        import json
        try:
            with open(self._config_path(), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _restore_last_dir(self):
        cfg = self._load_config()
        db = cfg.get("last_dir_battle") or cfg.get("last_dir")   # 兼容旧的单一 last_dir
        dc = cfg.get("last_dir_campaign")
        if db and os.path.isdir(db):
            self._cur_dir["battle"] = db
            self._scan_dir(db, "battle")
        if dc and os.path.isdir(dc):
            self._cur_dir["campaign"] = dc
            self._scan_dir(dc, "campaign")

    def _on_close(self):
        # 保存窗口几何 + 分隔条位置，供下次启动恢复
        self._shutdown_background_loader()
        self._shutdown_object_filter_runner()
        self._save_layout_state(geometry=self.geometry())
        if self.icons is not None and hasattr(self.icons, "close"):
            try:
                self.icons.close()           # 退出时释放当前图标解析器的句柄
            except Exception:
                pass
        self.destroy()

    def on_pick_dir(self):
        kind = "战役" if self.mode == "campaign" else "对战图"
        d = filedialog.askdirectory(title=f"选择存放{kind}的目录")
        if not d:
            return
        self._cur_dir[self.mode] = d
        self._save_config(**{f"last_dir_{self.mode}": d})
        self._scan_dir(d, self.mode)

    def on_refresh_dir(self):
        d = self._cur_dir.get(self.mode) or self._load_config().get(f"last_dir_{self.mode}")
        if d and os.path.isdir(d):
            self._scan_dir(d, self.mode)
        else:
            self.status.configure(text="还没选过目录，先点「选择地图目录」")

    def _scan_dir(self, d, mode):
        import glob
        self._cur_dir[mode] = d
        self.status.configure(text="正在扫描目录 …")
        self.update_idletasks()

        def work():
            if mode == "campaign":
                # 战役只列文件名，不解析里面的数据；等点击某战役才 load_map
                files = glob.glob(os.path.join(d, "**", "*.w3n"), recursive=True)
                files = sorted(set(files), key=lambda p: os.path.getmtime(p), reverse=True)
                items = [{"path": p, "name": os.path.basename(p),
                          "loaded": False, "views": None} for p in files]
                self.after(0, lambda: self._fill_campaign(items))
            else:
                items = scan_battle_maps(d)
                self.after(0, lambda: self._fill_battle(items))
        threading.Thread(target=work, daemon=True).start()

    def _fill_battle(self, items):
        self._dir_maps = items
        if self.mode == "battle":
            self._populate_left()
        self.status.configure(text=f"对战图目录：找到 {len(items)} 张")

    def _fill_campaign(self, items):
        self._dir_campaigns = items
        if self.mode == "campaign":
            self._populate_left()
        self.status.configure(text=f"战役目录：找到 {len(items)} 个（点战役展开看子地图）")

    # ---------- 一级模式 + 左侧列表 ----------
    def _populate_left(self):
        # 两种模式都显示「选择地图目录 + ⟳」
        if not self.left_brow.winfo_manager():
            self.left_brow.pack(fill="x", padx=8, pady=(8, 4), before=self.left_title)
        if self.mode == "campaign":
            self.left_title.configure(text="战役列表")
            self._refresh_campaign_tree()
        else:
            self.left_title.configure(text="地图列表")
            self._refresh_left_list()

    def _refresh_left_list(self):
        """对战图：扁平地图列表。"""
        q = self.map_search.get().strip().lower() if hasattr(self, "map_search") else ""
        self._node_map = {}
        entries = []
        self.map_list.delete(*self.map_list.get_children())
        for i, (p, name) in enumerate(self._dir_maps):
            if q and q not in name.lower():
                continue
            iid = f"m{i}"
            self.map_list.insert("", "end", iid=iid, text=f" {name}")
            self._node_map[iid] = ("path", p)
            entries.append(MapEntry(iid=iid, title=name, subtitle=os.path.basename(p),
                                    action="打开地图"))
        self._autosize_tree(self.map_list, minw=130)   # 长地图名也能横向滚动看全
        self._map_gallery_entries = entries
        self._render_map_gallery()

    def _refresh_campaign_tree(self):
        """战役图：树形——战役为父节点，展开显示子地图(★共享+各关卡)。"""
        q = self.map_search.get().strip().lower() if hasattr(self, "map_search") else ""
        self._node_map = {}
        entries = []
        self.map_list.delete(*self.map_list.get_children())
        for i, camp in enumerate(self._dir_campaigns):
            if q and q not in camp["name"].lower():
                continue
            pid = f"c{i}"
            self.map_list.insert("", "end", iid=pid, text=f" {camp['name']}",
                                 open=bool(camp["loaded"]))
            self._node_map[pid] = ("campaign", i)
            action = "查看子图" if camp["loaded"] else "加载战役"
            entries.append(MapEntry(iid=pid, title=camp["name"],
                                    subtitle="战役图 · 共享对象与关卡子图", action=action))
            if camp["loaded"] and camp["views"]:
                for j, (label, md) in enumerate(camp["views"]):
                    cid = f"{pid}_s{j}"
                    self.map_list.insert(pid, "end", iid=cid, text=f" {label}")
                    self._node_map[cid] = ("md", md)
                    entries.append(MapEntry(iid=cid, title=label, subtitle=md.name,
                                            action="切换子图", depth=1))
            else:
                self.map_list.insert(pid, "end", iid=f"{pid}_load", text="  （展开加载…）")
        self._autosize_tree(self.map_list, minw=130)   # 长战役/子图名也能横向滚动看全
        self._map_gallery_entries = entries
        self._render_map_gallery()

    def _render_map_gallery(self):
        if not hasattr(self, "map_gallery"):
            return
        render_map_gallery(self.map_gallery, self._map_gallery_entries, self._open_node)

    def _on_mode_change(self, mode):
        self.mode = "campaign" if mode == "战役图" else "battle"
        self.map_search.set("")      # 战役与对战是两套独立列表，切模式清空搜索
        self._populate_left()

    def _on_tree_open(self, _evt):
        sel = self.map_list.focus()
        info = self._node_map.get(sel)
        if info and info[0] == "campaign":
            idx = info[1]
            if not self._dir_campaigns[idx]["loaded"]:
                self._load_campaign_node(idx)

    def _load_campaign_node(self, idx):
        self._start_campaign_load(idx)

    def _open_node(self, node_id):
        info = self._node_map.get(node_id)
        if not info:
            return
        kind, payload = info
        if kind == "path":
            self._start_path_load(payload)
        elif kind == "md":          # 战役子图（已解析好），后台准备后切换
            self._campaign_path = next(
                (c["path"] for c in self._dir_campaigns
                 if c["views"] and any(m is payload for _, m in c["views"])), None)
            self._start_map_switch(payload, self._campaign_path)
        elif kind == "campaign":    # 点战役父节点 → 加载（若未加载）
            if not self._dir_campaigns[payload]["loaded"]:
                self._load_campaign_node(payload)

    def _on_map_pick(self, _evt):
        sel = self.map_list.selection()
        if not sel:
            return
        self._open_node(sel[0])

    # ---------- 打开/加载 ----------
    def on_open(self):
        path = filedialog.askopenfilename(
            title="选择魔兽地图或战役",
            filetypes=[("魔兽地图/战役", "*.w3x *.w3m *.w3n"), ("所有文件", "*.*")])
        if not path:
            return
        self._start_path_load(path)

    def _on_loaded(self, md: MapData, cmds, recipes=None, resolver=None,
                   views=None, campaign_path=None):
        if views:                       # 战役：进入战役图模式，左侧列表填子图
            self._set_campaign_views(views, campaign_path)
        else:                           # 对战图：退出战役上下文
            self.mode = "battle"
            self.mode_seg.set("对战图")
            self._campaign_views = None
            self._campaign_path = None
            self._populate_left()
        self._render_map(md, cmds, recipes, resolver)

    def _render_map(self, md, cmds, recipes, resolver):
        self.map_data = md
        old = self.icons                      # 释放上一张图的图标解析器(地图档/战役档句柄)
        if old is not None and old is not resolver and hasattr(old, "close"):
            try:
                old.close()
            except Exception:
                pass
        self.icons = resolver
        self._pil_icon_cache = {}
        self._photo_cache = {}
        self.map_label.configure(text=f"当前地图：{md.name}")
        self._reset_detail_panel()
        self._refresh_enabled_modules(cmds, recipes)

        counts = md.category_counts()
        total = sum(counts.values())
        self.status.configure(text=f"已加载 {md.name} · {total} 对象 · "
                              f"{len(cmds)} 指令 · "
                              f"{len(self.recipes)} 合成 · "
                              + "  ".join(f"{k}{v}" for k, v in counts.items()))

    # ---------- 战役视图 ----------
    def _set_campaign_views(self, views, path=None):
        """单独打开一个战役：并入战役树（已加载），进入战役图模式。"""
        self._campaign_views = views
        self._campaign_path = path
        if views:
            name = quick_map_name(path) if path else "战役"
            entry = next((c for c in self._dir_campaigns if c["path"] == path), None)
            if entry:
                entry["loaded"] = True
                entry["views"] = views
            else:
                self._dir_campaigns.insert(
                    0, {"path": path, "name": name, "loaded": True, "views": views})
            self.mode = "campaign"
            self.mode_seg.set("战役图")
        self._populate_left()

    def _on_object_category(self, cat):
        self.active_object_category = cat
        self._render_object_cards()

    def _render_object_cards(self):
        if not hasattr(self, "object_gallery"):
            return
        render_object_gallery(
            gallery=self.object_gallery,
            active_category=self.active_object_category,
            results_by_category=self.col_results,
            show_detail=self._show_detail,
            get_icon=self._get_tree_photo,
        )

    def _on_col_select(self, cat):
        tv = self.col_trees[cat]
        cur = tv.focus() or (tv.selection()[0] if tv.selection() else "")
        if not cur:
            return
        res = self.col_results.get(cat, [])
        idx = int(cur)
        if idx >= len(res):
            return
        self._show_detail(res[idx])

    def _show_detail(self, o):
        self.detail_icon_image = self._get_photo(getattr(o, "icon", "")) or self.detail_blank_icon
        self.detail_icon.configure(image=self.detail_icon_image, text="")
        self.detail_title.configure(text=o.name)
        self.detail_sub.configure(text=f"{o.category}  ·  ID {o.obj_id}  ·  基础 {o.base_id}"
                                  + ("  ·  自定义" if o.is_custom else "  ·  原始"))
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("end", f"ID：{o.obj_id}\n10进制：{o.decimal}\n名字：{o.name}\n\n")
        if not o.fields:
            self.detail.insert("end", "（无修改字段）")
        for lab, val in o.fields:
            self.detail.insert("end", f"{lab}: {val}\n")
        self._insert_references(o)
        self.detail.configure(state="disabled")

    def _insert_references(self, o):
        """详情区追加「引用 →」「被引用 ←」两节（只读引用分析）。"""
        md = self.map_data
        if md is None:
            return

        def fmt(code, name):
            return f"{name}({code})" if name else code

        refs = (md.references or {}).get(o.obj_id) or []
        if refs:
            self.detail.insert("end", "\n── 引用（→ 此对象用到的对象）──\n")
            for label, resolved in refs:
                items = "，".join(fmt(c, n) for c, n in resolved)
                self.detail.insert("end", f"{label}: {items}\n")

        back = (md.referenced_by or {}).get(o.obj_id) or []
        if back:
            self.detail.insert("end", "\n── 被引用（← 谁用到此对象）──\n")
            # 同一引用者可能多字段引用，去重展示
            seen = set()
            for rid, rname, label in back:
                key = (rid, label)
                if key in seen:
                    continue
                seen.add(key)
                self.detail.insert("end", f"{fmt(rid, rname)}  ·  {label}\n")

    # ---------- 指令 ----------
    def _refresh_cmds(self):
        q = self.cmd_search.get().strip()
        cq = compile_query(q)                 # 编译一次，下面每条指令复用
        self.cmd_tree.delete(*self.cmd_tree.get_children())
        n = 0
        for c in self.commands:
            blob = c.command + " " + c.hint
            if q and cq.score(blob) is None:
                continue
            self.cmd_tree.insert("", "end",
                                 values=(c.command or "(空)",
                                         "精确" if c.exact else "前缀", c.hint),
                                 tags=("odd" if n % 2 else "even",))
            n += 1
        self.cmd_tree.tag_configure("odd", background=ROW_ALT)
        self.cmd_tree.tag_configure("even", background=CARD)
        # 说明列按最长内容自适应宽度，配合横向滚动条看全长提示
        f = self._measure_font()
        widest = max((f.measure(c.hint) for c in self.commands), default=0)
        self.cmd_tree.column("hint", width=max(420, widest + 28))
        if self.commands:
            self.cmd_hint.configure(text=f"共 {len(self.commands)} 条聊天指令"
                                    f"（前缀=输入以该串开头即触发，常带参数；精确=完全匹配）")
        else:
            self.cmd_hint.configure(text="未发现聊天指令（此图可能无聊天触发，或用了非标准写法）")

    # ---------- 导出 ----------
    def _need_map(self):
        if not self.map_data:
            messagebox.showinfo("提示", "请先打开一张地图")
            return False
        return True

    def _open_dir(self, out, n, kind):
        self.status.configure(text=f"已导出 {n} 个{kind}到临时目录 {out}")
        try:
            os.startfile(out)        # 打开资源管理器到该临时目录
        except Exception:
            pass
        messagebox.showinfo("完成", f"已导出 {n} 个{kind}到临时目录：\n{out}\n（临时文件，可随时清理）")

    def on_export_all(self):
        if not self._need_map():
            return
        # 战役用 .w3n 顶层路径，可递归导出所有子图内部；普通图用自身
        path = self._campaign_path or self.map_data.path
        self.status.configure(text="正在解包全部文件到临时目录 …")
        self.update_idletasks()

        def work():
            try:
                out = export_all_files(path)        # 默认 TMP，战役自动递归
                n = sum(len(fs) for _, _, fs in os.walk(out))
                self.after(0, lambda: self._open_dir(out, n, "文件"))
            except Exception as exc:
                error_text = str(exc)
                self.after(0, lambda message=error_text: messagebox.showerror("导出失败", message))
        threading.Thread(target=work, daemon=True).start()

    def on_export_scripts(self):
        if not self._need_map():
            return
        out = tmp_extract_dir(self.map_data.name, "脚本", clean=True)   # 清空旧导出，避免同名图残留
        scripts = dict(self.map_data.scripts)          # 快照后到后台线程写盘，避免卡 UI
        self.status.configure(text="正在导出脚本 …")

        def work():
            try:
                n = 0
                for fn, text in scripts.items():
                    with open(os.path.join(out, os.path.basename(fn)), "w", encoding="utf-8") as f:
                        f.write(text)
                    n += 1
                self.after(0, lambda: self._open_dir(out, n, "脚本"))
            except Exception as exc:
                error_text = str(exc)
                self.after(0, lambda message=error_text: messagebox.showerror("导出失败", message))
        threading.Thread(target=work, daemon=True).start()

    def on_export_ids(self):
        if not self._need_map():
            return
        out = tmp_extract_dir(self.map_data.name, "ID列表", clean=True)   # 清空旧导出，避免同名图残留
        objects = {c: list(v) for c, v in self.map_data.objects.items()}
        self.status.configure(text="正在导出ID列表 …")

        def work():
            try:
                n = 0
                for cat, objs in objects.items():
                    blocks = []
                    for o in objs:
                        desc = next(
                            (value for label, value in o.fields
                             if label in ("说明", "描述", "Ubertip", "提示")),
                            "",
                        )
                        blocks.append(f"10进制：{o.decimal}\nID：{o.obj_id}\n名字：{o.name}\n{desc}\n")
                    with open(os.path.join(out, f"{cat}ID.txt"), "w", encoding="utf-8") as f:
                        f.write("\n".join(blocks))
                    n += 1
                self.after(0, lambda: self._open_dir(out, n, "分类的ID列表"))
            except Exception as exc:
                error_text = str(exc)
                self.after(0, lambda message=error_text: messagebox.showerror("导出失败", message))
        threading.Thread(target=work, daemon=True).start()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
