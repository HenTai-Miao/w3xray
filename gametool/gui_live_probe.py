"""live 探针 GUI 弹窗: 只读内存读取 → 输出区 + JSON 自动复制。

只读纪律: 背后是 live_cli.run_live_cli (ReadProcessMemory/PrintWindow 快照),
绝不注入、绝不写游戏内存。
"""

from __future__ import annotations

import os
import threading

import customtkinter as ctk

from .theme import BG, CARD, TEXT, TEXT_STRONG

_FONT = ("Microsoft YaHei UI", 11)


class LiveProbeWindow(ctk.CTkToplevel):
    def __init__(self, master, pack_dir: str | None) -> None:
        super().__init__(master)
        self._pack_dir = pack_dir
        self.title("live 探针 — 只读内存读取")
        self.geometry("860x560")
        self.configure(fg_color=BG)
        self.transient(master)
        self.grab_set()
        self.bind("<Escape>", lambda _e: self.destroy())

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
            text="开始探针",
            width=110,
            font=_FONT,
            command=self._start,
        )
        self._probe_button.pack(side="left", padx=(12, 6), pady=8)
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

        self.after(120, self._start)

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
        done: list[str] = []

        def _worker() -> None:
            import contextlib
            import io

            from .live_cli import LiveCliOptions, run_live_cli

            buffer = io.StringIO()
            resources = ("reported", "reported") if want_resources else None
            options = LiveCliOptions(
                pack_dir=pack_dir,
                players=want_players,
                all_units=want_all,
                resources=resources,
            )
            code = 0
            try:
                with contextlib.redirect_stdout(buffer):
                    code = run_live_cli(options)
            except SystemExit as exc:  # 返回码路径
                code = int(exc.code or 0)
            except Exception as exc:  # 撑住弹窗: 任何异常都落文本区
                done.append(f"探针异常: {type(exc).__name__}: {exc}")
                return
            done.append(f"__CODE__{code}__" + buffer.getvalue())

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
        if text.startswith("__CODE__"):
            code_str, body = text.split("__", 2)[1], text.split("__", 2)[2]
            body = body or "(无输出)"
        else:
            code_str, body = "1", text
        # 探针 JSON 自动复制: 尾部 {" 开头的整段 (供 near 模式「从剪贴板提取坐标」直接用)
        copied = ""
        tail = body[body.rindex('{"') :] if '{"' in body else ""
        if tail.strip() and code_str == "0":
            try:
                self.clipboard_clear()
                self.clipboard_append(tail.strip())
                copied = "  ·  探针 JSON 已复制到剪贴板 (near 模式可一键提取坐标)"
            except Exception:
                copied = ""
        self._copy_hint.configure(text=copied)
        self._output.configure(state="normal")
        self._output.delete("1.0", "end")
        self._output.insert("1.0", body if body.strip() else f"(退出码 {code_str})")
        self._output.configure(state="disabled")


def open_live_probe_dialog(master, pack_dir: str | None = None) -> None:
    if pack_dir is None:
        pack_dir = os.environ.get("GAMEXRAY_LAST_PACK", "") or None
    LiveProbeWindow(master, pack_dir)
