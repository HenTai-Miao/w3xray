"""live 探针 GUI 弹窗: 只读内存读取 → 输出区 + JSON 自动复制。

只读纪律: 背后是 live_cli.run_live_cli (ReadProcessMemory/PrintWindow 快照),
绝不注入、绝不写游戏内存。
"""

from __future__ import annotations

from collections.abc import Callable
import os
import pathlib
import tkinter as tk
import threading

import customtkinter as ctk

from .theme import BG, CARD, TEXT, TEXT_STRONG

_FONT = ("Microsoft YaHei UI", 11)


class LiveProbeWindow(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        pack_dir: str | None,
        query_callback: "Callable[[str], None] | None" = None,
    ) -> None:
        super().__init__(master)
        self._pack_dir = pack_dir
        self._query_callback = query_callback
        pack_name = pathlib.Path(pack_dir).name if pack_dir else ""
        self.title(
            "live 探针 — 只读内存读取" + (f" · {pack_name}" if pack_name else "")
        )
        self.geometry("860x560")
        self.configure(fg_color=BG)
        self.transient(master)
        self.grab_set()
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Control-r>", lambda _e: self._start())
        self.bind("<Control-r>", lambda _e: self._start())
        # CapsLock 大写态变体 (Tk 绑定大小写敏感)
        self.bind("<Control-R>", lambda _e: self._start())
        from .gui_pack_query import bind_geometry_memory

        bind_geometry_memory(self, "gui-live-probe", "860x560")

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
        self._var_players = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            bar,
            text="玩家列表",
            variable=self._var_players,
            font=("Microsoft YaHei UI", 10),
        ).pack(side="left", padx=(0, 6))
        self._var_all_units = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            bar,
            text="全单位",
            variable=self._var_all_units,
            font=("Microsoft YaHei UI", 10),
        ).pack(side="left", padx=(0, 6))
        self._var_resources = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            bar,
            text="资源对齐 (HUD 值校准)",
            variable=self._var_resources,
            font=("Microsoft YaHei UI", 10),
        ).pack(side="left", padx=(0, 6))
        self._copy_hint = ctk.CTkLabel(
            bar, text="", font=("Microsoft YaHei UI", 10), text_color=TEXT
        )
        self._copy_hint.pack(side="right", padx=12)

        self._output = ctk.CTkTextbox(self, fg_color=CARD, text_color=TEXT, font=_FONT)
        self._output.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self._output.insert("1.0", "点击「开始探针」读取当前对局 (需游戏运行中)。")
        self._output.configure(state="disabled")

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
            pos = self._output.search(needle, start, stopindex="end", nocase=True)
            if not pos:
                pos = self._output.search(
                    needle, "1.0", stopindex="end", nocase=True
                )  # 回卷
            if pos:
                self._output.see(pos)
                end = f"{pos}+{len(needle)}c"
                self._output.tag_add("sel", pos, end)
                self._find_state["start"] = end

        find_entry.bind("<Return>", lambda _e: _find_next())
        self.bind_all("<Control-f>", lambda _e: find_entry.focus_set() or "break")
        # CapsLock 大写态变体 (Tk 绑定大小写敏感)
        self.bind_all("<Control-F>", lambda _e: find_entry.focus_set() or "break")
        # Ctrl+A 全选输出 (CTkTextbox 不默认绑)
        self.bind_all(
            "<Control-a>",
            lambda _e: (
                self._output.tag_add("sel", "1.0", "end"),
                self._output.mark_set("insert", "end"),
                "break",
            )[2],
        )
        # CapsLock 大写态变体 (Tk 绑定大小写敏感)
        self.bind_all(
            "<Control-A>",
            lambda _e: (
                self._output.tag_add("sel", "1.0", "end"),
                self._output.mark_set("insert", "end"),
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

        self.after(120, self._start)

    def _last_unit_query_file(self) -> pathlib.Path:
        from .gui_pack_query import _memo_dir

        return pathlib.Path(_memo_dir()) / "live-probe-unit.txt"

    def _load_last_unit_query(self) -> str:
        try:
            return (
                pathlib.Path(self._last_unit_query_file())
                .read_text(encoding="utf-8")
                .strip()
            )
        except OSError:
            return ""

    def _save_last_unit_query(self, query: str | None) -> None:
        if not query:
            return
        try:
            pathlib.Path(self._last_unit_query_file()).write_text(
                query, encoding="utf-8"
            )
        except OSError:
            pass  # fail-open: 记忆失败不影响探针

    def _last_map_path_file(self) -> pathlib.Path:
        from .gui_pack_query import _memo_dir

        return pathlib.Path(_memo_dir()) / "live-probe-map.txt"

    def _load_last_map_path(self) -> str:
        try:
            return (
                pathlib.Path(self._last_map_path_file())
                .read_text(encoding="utf-8")
                .strip()
            )
        except OSError:
            return ""

    def _save_last_map_path(self, path: str | None) -> None:
        if not path:
            return
        try:
            pathlib.Path(self._last_map_path_file()).write_text(path, encoding="utf-8")
        except OSError:
            pass  # fail-open: 记忆失败不影响探针

    def _start(self) -> None:
        if self._probe_button.cget("state") == "disabled":
            return
        self._probe_button.configure(state="disabled")
        self._copy_hint.configure(text="")
        self._output.configure(state="normal")
        self._output.delete("1.0", "end")
        self._output.insert("1.0", "探针中 … (读内存 + 自动定位资料包)")
        self._output.configure(state="disabled")

        pack_dir = self._pack_dir
        want_players = self._var_players.get()
        want_all = self._var_all_units.get()
        want_resources = self._var_resources.get()
        map_path = self._map_entry.get().strip() or None
        unit_query = self._unit_entry.get().strip() or None
        self._save_last_unit_query(unit_query)  # 注意: 上一行缩进已同块
        self._save_last_map_path(map_path)
        done: list[str] = []

        def _worker() -> None:
            import contextlib
            import io

            from .live_cli import LiveCliOptions, run_live_cli

            buffer = io.StringIO()
            err_buffer = io.StringIO()
            resources = ("reported", "reported") if want_resources else None
            options = LiveCliOptions(
                map_path=map_path,
                unit_query=unit_query,
                pack_dir=pack_dir,
                players=want_players,
                all_units=want_all,
                resources=resources,
            )
            code = 0
            try:
                with (
                    contextlib.redirect_stdout(buffer),
                    contextlib.redirect_stderr(err_buffer),
                ):
                    code = run_live_cli(options)
            except SystemExit as exc:  # 返回码路径
                code = int(exc.code or 0)
            except Exception as exc:  # 撑住弹窗: 任何异常都落文本区
                done.append(f"探针异常: {type(exc).__name__}: {exc}")
                return
            body = buffer.getvalue()
            if code != 0 and err_buffer.getvalue().strip():
                # 出路口径走 stderr (无图/未运行/主菜单提示) — GUI 用户必须看到
                body = body + err_buffer.getvalue()
            done.append(f"{code}" + chr(0) + body)

        threading.Thread(target=_worker, daemon=True).start()

        def _poll() -> None:
            if not self.winfo_exists():
                return
            if not done:
                self.after(80, _poll)
                return
            self._finish(done[0])

        self.after(80, _poll)

    def _finish(self, text: str) -> None:
        self._probe_button.configure(state="normal")
        if chr(0) in text:
            code_str, body = text.split(chr(0), 1)
            body = body or "(无输出)"
        else:
            code_str, body = "1", text
        # 探针 JSON 自动复制: 尾部 {" 开头的整段 (供 near 模式「从剪贴板提取坐标」直接用)
        copied = ""
        # 外层根 = 首个行首 { (indent 输出); rindex 会命中内层对象致 Extra data
        root_pos = next(
            (
                i
                for i, ch in enumerate(body)
                if ch == "{" and (i == 0 or body[i - 1] in (chr(10), chr(13)))
            ),
            -1,
        )
        tail = body[root_pos:] if root_pos >= 0 else ""
        if tail.strip() and code_str == "0":
            try:
                self.clipboard_clear()
                self.clipboard_append(tail.strip())
                copied = "  ·  探针 JSON 已复制 (near 可提取坐标)"
                # 结构化摘要: 单位/物品/玩家数一行可见, 免读长输出
                import json

                try:
                    probe = json.loads(tail.strip())
                    unit_count = len(probe.get("units") or [])
                    item_count = sum(
                        len(u.get("items") or []) for u in probe.get("units") or []
                    )
                    owned = probe.get("owned_units")
                    extra = ""
                    if owned is not None:
                        extra = f" · 在场单位 {len(owned)}"
                    copied = (
                        f"  ·  带物单位 {unit_count} · 物品 {item_count}{extra}"
                        + "  ·  JSON 已复制 (near 可提取坐标)"
                    )
                except ValueError:
                    pass
            except Exception:
                copied = ""
        self._copy_hint.configure(text=copied)
        self._output.configure(state="normal")
        self._output.delete("1.0", "end")
        self._output.insert("1.0", body if body.strip() else f"(退出码 {code_str})")
        self._output.see("1.0")  # 回滚视口到摘要行 (长输出时旧视口停在中部)
        self._output.configure(state="disabled")

    def _near_selected_coords(self) -> None:
        """取选中/剪贴板的 x/y, 交给包查询窗 near 模式反查。"""
        try:
            raw = self._output.get("sel.first", "sel.last").strip()
        except tk.TclError:
            raw = ""
        if not raw:
            try:
                raw = self.clipboard_get().strip()
            except Exception:
                return
        import re

        # JSON 形态显式取 selected 块坐标 (对齐查询窗 312 轮语义——尾部是 all_units,
        # 取首对数靠「selected 恰好在前」的巧合而非结构语义)
        sel_block = re.search(r'"selected"\s*:\s*\{[^{}]*\}', raw)
        if sel_block:
            mx = re.search(r'"x"\s*:\s*(-?[\d.]+)', sel_block.group(0))
            my = re.search(r'"y"\s*:\s*(-?[\d.]+)', sel_block.group(0))
            if mx and my:
                if self._query_callback is not None:
                    self._query_callback(f"near {mx.group(1)} {my.group(1)}")
                return
        nums = re.findall(r"-?\d+(?:\.\d+)?", raw)
        if len(nums) < 2:
            return
        x, y = nums[0], nums[1]
        if self._query_callback is not None:
            self._query_callback(f"near {x} {y}")

    def _near_rerun_selected(self, radius: str = "500") -> None:
        """选中/剪贴板坐标以半径 500 再查 (对齐查询窗 315 收缩迭代语义)。"""
        try:
            raw = self._output.get("sel.first", "sel.last").strip()
        except tk.TclError:
            raw = ""
        if not raw:
            try:
                raw = self.clipboard_get().strip()
            except Exception:
                return
        import re

        nums = re.findall(r"-?\d+(?:\.\d+)?", raw)
        if len(nums) < 2:
            return
        if self._query_callback is not None:
            self._query_callback(f"near {nums[0]} {nums[1]} {radius}")

    def _extract_code(self) -> str:
        """取输出区选中文本 (退剪贴板) 的四码, 无则空串。"""
        try:
            code = self._output.get("sel.first", "sel.last").strip()
        except tk.TclError:
            code = ""
        if not code:
            try:
                code = self.clipboard_get().strip()
            except Exception:
                return ""
        # 四码或含四码的片段都行: 提取前一个 [A-Z][0-9A-Z]{3} 形态
        import re

        matches = re.findall(r"[A-Z][0-9A-Z]{3}", code)
        if not matches:
            return ""
        if len(matches) > 1:
            # 全选/长选区含多个码 — 猜一个会误导 (JSON 尾部首个码是随机条目)
            self._copy_hint.configure(text="选区含多个码——请精确选中一个")
            return ""
        return matches[0]

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


def open_live_probe_dialog(
    master,
    pack_dir: str | None = None,
    query_callback: "Callable[[str], None] | None" = None,
) -> None:
    if pack_dir is None:
        pack_dir = os.environ.get("GAMEXRAY_LAST_PACK", "") or None
    LiveProbeWindow(master, pack_dir, query_callback=query_callback)
