"""魔兽地图提取器 GUI（CustomTkinter，深色卡片风）。

三个标签页：
- 对象浏览：模糊搜索 单位/物品/技能/科技 等，看详情、导出
- 隐藏指令：扫描脚本里的聊天指令
- 合成配方：识别物品合成配方
"""
from __future__ import annotations

import os
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

import customtkinter as ctk

from collections import Counter

from .api import (load_map, commands_from_map, recipes_from_map,
                  export_all_files, tmp_extract_dir, quick_map_name, MapData)
from .search import fuzzy_score
from .icons import IconResolver
from PIL import Image, ImageTk
try:
    from .base_names import BASE_NAMES
except Exception:
    BASE_NAMES = {}

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

FONT = "JetBrains Mono"
# Darcula 风（JetBrains 深色）
_LAYOUT_VERSION = 2        # 布局结构版本（变更后忽略旧的分隔条配置）
ACCENT = "#3592c4"         # Darcula 蓝
ACCENT_HOVER = "#4aa3d5"
CARD = "#3c3f41"           # 面板
BG = "#2b2b2b"             # 编辑器底
TEXT = "#a9b7c6"
SUBTLE = "#808080"
BORDER = "#323232"
ROW_ALT = "#323436"
SEL_BG = "#2d5177"         # Darcula 选中蓝
SECONDARY = "#4c5052"
SECONDARY_HOVER = "#5c6164"
PANEL = "#2b2b2b"          # 文本框/画布底
PARALLEL_CATS = ["物品", "单位", "技能", "科技"]


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("魔兽地图提取器")
        self.geometry("1380x800")
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
        self._photo_cache = {}     # icon path -> PhotoImage
        self._row_imgs = []        # 保持引用防止被回收
        self._blank = None

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
        self.after(500, self._restore_sashes)      # 恢复上次拖拽的分隔位置

    # ---------- 顶栏 ----------
    def _build_topbar(self):
        bar = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0, height=64)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)
        ctk.CTkLabel(bar, text="  ⚔  魔兽地图提取器", font=(FONT, 16, "bold")).pack(side="left", padx=10)
        ctk.CTkButton(bar, text="打开地图 / 战役", font=(FONT, 14, "bold"),
                      width=140, height=38, command=self.on_open).pack(side="left", padx=8)
        self.map_label = ctk.CTkLabel(bar, text="未打开", font=(FONT, 13), text_color=SUBTLE)
        self.map_label.pack(side="left", padx=12)
        ctk.CTkButton(bar, text="导出全部文件", font=(FONT, 13), width=110, height=34,
                      fg_color=SECONDARY, hover_color=SECONDARY_HOVER, text_color=TEXT,
                      command=self.on_export_all).pack(side="right", padx=6)
        ctk.CTkButton(bar, text="导出脚本", font=(FONT, 13), width=90, height=34,
                      fg_color=SECONDARY, hover_color=SECONDARY_HOVER, text_color=TEXT,
                      command=self.on_export_scripts).pack(side="right", padx=6)
        ctk.CTkButton(bar, text="导出ID列表", font=(FONT, 12), width=92, height=30,
                      fg_color=SECONDARY, hover_color=SECONDARY_HOVER, text_color=TEXT,
                      command=self.on_export_ids).pack(side="right", padx=5)

    # ---------- 标签页 ----------
    def _build_tabs(self):
        # 一级：对战图 | 战役图（左右切换）
        self.mode_seg = ctk.CTkSegmentedButton(
            self, values=["对战图", "战役图"], command=self._on_mode_change,
            font=(FONT, 14, "bold"), height=34,
            selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
            unselected_color=CARD, fg_color=BG)
        self.mode_seg.set("对战图")
        self.mode_seg.pack(pady=(8, 2))

        self.tabs = ctk.CTkTabview(self, fg_color=BG, segmented_button_selected_color=ACCENT)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(2, 6))
        self.tab_obj = self.tabs.add("对象浏览")
        self.tab_cmd = self.tabs.add("隐藏指令")
        self.tab_rec = self.tabs.add("合成配方")
        self._build_obj_tab(self.tab_obj)
        self._build_cmd_tab(self.tab_cmd)
        self._build_rec_tab(self.tab_rec)

    def _build_obj_tab(self, parent):
        # 顶部搜索（过滤所有列）
        ctrl = ctk.CTkFrame(parent, fg_color=BG)
        ctrl.pack(fill="x", padx=4, pady=(6, 6))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refresh_list())
        se = ctk.CTkEntry(ctrl, textvariable=self.search_var, height=32, font=(FONT, 12),
                          justify="center",
                          placeholder_text="🔍  搜索名称/ID/描述　空格=且　竖线|=或　例：智力 剑|法杖")
        se.pack(fill="x")
        self._attach_ctx_menu(se, paste=True)

        body = ctk.CTkFrame(parent, fg_color=BG)
        body.pack(fill="both", expand=True)
        # 可拖拽分隔：地图列表 | 物品 | 单位 | 技能 | 科技 | 描述，拖动中间分隔条调宽
        paned = ttk.PanedWindow(body, orient="horizontal")
        paned.pack(fill="both", expand=True)
        self.paned = paned

        # 左：地图列表（对战图=文件夹地图；战役图=战役共享+各子图）
        leftp = ctk.CTkFrame(paned, fg_color=CARD, corner_radius=8, width=130)
        self.left_brow = ctk.CTkFrame(leftp, fg_color=CARD)
        self.left_brow.pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkButton(self.left_brow, text="选择地图目录", height=30, font=(FONT, 12),
                      command=self.on_pick_dir).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(self.left_brow, text="⟳", width=30, height=30, font=(FONT, 14),
                      fg_color=SECONDARY, hover_color=SECONDARY_HOVER, text_color=TEXT,
                      command=self.on_refresh_dir).pack(side="right", padx=(4, 0))
        self.left_title = ctk.CTkLabel(leftp, text="地图列表", font=(FONT, 12, "bold"),
                                       anchor="w")
        self.left_title.pack(fill="x", padx=10)
        self.map_search = tk.StringVar()
        self.map_search.trace_add("write", lambda *_: self._populate_left())
        mse = ctk.CTkEntry(leftp, textvariable=self.map_search, height=28, font=(FONT, 11),
                           justify="center", placeholder_text="🔍 搜索…")
        mse.pack(fill="x", padx=8, pady=(0, 4))
        self._attach_ctx_menu(mse, paste=True)
        mlw = tk.Frame(leftp, bg=CARD)
        mlw.pack(fill="both", expand=True, padx=6, pady=6)
        self.map_list = ttk.Treeview(mlw, show="tree", selectmode="browse")
        mvsb = ttk.Scrollbar(mlw, orient="vertical", command=self.map_list.yview)
        self.map_list.configure(yscrollcommand=mvsb.set)
        mvsb.pack(side="right", fill="y")
        self.map_list.pack(side="left", fill="both", expand=True)
        self.map_list.bind("<Double-1>", self._on_map_pick)   # 双击才加载/切换
        self.map_list.bind("<<TreeviewOpen>>", self._on_tree_open)
        self._dir_maps = []
        paned.add(leftp, weight=2)

        # 中：物品/单位/技能/科技 四列（各为可拖拽面板）
        self.col_trees = {}
        self.col_results = {}
        self.col_headers = {}
        for i, cat in enumerate(PARALLEL_CATS):
            col = ctk.CTkFrame(paned, fg_color=CARD, corner_radius=8, width=200)
            hdr = ctk.CTkLabel(col, text=cat, font=(FONT, 12, "bold"))
            hdr.pack(fill="x", pady=(5, 2))
            self.col_headers[cat] = hdr
            w = tk.Frame(col, bg=CARD)
            w.pack(fill="both", expand=True, padx=5, pady=(0, 6))
            tv = ttk.Treeview(w, show="tree", selectmode="browse")
            tv.column("#0", width=80, minwidth=50, stretch=True, anchor="w")
            vsb = ttk.Scrollbar(w, orient="vertical", command=tv.yview)
            tv.configure(yscrollcommand=vsb.set)
            vsb.pack(side="right", fill="y")
            tv.pack(side="left", fill="both", expand=True)
            tv.bind("<<TreeviewSelect>>", lambda e, c=cat: self._on_col_select(c))  # 单击看详情
            self._attach_tree_copy(tv)                                            # 右键复制名字
            self.col_trees[cat] = tv
            self.col_results[cat] = []
            paned.add(col, weight=3)

        # 右：描述
        rightp = ctk.CTkFrame(paned, fg_color=CARD, corner_radius=8, width=300)
        self.detail_title = ctk.CTkLabel(rightp, text="选择条目查看详情", font=(FONT, 15, "bold"),
                                         anchor="w", justify="left", wraplength=420)
        self.detail_title.pack(fill="x", padx=14, pady=(12, 2))
        self.detail_sub = ctk.CTkLabel(rightp, text="", font=(FONT, 11),
                                       text_color=SUBTLE, anchor="w", wraplength=420, justify="left")
        self.detail_sub.pack(fill="x", padx=12)
        self.detail = ctk.CTkTextbox(rightp, font=(FONT, 12),
                                     fg_color=PANEL, wrap="word")
        self.detail.pack(fill="both", expand=True, padx=10, pady=10)
        self.detail.configure(state="disabled")
        self._attach_ctx_menu(self.detail, copy_all=True)
        paned.add(rightp, weight=4)

    def _build_cmd_tab(self, parent):
        top = ctk.CTkFrame(parent, fg_color=BG)
        top.pack(fill="x", padx=4, pady=(8, 6))
        self.cmd_search = tk.StringVar()
        self.cmd_search.trace_add("write", lambda *_: self._refresh_cmds())
        cse = ctk.CTkEntry(top, textvariable=self.cmd_search, height=38, font=(FONT, 14),
                           justify="center",
                           placeholder_text="🔍  搜索指令/说明　空格=且　竖线|=或")
        cse.pack(fill="x")
        self._attach_ctx_menu(cse, paste=True)
        self.cmd_hint = ctk.CTkLabel(parent, text="打开地图后这里列出脚本里的全部聊天指令（含隐藏指令）",
                                     font=(FONT, 12), text_color=SUBTLE, anchor="w")
        self.cmd_hint.pack(fill="x", padx=6, pady=(0, 6))
        wrap = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12)
        wrap.pack(fill="both", expand=True)
        inner = tk.Frame(wrap, bg=CARD)
        inner.pack(fill="both", expand=True, padx=8, pady=8)
        self.cmd_tree = ttk.Treeview(inner, columns=("cmd", "match", "hint"),
                                     show="headings", selectmode="browse")
        for c, t, w, a in (("cmd", "指令", 180, "w"), ("match", "匹配", 70, "center"),
                           ("hint", "说明(脚本提示)", 420, "w")):
            self.cmd_tree.heading(c, text=t)
            self.cmd_tree.column(c, width=w, anchor=a)
        vsb = ttk.Scrollbar(inner, orient="vertical", command=self.cmd_tree.yview)
        self.cmd_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.cmd_tree.pack(side="left", fill="both", expand=True)
        self._attach_tree_copy(self.cmd_tree)

    def _build_rec_tab(self, parent):
        top = ctk.CTkFrame(parent, fg_color=BG)
        top.pack(fill="x", padx=4, pady=(8, 6))
        self.rec_search = tk.StringVar()
        self.rec_search.trace_add("write", lambda *_: self._refresh_recipes())
        rse = ctk.CTkEntry(top, textvariable=self.rec_search, height=38, font=(FONT, 14),
                           justify="center",
                           placeholder_text="🔍  搜索材料/成品名称　空格=且　竖线|=或")
        rse.pack(fill="x")
        self._attach_ctx_menu(rse, paste=True)
        self.rec_hint = ctk.CTkLabel(parent, text="打开地图后这里列出脚本里识别到的物品合成配方",
                                     font=(FONT, 12), text_color=SUBTLE, anchor="w")
        self.rec_hint.pack(fill="x", padx=6, pady=(0, 6))
        wrap = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12)
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

    def _item_name(self, code):
        if self.map_data:
            o = self.map_data.obj_index.get(code)
            if o and o.name and o.name != code:
                return f"{o.name}({code})"
        bn = BASE_NAMES.get(code)
        return f"{bn}({code})" if bn else code

    def _measure_font(self):
        """缓存一个与表格行同字体的测量用 Font，用来算材料列该多宽。"""
        if not hasattr(self, "_rec_font"):
            self._rec_font = tkfont.Font(family=FONT, size=11)
        return self._rec_font

    def _refresh_recipes(self):
        q = self.rec_search.get().strip().lower()
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
            if q and fuzzy_score(q, (res_name + " " + ing_str).lower()) is None:
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
        self.status = ctk.CTkLabel(self, text="就绪 · 点击「打开地图」开始", anchor="w",
                                   font=(FONT, 12), text_color=SUBTLE)
        self.status.pack(fill="x", side="bottom", padx=16, pady=4)

    def _setup_tree_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", background=CARD, fieldbackground=CARD,
                        foreground=TEXT, rowheight=32, borderwidth=0, font=(FONT, 11))
        style.configure("Treeview.Heading", background="#313335", foreground=TEXT,
                        font=(FONT, 12, "bold"), borderwidth=0, relief="flat")
        style.map("Treeview", background=[("selected", SEL_BG)],
                  foreground=[("selected", "#ffffff")])
        style.map("Treeview.Heading", background=[("active", "#3a3d3f")])
        # 细化滚动条，融入深色
        style.configure("Vertical.TScrollbar", background=CARD, troughcolor=BG,
                        borderwidth=0, arrowsize=12)
        style.configure("Horizontal.TScrollbar", background=CARD, troughcolor=BG,
                        borderwidth=0, arrowsize=12)

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

    def _restore_sashes(self):
        cfg = self._load_config()
        # 布局变更后旧的分隔条位置会错位，版本不符则忽略，用默认布局
        if cfg.get("layout") != _LAYOUT_VERSION:
            return
        sashes = cfg.get("sashes")
        if not sashes:
            return
        try:
            self.update_idletasks()
            for i, pos in enumerate(sashes):
                try:
                    self.paned.sashpos(i, int(pos))
                except Exception:
                    pass
        except Exception:
            pass

    def _on_close(self):
        # 保存窗口几何 + 分隔条位置，供下次启动恢复
        try:
            sashes = []
            n = len(self.paned.panes())
            for i in range(n - 1):
                try:
                    sashes.append(self.paned.sashpos(i))
                except Exception:
                    break
            self._save_config(geometry=self.geometry(), sashes=sashes,
                              layout=_LAYOUT_VERSION)
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
                files = []
                for pat in ("*.w3x", "*.w3m", "*.W3X"):
                    files.extend(glob.glob(os.path.join(d, "**", pat), recursive=True))
                files = sorted(set(files), key=lambda p: os.path.getmtime(p), reverse=True)
                items = [(p, quick_map_name(p)) for p in files]
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
        self.map_list.delete(*self.map_list.get_children())
        for i, (p, name) in enumerate(self._dir_maps):
            if q and q not in name.lower():
                continue
            iid = f"m{i}"
            self.map_list.insert("", "end", iid=iid, text=f" {name}")
            self._node_map[iid] = ("path", p)

    def _refresh_campaign_tree(self):
        """战役图：树形——战役为父节点，展开显示子地图(★共享+各关卡)。"""
        q = self.map_search.get().strip().lower() if hasattr(self, "map_search") else ""
        self._node_map = {}
        self.map_list.delete(*self.map_list.get_children())
        for i, camp in enumerate(self._dir_campaigns):
            if q and q not in camp["name"].lower():
                continue
            pid = f"c{i}"
            self.map_list.insert("", "end", iid=pid, text=f" {camp['name']}",
                                 open=bool(camp["loaded"]))
            self._node_map[pid] = ("campaign", i)
            if camp["loaded"] and camp["views"]:
                for j, (label, md) in enumerate(camp["views"]):
                    cid = f"{pid}_s{j}"
                    self.map_list.insert(pid, "end", iid=cid, text=f" {label}")
                    self._node_map[cid] = ("md", md)
            else:
                self.map_list.insert(pid, "end", iid=f"{pid}_load", text="  （展开加载…）")

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
        camp = self._dir_campaigns[idx]
        self.status.configure(text=f"正在解析战役 {camp['name']} …")

        def work():
            try:
                md = load_map(camp["path"])
            except Exception:
                traceback.print_exc()
                return
            views = [("★ 战役共享对象", md)] + [(s.name, s) for s in md.sub_maps]
            camp["loaded"] = True
            camp["views"] = views
            self.after(0, lambda: (self._refresh_campaign_tree(),
                                   self.status.configure(
                                       text=f"战役 {camp['name']}：{len(md.sub_maps)} 张子图")))
        threading.Thread(target=work, daemon=True).start()

    def _on_map_pick(self, _evt):
        sel = self.map_list.selection()
        if not sel:
            return
        info = self._node_map.get(sel[0])
        if not info:
            return
        kind, payload = info
        if kind == "path":
            self.status.configure(text=f"正在解析 {os.path.basename(payload)} …")
            self.update_idletasks()
            threading.Thread(target=self._load_worker, args=(payload,), daemon=True).start()
        elif kind == "md":          # 战役子图（已解析好），后台准备后切换
            self._campaign_path = next(
                (c["path"] for c in self._dir_campaigns
                 if c["views"] and any(m is payload for _, m in c["views"])), None)
            self.status.configure(text=f"正在切换 …")
            threading.Thread(target=self._switch_worker, args=(payload,), daemon=True).start()
        elif kind == "campaign":    # 点战役父节点 → 加载（若未加载）
            if not self._dir_campaigns[payload]["loaded"]:
                self._load_campaign_node(payload)

    # ---------- 打开/加载 ----------
    def on_open(self):
        path = filedialog.askopenfilename(
            title="选择魔兽地图或战役",
            filetypes=[("魔兽地图/战役", "*.w3x *.w3m *.w3n"), ("所有文件", "*.*")])
        if not path:
            return
        self.status.configure(text=f"正在解析 {os.path.basename(path)} …")
        self.update_idletasks()
        threading.Thread(target=self._load_worker, args=(path,), daemon=True).start()

    def _load_worker(self, path):
        try:
            md = load_map(path)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("解析失败", str(e)))
            self.after(0, lambda: self.status.configure(text="解析失败"))
            return
        # 战役：顶层共享对象 + 各子图，做成下拉条目；普通图无下拉
        if md.sub_maps:
            views = [("★ 战役共享对象", md)] + [(s.name, s) for s in md.sub_maps]
            campaign_path = path
        else:
            views = None
            campaign_path = None
        active = views[0][1] if views else md
        cmds, recipes, resolver = self._prepare(active, campaign_path)
        self.after(0, lambda: self._on_loaded(active, cmds, recipes, resolver,
                                              views, campaign_path))

    def _prepare(self, md, campaign_path=None):
        """worker 线程：为一张 md 算指令/配方 + 预解码图标（含战役顶层档兜底）。"""
        try:
            cmds = commands_from_map(md)
        except Exception:
            traceback.print_exc()        # 扫描出错时打日志，不静默伪装成"无指令"
            cmds = []
        try:
            recipes = recipes_from_map(md)
        except Exception:
            traceback.print_exc()
            recipes = []
        resolver = None
        try:
            extra = [campaign_path] if (campaign_path and campaign_path != md.path) else None
            resolver = IconResolver(md.path, extra_paths=extra)
            seen = set()
            for objs in md.objects.values():
                for o in objs:
                    if o.icon and o.icon not in seen:
                        seen.add(o.icon)
                        resolver.get_image(o.icon)
        except Exception:
            resolver = None
        return cmds, recipes, resolver

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
        self.icons = resolver
        self._photo_cache = {}
        self.map_label.configure(text=f"📦 {md.name}")
        # 清空上一张图残留的详情，避免误以为是当前图的数据
        self.detail_title.configure(text="选择左侧条目查看详情")
        self.detail_sub.configure(text="")
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.configure(state="disabled")
        self._refresh_list()

        # 指令
        self.commands = cmds
        self._refresh_cmds()
        # 合成配方
        self.recipes = recipes or []
        self._refresh_recipes()

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

    def _view_md(self, label):
        for lbl, m in (self._campaign_views or []):
            if lbl == label:
                return m
        return None

    def _switch_worker(self, md):
        cmds, recipes, resolver = self._prepare(md, self._campaign_path)
        self.after(0, lambda: self._render_map(md, cmds, recipes, resolver))

    # ---------- 对象浏览（多列）----------
    def _refresh_list(self):
        if not self.map_data:
            return
        query = self.search_var.get().strip().lower()
        self._row_imgs = []
        summary = []
        for cat in PARALLEL_CATS:
            objs = self.map_data.objects.get(cat, [])
            scored = []
            for o in objs:
                sc = fuzzy_score(query, o.search_text) if query else 0
                if sc is not None:
                    scored.append((sc, o))
            if query:
                scored.sort(key=lambda t: -t[0])
            res = [o for _, o in scored]      # 全部展示，不限数量
            self.col_results[cat] = res
            tv = self.col_trees[cat]
            tv.delete(*tv.get_children())
            for i, o in enumerate(res):
                photo = self._get_photo(getattr(o, "icon", ""))
                self._row_imgs.append(photo)
                ext = getattr(o, "ext", "")
                mark = " 〔脚本〕" if ext == "script" else (" 〔原版〕" if ext == "base" else "")
                tv.insert("", "end", iid=str(i), image=photo or "",
                          text=f" {o.name}{mark}",
                          tags=("odd" if i % 2 else "even",))
            tv.tag_configure("odd", background=ROW_ALT)
            tv.tag_configure("even", background=CARD)
            self.col_headers[cat].configure(text=f"{cat}  ({len(res)})")
            summary.append(f"{cat}{len(res)}")
        self.status.configure(text="  ".join(summary))

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

    def _col_select_all(self, cat):
        tv = self.col_trees[cat]
        items = tv.get_children()
        tv.selection_set(items)

    def on_export_selected(self):
        if not self._need_map():
            return
        picked = []
        for cat in PARALLEL_CATS:
            tv = self.col_trees[cat]
            res = self.col_results.get(cat, [])
            for iid in tv.selection():
                i = int(iid)
                if i < len(res):
                    picked.append((cat, res[i]))
        if not picked:
            messagebox.showinfo("提示", "请先在列表里选中条目（Ctrl/Shift 多选，或点列头「全选」）")
            return
        out = filedialog.asksaveasfilename(title="导出选中的对象", defaultextension=".txt",
                                           initialfile="选中对象.txt",
                                           filetypes=[("文本", "*.txt")])
        if not out:
            return
        with open(out, "w", encoding="utf-8") as f:
            for cat, o in picked:
                desc = next((v for l, v in o.fields if l in ("说明", "描述", "Ubertip", "提示")), "")
                f.write(f"[{cat}] 10进制：{o.decimal}\nID：{o.obj_id}\n名字：{o.name}\n{desc}\n\n")
        self.status.configure(text=f"已导出选中的 {len(picked)} 个对象到 {out}")
        messagebox.showinfo("完成", f"已导出选中的 {len(picked)} 个对象到\n{out}")

    def _get_photo(self, icon_path):
        if not icon_path or self.icons is None:
            return None
        key = icon_path.lower()
        if key in self._photo_cache:
            return self._photo_cache[key]
        photo = None
        try:
            pil = self.icons.get_image(icon_path)
            if pil is not None:
                photo = ImageTk.PhotoImage(pil.resize((20, 20), Image.LANCZOS))
        except Exception:
            photo = None
        self._photo_cache[key] = photo
        return photo

    def _show_detail(self, o):
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
        self.detail.configure(state="disabled")

    # ---------- 指令 ----------
    def _refresh_cmds(self):
        q = self.cmd_search.get().strip().lower()
        self.cmd_tree.delete(*self.cmd_tree.get_children())
        n = 0
        for c in self.commands:
            blob = (c.command + " " + c.hint).lower()
            if q and fuzzy_score(q, blob) is None:
                continue
            self.cmd_tree.insert("", "end",
                                 values=(c.command or "(空)",
                                         "精确" if c.exact else "前缀", c.hint),
                                 tags=("odd" if n % 2 else "even",))
            n += 1
        self.cmd_tree.tag_configure("odd", background=ROW_ALT)
        self.cmd_tree.tag_configure("even", background=CARD)
        if self.commands:
            self.cmd_hint.configure(text=f"共 {len(self.commands)} 条聊天指令"
                                    f"（前缀=输入以该串开头即触发，常带参数；精确=完全匹配）")

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
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("导出失败", str(e)))
        threading.Thread(target=work, daemon=True).start()

    def on_export_scripts(self):
        if not self._need_map():
            return
        out = tmp_extract_dir(self.map_data.name, "脚本")
        n = 0
        for fn, text in self.map_data.scripts.items():
            with open(os.path.join(out, os.path.basename(fn)), "w", encoding="utf-8") as f:
                f.write(text)
            n += 1
        self._open_dir(out, n, "脚本")

    def on_export_ids(self):
        if not self._need_map():
            return
        out = tmp_extract_dir(self.map_data.name, "ID列表")
        n = 0
        for cat, objs in self.map_data.objects.items():
            blocks = []
            for o in objs:
                desc = next((v for l, v in o.fields if l in ("说明", "描述", "Ubertip", "提示")), "")
                blocks.append(f"10进制：{o.decimal}\nID：{o.obj_id}\n名字：{o.name}\n{desc}\n")
            with open(os.path.join(out, f"{cat}ID.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(blocks))
            n += 1
        self._open_dir(out, n, "分类的ID列表")


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
