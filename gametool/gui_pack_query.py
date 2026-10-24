"""GUI 内直查当前资料包 — search/doc 子命令的图形入口 (后台线程, 结果弹窗)。"""

from __future__ import annotations

import os
import pathlib
import re
import tkinter as tk
from typing import TYPE_CHECKING

import customtkinter as ctk

from .theme import BG, CARD, FONT, SUBTLE, TEXT, TITLE_FONT

if TYPE_CHECKING:
    from collections.abc import Callable


_LAST_KEYWORD = ""
_LAST_MODE = "doc"
_LAST_RESULT = ""
_HISTORY: list[tuple[str, str]] = []  # (模式, 关键词) 最近 10 条
_WINDOW_GEOMETRY: dict[str, str] = {}  # 窗口名 -> "WxH" (进程级)


def _memo_dir() -> str:
    try:
        from .cache_root import gamexray_cache_root

        return str(gamexray_cache_root() / "gui-query-memo")
    except OSError:
        return ""


def _save_memo() -> None:
    """收藏+历史落盘 (fail-open): 重启程序不丢。"""
    import json

    from pathlib import Path

    base = _memo_dir()
    if not base:
        return
    try:
        base_path = Path(base)
        base_path.mkdir(parents=True, exist_ok=True)
        (base_path / "history.json").write_text(
            json.dumps(_HISTORY, ensure_ascii=False), encoding="utf-8"
        )
        (base_path / "pinned.json").write_text(
            json.dumps(_PINNED, ensure_ascii=False), encoding="utf-8"
        )
        (base_path / "geometry.json").write_text(
            json.dumps(_WINDOW_GEOMETRY, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass  # fail-open: 记忆失败不影响查询


def _load_memo() -> None:
    import json

    from pathlib import Path

    base = _memo_dir()
    if not base:
        return
    try:
        base_path = Path(base)
        history = json.loads((base_path / "history.json").read_text(encoding="utf-8"))
        _HISTORY[:] = [tuple(x) for x in history]
        pinned = json.loads((base_path / "pinned.json").read_text(encoding="utf-8"))
        _PINNED[:] = [tuple(x) for x in pinned]
        geo = json.loads((base_path / "geometry.json").read_text(encoding="utf-8"))
        _WINDOW_GEOMETRY.update(geo)
    except OSError, ValueError:
        pass  # fail-open: 缺文件/坏格式当空白


def _remember_geometry(win, name: str) -> None:
    """窗口关闭时把尺寸写进进程级记忆 (未渲染的 200x200 默认不覆盖好记忆)。"""
    try:
        if int(win.winfo_width()) <= 1:
            return  # 从未渲染: 别用默认尺寸污染已保存的记忆
    except Exception:
        pass
    _WINDOW_GEOMETRY[name] = win.geometry()


def apply_saved_geometry(win, name: str, fallback: str) -> None:
    """按记忆尺寸/位置还原窗口, 无记忆用 fallback (跨弹窗复用)。"""
    win.geometry(_WINDOW_GEOMETRY.get(name, fallback))


def bind_geometry_memory(win, name: str, fallback: str) -> None:
    """还原 + 关闭落盘一体化: 弹窗记忆惯例的最小接入点。"""
    _load_memo()  # 跨弹窗接入时 dict 可能未填充 (探针等独立弹窗)

    def _on_destroy(event) -> None:
        # <Destroy> 会因子控件销毁冒泡触发, 只有顶层自身销毁才记 geometry
        if event.widget is not win:
            return
        _remember_geometry(win, name)
        _save_memo()

    apply_saved_geometry(win, name, fallback)
    win.bind("<Destroy>", _on_destroy)


_PINNED: list[tuple[str, str]] = []  # (标题, 内容)


def open_pack_query_dialog(
    master,
    pack_dir_provider: Callable[[], str | None],
    ensure_pack: Callable[[], str | None],
    prefill: str = "",
    prefill_command: str = "",
) -> None:
    """打开包查询窗口。

    pack_dir_provider 返回最近一次导出的资料包目录 (无则 None);
    ensure_pack 在无包时回调 GUI 的导出动作 (先导出再查)。
    """
    pack_dir = pack_dir_provider()
    if not pack_dir or not os.path.isdir(pack_dir):
        ensure_pack()
        return
    _PackQueryWindow(master, pack_dir, prefill, prefill_command)


class _PackQueryWindow(ctk.CTkToplevel):
    def __init__(
        self, master, pack_dir: str, prefill: str = "", prefill_command: str = ""
    ) -> None:
        super().__init__(master)
        self._pack_dir = pack_dir
        _load_memo()
        pack_label = os.path.basename(pack_dir.rstrip("/")) or "资料包查询"
        self.title(f"资料包查询 — {pack_label}")
        remembered = _WINDOW_GEOMETRY.get("pack-query")
        self.geometry(remembered or "760x560")
        self.bind("<Destroy>", lambda _e: _remember_geometry(self, "pack-query"))
        self.configure(fg_color=BG)
        self.transient(master)
        self.grab_set()
        self.bind("<Escape>", lambda _e: self.destroy())

        header = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        header.pack(fill="x", padx=14, pady=(14, 8))
        ctk.CTkLabel(
            header,
            text="资料包查询",
            font=(TITLE_FONT, 17, "bold"),
            text_color=TEXT,
        ).pack(anchor="w", padx=12, pady=(8, 0))
        ctk.CTkLabel(
            header,
            text=f"包: {pack_dir}",
            font=(FONT, 11),
            text_color=SUBTLE,
            anchor="w",
            justify="left",
        ).pack(fill="x", padx=12, pady=(0, 8))

        row = ctk.CTkFrame(self, fg_color="transparent")
        _HISTORY_VALUES = [f"{c} {k}".strip() for c, k in _HISTORY] or ["(无历史)"]
        self._history = ctk.CTkOptionMenu(
            row,
            values=_HISTORY_VALUES,
            width=120,
            command=self._on_history_pick,
        )
        self._history.set(_HISTORY_VALUES[0] if _HISTORY else "(历史)")
        self._history.pack(side="right")
        self._history_clear = ctk.CTkButton(
            row,
            text="清历史",
            width=60,
            height=26,
            font=(FONT, 11),
            fg_color="transparent",
            border_width=1,
            command=self._clear_history,
        )
        self._history_clear.pack(side="right", padx=(0, 4))
        row.pack(fill="x", padx=14)
        self._keyword = ctk.CTkEntry(
            row, placeholder_text="四码或名称…  Ctrl+1..8 切模式  回车查", width=340
        )
        self._keyword.insert(0, prefill or _LAST_KEYWORD)
        self._keyword.pack(side="left", padx=(0, 8))
        self._keyword.bind("<Return>", lambda _e: self._run(self._mode.get()))
        self._paste_coords = ctk.CTkButton(
            row,
            text="从剪贴板提取坐标",
            width=140,
            command=self._coords_from_clipboard,
        )
        self._paste_coords.pack(side="left", padx=(0, 8))
        self._mode_commands = [
            "doc",
            "search",
            "list",
            "buffs",
            "export",
            "synth",
            "skills",
            "units",
            "locate",
            "near",
            "where",
            "drop",
            "again",
            "stats",
            "shop",
            "tech",
            "item",
            "heroes",
            "price",
        ]
        for _i, _cmd in enumerate(self._mode_commands, start=1):
            keynum = _i if _i < 10 else 0  # near 排第 10 = Ctrl+0; again 第 11 位走不到
            if _i > 10:
                break  # again 仅面板点击切换 (Ctrl+0 已归 near)
            self.bind_all(
                f"<Control-Key-{keynum}>",
                lambda _e, c=_cmd: self._switch_mode(c),
            )
        self._mode = ctk.CTkSegmentedButton(
            row,
            values=[
                "doc",
                "search",
                "list",
                "buffs",
                "export",
                "synth",
                "skills",
                "units",
                "locate",
                "near",
                "where",
                "drop",
            ],
            width=280,
        )
        self._mode.set(prefill_command or _LAST_MODE)
        self._mode.pack(side="left", padx=(0, 8))
        # 扩展模式第二行 (低频查点选; 切换时与主面板联动 set)
        self._mode_extra = ctk.CTkSegmentedButton(
            row,
            values=[
                "again",
                "stats",
                "shop",
                "tech",
                "item",
                "heroes",
                "price",
            ],
            width=280,
        )
        self._mode_extra.set("again")  # 占位显示 (真实模式以 self._mode 为准)
        self._mode_extra.configure(command=self._extra_mode_clicked)
        self._mode_extra.pack(side="left", padx=(0, 8))
        # 初开时扩展排高亮同步 (记忆恢复的模式可能属扩展组)
        _initial = self._mode.get()
        if _initial in ("again", "stats", "shop", "tech", "item", "heroes", "price"):
            self._mode_extra.set(_initial)
        else:
            self._mode_extra.set("<<none>>")
        ctk.CTkButton(row, text="查询", width=84, command=self._run_clicked).pack(
            side="left"
        )
        self._near_kind = ctk.CTkOptionMenu(
            row,
            values=["全部", "单位", "装饰", "物品", "脚本"],
            width=76,
        )
        self._near_kind.set(self._load_near_kind())
        # near 模式才显示 (switch 时切换)

        pin_row = ctk.CTkFrame(self, fg_color="transparent")
        pin_row.pack(fill="x", padx=14, pady=(10, 0))
        self._pin_button = ctk.CTkButton(
            pin_row,
            text=self._pin_button_text(),
            width=150,
            height=24,
            font=(FONT, 11),
            command=self._pin_current,
        ).pack(side="left")
        ctk.CTkButton(
            pin_row,
            text="清空收藏",
            width=90,
            height=24,
            font=(FONT, 11),
            fg_color="transparent",
            border_width=1,
            command=self._clear_pinned,
        ).pack(side="left", padx=(6, 0))
        self._pinned_box = ctk.CTkTextbox(
            self, font=("Consolas", 11), wrap="none", height=120
        )
        if _PINNED:
            self._render_pinned()

        find_row = ctk.CTkFrame(self, fg_color="transparent")
        find_row.pack(fill="x", padx=14)
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
        self._var_json = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            find_row,
            text="JSON 输出",
            variable=self._var_json,
            font=("Microsoft YaHei UI", 10),
        ).pack(side="right", padx=(8, 0))

        def _find_next():
            needle = self._find_var.get().strip()
            if not needle:
                return
            start = self._find_state["start"]
            pos = self._output.search(needle, start, stopindex="end", nocase=True)
            if not pos:
                self._find_state["start"] = "1.0"
                pos = self._output.search(needle, "1.0", stopindex="end", nocase=True)
            if pos:
                self._output.see(pos)
                self._output.mark_set("insert", pos)
                end = f"{pos}+{len(needle)}c"
                self._output.tag_add("sel", pos, end)
                self._find_state["start"] = end
            elif _PINNED:
                # 结果区无命中 → 收藏区续找 (定位双通道覆盖收藏对比内容)
                ppos = self._pinned_box.search(
                    needle, "1.0", stopindex="end", nocase=True
                )
                if ppos:
                    self._pinned_box.see(ppos)
                    pend = f"{ppos}+{len(needle)}c"
                    self._pinned_box.tag_add("sel", ppos, pend)

        find_entry.bind("<Return>", lambda _e: _find_next())
        self.bind_all("<Control-f>", lambda _e: find_entry.focus_set() or "break")
        # Ctrl+A 全选输出 (CTkTextbox 不默认绑)
        self.bind_all(
            "<Control-a>",
            lambda _e: (
                self._output.tag_add("sel", "1.0", "end"),
                self._output.mark_set("insert", "end"),
                "break",
            )[2],
        )
        self._output = ctk.CTkTextbox(self, font=("Consolas", 12), wrap="none")
        self._output.pack(fill="both", expand=True, padx=14, pady=10)
        if _LAST_RESULT:
            self._output.insert("1.0", _LAST_RESULT)
        else:
            self._output.insert(
                "1.0",
                "模式速览 (Ctrl+1..9 直切): doc=全景 search=全包搜 list=表清单\n"
                "buffs=增益 export=导出 synth=配方 skills=技能 units=单位 locate=战役定位\n"
                "（有上会话结果时此处自动恢复; Ctrl+F 内搜本区）\n",
            )
        pin_menu = tk.Menu(self, tearoff=0)
        pin_menu.add_command(
            label="复制选中",
            command=lambda: (
                (
                    self._pinned_box.clipboard_clear(),
                    self._pinned_box.clipboard_append(
                        self._pinned_box.get("sel.first", "sel.last")
                    ),
                )
                if self._pinned_box.tag_ranges("sel")
                else None
            ),
        )
        pin_menu.add_command(label="复制收藏全部", command=self._copy_pinned)
        pin_menu.add_command(label="清空收藏", command=self._clear_pinned)
        pin_menu.add_separator()
        pin_menu.add_command(
            label="用选中坐标 near 再查 (半径 500)",
            command=lambda: self._near_rerun_from_pinned("500"),
        )
        pin_menu.add_command(
            label="用选中坐标 near 再查 (半径 100, 更精细)",
            command=lambda: self._near_rerun_from_pinned("100"),
        )
        pin_menu.add_command(
            label="用选中码查完整描述 (doc)",
            command=lambda: self._code_rerun("doc", self._pinned_box),
        )
        pin_menu.add_command(
            label="用选中码 where 反查获取途径",
            command=lambda: self._code_rerun("where", self._pinned_box),
        )
        pin_menu.add_command(
            label="用选中码 drop 反查掉落",
            command=lambda: self._code_rerun("drop", self._pinned_box),
        )
        pin_menu.add_command(
            label="导出收藏为 .md",
            command=lambda: self._export_md(self._pinned_box, "收藏对比"),
        )
        self._pinned_box.bind(
            "<Button-3>", lambda e: pin_menu.tk_popup(e.x_root, e.y_root)
        )
        self.bind_all("<Control-p>", lambda _e: self._pinned_box.focus_set() or "break")

        if prefill:
            self.after(120, lambda: self._run(prefill_command or "doc"))
        elif not _LAST_RESULT:
            self.after(120, lambda: self._run("stats"))
            self.after(120, lambda: self._run("doc"))

        menu = tk.Menu(self, tearoff=0)
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
        menu.add_command(label="复制全部", command=self._copy_all)
        menu.add_command(
            label="导出为 .md", command=lambda: self._export_md(self._output)
        )
        menu.add_separator()
        menu.add_command(
            label="用选中坐标 near 再查 (半径 500)",
            command=lambda: self._near_rerun_from_selection("500"),
        )
        menu.add_command(
            label="用选中坐标 near 再查 (半径 100, 更精细)",
            command=lambda: self._near_rerun_from_selection("100"),
        )
        menu.add_command(
            label="用选中码查完整描述 (doc)",
            command=lambda: self._code_rerun("doc"),
        )
        menu.add_command(
            label="用选中码 where 反查获取途径",
            command=lambda: self._code_rerun("where"),
        )
        menu.add_command(
            label="用选中码 drop 反查掉落",
            command=lambda: self._code_rerun("drop"),
        )
        self._output.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

    def _clear_history(self) -> None:
        _HISTORY.clear()
        _save_memo()
        self._history.set("(历史)")

    def _on_history_pick(self, value: str) -> None:
        for cmd, kw in _HISTORY:
            if f"{cmd} {kw}".strip() == value:
                self._switch_mode(
                    cmd
                )  # 走统一切换 (扩展排高亮/near 显隐/placeholder 跟随)
                self._keyword.delete(0, "end")
                self._keyword.insert(0, kw)
                self._run(cmd)
                return

    _PLACEHOLDERS = {
        "doc": "四码或名称…  (doc 必填)",
        "search": "关键词…  (search 必填)",
        "list": "表名可空=全表…  (回车查)",
        "buffs": "关键词可空=全量…  (回车查)",
        "export": "四码或名称…  (export 必填)",
        "synth": "全图配方…  (回车查)",
        "skills": "关键词可空=全量…  (回车查)",
        "units": "关键词可空=全量…  (回车查)",
        "locate": "特征码分号分隔: 码1;码2;…  (战役定位)",
        "near": "坐标反查: x y [radius] [--kind 单位/装饰/物品/脚本]  (探针 JSON 有 x/y)",
        "where": "物品名/四码 → 获取途径 (合成/掉落/商店/脚本奖励满量)",
        "drop": "单位/物品名 → 死亡掉落与奖池证据 (含脚本触发)",
        "again": "回车重跑最近一次成功查询 (pack/command/query 从记忆取)",
        "stats": "回车看包总览: 表行数/导出时间/查询记忆  (关键词可空)",
        "shop": "店名/商人 → 货架+制造+出售满量  (未命中列全图商店)",
        "tech": "科技名/码 → 等级/造价/效果/前置  (一屏科技单)",
        "item": "物品名/四码 → 效果/价格/描述 (自定义行优先)",
        "heroes": "英雄名 → 属性/技能/获取 (预放置+关系表)",
        "price": "物品名/四码 → 金币价 (地图价优先, 未命中给总量提示)",
    }

    def _near_kind_file(self) -> pathlib.Path:
        from .gui_pack_query import _memo_dir

        return pathlib.Path(_memo_dir()) / "near-kind.txt"

    def _load_near_kind(self) -> str:
        try:
            value = (
                pathlib.Path(self._near_kind_file()).read_text(encoding="utf-8").strip()
            )
        except OSError:
            return "全部"
        return value if value in ("全部", "单位", "装饰", "物品", "脚本") else "全部"

    def _save_near_kind(self, value: str) -> None:
        try:
            pathlib.Path(self._near_kind_file()).write_text(value, encoding="utf-8")
        except OSError:
            pass  # fail-open: 记忆失败不影响查询

    def _switch_mode(self, command: str) -> None:
        self._mode.set(command)
        # 扩展排高亮联动: 值属扩展组则高亮该值, 否则清高亮 (避免两排误导性高亮)
        if command in ("again", "stats", "shop", "tech", "item", "heroes", "price"):
            self._mode_extra.set(command)
        else:
            self._mode_extra.set("<<none>>")
        if command == "again":
            # placeholder 动态显示最近一次查询 (用户不用猜记忆里有什么)
            from .pack_query_cli import _load_last_query  # noqa: PLC0415

            last = _load_last_query()
            if last:
                self._keyword.configure(
                    placeholder_text=f"重跑: {last['command']} {last['query']}"
                )
                self._keyword.focus_set()
                return
        self._keyword.configure(placeholder_text=self._PLACEHOLDERS.get(command, ""))
        if command == "near":
            self._near_kind.pack(side="left", padx=(8, 0))
        else:
            self._near_kind.pack_forget()
        self._keyword.focus_set()

    def _code_rerun(self, prefix: str, box=None) -> None:
        """选中码以指定语义重查 (where=获取途径, drop=掉落; 对齐探针 306 直达)。"""
        box = box if box is not None else self._output
        try:
            raw = box.get("sel.first", "sel.last").strip()
        except tk.TclError:
            raw = ""
        import re as _re

        matches = _re.findall(r"[A-Z][0-9A-Z]{3}", raw)
        if len(matches) != 1:
            return  # 多匹配拒猜测 (对齐探针 309)
        self._switch_mode(prefix)
        self._keyword.delete(0, "end")
        self._keyword.insert(0, matches[0])
        self._run_clicked()

    def _near_rerun_from_box(self, box, radius: str) -> None:
        """选中行含坐标时以该点为中心再查 (半径收缩迭代, 由远及近逼近目标)。"""
        try:
            raw = box.get("sel.first", "sel.last").strip()
        except tk.TclError:
            raw = ""
        nums = re.findall(r"-?[\d.]+", raw)
        if len(nums) < 2:
            return
        self._switch_mode("near")  # 统一入口 (扩展排高亮清显跟随)
        self._keyword.delete(0, "end")
        self._keyword.insert(0, nums[0] + " " + nums[1] + " " + radius)
        self._run_clicked()

    def _near_rerun_from_selection(self, radius: str = "500") -> None:
        self._near_rerun_from_box(self._output, radius)

    def _near_rerun_from_pinned(self, radius: str = "500") -> None:
        self._near_rerun_from_box(self._pinned_box, radius)

    def _coords_from_clipboard(self) -> None:
        """从剪贴板提取坐标填入关键词框。
        支持两种形态: live 探针 JSON 片段 ("x": 150, "y": 150) 或裸「x y [radius]」。
        """
        try:
            raw = self.clipboard_get()
        except Exception:
            return
        # 优先取 selected 块内坐标 — 探针 JSON 的 selected 在最前, 尾部是 all_units
        # (旧取 xs[-1] 拿到的是全图末尾单位, 注释「通常=选中单位」不实)
        sel_block = re.search(r'"selected"\s*:\s*\{[^{}]*\}', raw)
        if sel_block:
            block = sel_block.group(0)
            mx = re.search(r'"x"\s*:\s*(-?[\d.]+)', block)
            my = re.search(r'"y"\s*:\s*(-?[\d.]+)', block)
            if mx and my:
                self._keyword.delete(0, "end")
                self._keyword.insert(0, mx.group(1) + " " + my.group(1))
                return
        xs = re.findall(r'"x"\s*:\s*(-?[\d.]+)', raw)
        ys = re.findall(r'"y"\s*:\s*(-?[\d.]+)', raw)
        if xs and ys:
            x, y = xs[-1], ys[-1]  # 无 selected 块时退最后一对 (裸坐标列表)
        else:
            nums = re.findall(r"-?[\d.]+", raw)
            if len(nums) < 2:
                return
            x, y = nums[0], nums[1]
        radius = re.findall(r'"radius"\s*:\s*([\d.]+)|半径\s*([\d.]+)', raw)
        parts = [x, y]
        if radius and (radius[-1][0] or radius[-1][1]):
            parts.append(radius[-1][0] or radius[-1][1])
        self._keyword.delete(0, "end")
        self._keyword.insert(0, " ".join(parts))

    def _extra_mode_clicked(self, value: str) -> None:
        """扩展面板点选: 同步主面板模式并执行切换 (near 专有控件显隐跟随)。"""
        self._mode.set(value)
        self._switch_mode(value)

    def _run_clicked(self) -> None:
        self._run(self._mode.get())

    def _run(self, command: str) -> None:
        global _LAST_KEYWORD, _LAST_MODE
        _LAST_KEYWORD = self._keyword.get().strip()  # pyright: ignore[reportConstantRedefinition]
        _LAST_MODE = command  # pyright: ignore[reportConstantRedefinition]
        keyword = self._keyword.get().strip()
        if command == "near":
            kind = self._near_kind.get()
            self._save_near_kind(kind)
            if kind != "全部":
                keyword = (keyword + " --kind " + kind).strip()
        # 免词清单 = 本窗九模式中可空词执行的 (affixes/registered 仅 CLI 有, 不在此窗)
        if keyword or command in (
            "stats",
            "list",
            "buffs",
            "skills",
            "units",
            "heroes",
            "synth",
        ):
            entry = (command, keyword)
            if entry in _HISTORY:
                _HISTORY.remove(entry)
            _HISTORY.insert(0, entry)
            del _HISTORY[10:]
        _save_memo()
        if (
            command in ("doc", "export", "search", "diff", "locate", "near")
            and not keyword
        ):
            self._output.delete("1.0", "end")
            self._find_state["start"] = "1.0"
            self._output.insert("1.0", f"{command} 需要四码或名称")
            return
        self._output.delete("1.0", "end")
        self._find_state["start"] = "1.0"
        self._output.insert("1.0", "查询中 …")
        self.configure(cursor="watch")
        # 后台线程跑查询, Tk 只在主线程碰 — 大包首查不再卡界面。
        # 交付用主线程轮询 (跨线程 after/event_generate 在 Tk 下会死锁主循环)
        import threading

        done: list[tuple[str, str]] = []
        as_json = self._var_json.get()

        def _worker() -> None:
            result, elapsed = self._run_query(command, keyword, as_json)
            # CLI again 共享记忆: GUI 成功查询也落 memo (未找到/异常不写)
            if command != "diff" and result and not result.startswith("未找到"):
                try:
                    from .pack_query_cli import _store_last_query

                    _store_last_query(pathlib.Path(self._pack_dir), command, keyword)
                except Exception:
                    pass
            done.append((result, elapsed))

        threading.Thread(target=_worker, daemon=True).start()

        def _poll() -> None:
            if done:
                result, elapsed = done[0]
                self._finish(result, elapsed)
                return
            if self.winfo_exists():
                self.after(60, _poll)

        self.after(60, _poll)

    def _run_query(
        self, command: str, keyword: str, as_json: bool = False
    ) -> tuple[str, str]:
        """线程内执行查询: 不碰任何 Tk 对象, 返回 (正文, 耗时行)。"""
        try:
            from gametool.pack_query_cli import (
                PackQueryCliOptions,
                run_pack_query_cli,
            )
        except ImportError as exc:  # pragma: no cover
            return (f"查询模块不可用: {exc}", "")
        import contextlib
        import io

        options = PackQueryCliOptions(
            pack_dir=self._pack_dir,
            command=command,
            query=keyword,
            limit=0,
            as_json=as_json,
        )
        buffer = io.StringIO()
        err_buffer = io.StringIO()
        try:
            with (
                contextlib.redirect_stdout(buffer),
                contextlib.redirect_stderr(err_buffer),
            ):
                run_pack_query_cli(options)
        except SystemExit as exc:  # run_pack_query_cli 返回码路径不打异常
            return (buffer.getvalue() or f"(退出码 {exc.code})", "")
        output = buffer.getvalue() or "(无输出)"
        elapsed = err_buffer.getvalue().strip()
        return (output, elapsed)

    def _pin_current(self) -> None:
        text = self._output.get("1.0", "end").strip()
        if not text or text.startswith("查询中") or "需要四码或名称" in text:
            return
        title = f"{self._mode.get()} {self._keyword.get().strip()}"
        # 同题收藏覆盖旧藏 (对比场景同一查询只需最新一份, 且地图改动后重查值得更新)
        _PINNED[:] = [p for p in _PINNED if p[0] != title]
        _PINNED.append((title, text))
        _save_memo()
        self._render_pinned()
        self._refresh_pin_button()

    def _clear_pinned(self) -> None:
        _PINNED.clear()
        _save_memo()
        self._pinned_box.delete("1.0", "end")
        self._refresh_pin_button()

    def _export_md(self, source_box, label: str = "查询结果") -> None:
        text = source_box.get("1.0", "end").strip()
        if not text:
            return
        from .archive_export import tmp_extract_dir

        out_dir = tmp_extract_dir("pack-query-export")
        safe = "".join(ch if ch not in '\\/:*?"<>|' else "_" for ch in label)
        out_path = os.path.join(out_dir, safe + ".md")
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        self._output.insert("end", f"\n[已导出: {out_path}]\n")
        self._find_state["start"] = "1.0"
        self.clipboard_clear()
        self.clipboard_append(out_path)

    def _copy_pinned(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._pinned_box.get("1.0", "end"))

    def _pin_button_text(self) -> str:
        n = len(_PINNED)
        return f"⊕ 收藏本次结果 (对比用) [{n} 项]" if n else "⊕ 收藏本次结果 (对比用)"

    def _refresh_pin_button(self) -> None:
        assert self._pin_button is not None
        self._pin_button.configure(text=self._pin_button_text())

    def _render_pinned(self) -> None:
        self._pinned_box.delete("1.0", "end")
        self._pinned_box.tag_config("del-mark", foreground="#d33", underline=True)
        for index, (title, text) in enumerate(_PINNED):
            mark = f"del-{index}"
            self._pinned_box.tag_delete(mark)
            self._pinned_box.insert("end", "[删] ", mark)
            self._pinned_box.tag_bind(
                mark,
                "<Button-1>",
                lambda _e, i=index: self._remove_pinned(i),
            )
            self._pinned_box.insert("end", f"==== 收藏: {title} ====" + "\n")
            self._pinned_box.insert("end", text + "\n\n")

    def _remove_pinned(self, index: int) -> None:
        if 0 <= index < len(_PINNED):
            del _PINNED[index]
            _save_memo()
            self._render_pinned()
            self._refresh_pin_button()

    def _copy_all(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._output.get("1.0", "end"))

    def _finish(self, text: str, elapsed: str = "") -> None:
        global _LAST_RESULT
        # export 模式: CLI 输出含 [已导出: 路径], 自动复制路径进剪贴板
        if "[已导出: " in text:
            exported = text.split("[已导出: ", 1)[1].split("]", 1)[0]
            self.clipboard_clear()
            self.clipboard_append(exported)
            text += "\n(路径已复制到剪贴板)"
        if elapsed:
            text += f"\n──────────  {elapsed}  ──────────\n"
        _LAST_RESULT = text  # pyright: ignore[reportConstantRedefinition]
        self.configure(cursor="")
        self._output.delete("1.0", "end")
        self._find_state["start"] = "1.0"
        self._output.insert("1.0", text)
