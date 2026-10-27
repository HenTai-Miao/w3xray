"""Author plaintext and real-save actions exposed through the GUI data menu."""

from __future__ import annotations

from typing import TYPE_CHECKING

import os
from pathlib import Path
from tkinter import filedialog, messagebox

from .api import tmp_extract_dir
from .author_plaintext_bundle import MANIFEST_NAME
from .gui_worker_registry import GuiWorkerTicket
from .knowledge_io import write_text
from .real_save_files import analyze_real_save_path, format_real_save_report_tsv
from .trusted_description_cache import (
    TrustedDescriptionCacheError,
    VerifiedDescriptionCache,
    load_trusted_description_cache,
)


class ExternalDataToolsMixin:
    """Manage author plaintext selection and read-only save analysis actions."""

    if TYPE_CHECKING:
        import customtkinter as ctk
        import tkinter as tk
        from collections.abc import Callable

        from .map_data import MapData

        data_tools_button: ctk.CTkButton  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        data_tools_menu: tk.Menu  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        map_data: MapData | None  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        status: ctk.CTkLabel  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        _load_config: Callable[[], dict[str, str]]  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        _need_map: Callable[..., object]  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        _open_dir: Callable[..., object]  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        _post_gui_worker: Callable[..., object]  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        _refresh_external_source_labels: Callable[..., object]  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        _reload_active_source: Callable[..., object]  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        _save_config: Callable[..., None]  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        _start_gui_worker: Callable[..., object]  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        _start_gui_map_worker: Callable[..., object]  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入

    author_bundle_path: str | None  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
    description_cache_path: str | None  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
    description_cache_manifest_sha256: str = ""
    description_cache_entry_count: int = 0

    def on_pick_author_bundle(self) -> None:
        path = filedialog.askdirectory(title="选择作者明文补充包目录")
        if not path:
            return
        if not os.path.isfile(os.path.join(path, MANIFEST_NAME)):
            messagebox.showerror("明文包无效", f"目录中缺少 {MANIFEST_NAME}")
            return
        self.author_bundle_path = path
        self._save_config(author_bundle_path=path)
        self._refresh_external_source_labels()
        self._reload_active_source()

    def on_clear_author_bundle(self) -> None:
        self.author_bundle_path = None
        self._save_config(author_bundle_path=None)
        self._refresh_external_source_labels()
        self._reload_active_source()

    def on_pick_description_cache(self) -> None:
        path = filedialog.askdirectory(title="选择 GAMEXRAY 可信描述缓存目录")
        if not path:
            return
        try:
            verified = load_trusted_description_cache(Path(path))
        except TrustedDescriptionCacheError as exc:
            messagebox.showerror("可信描述缓存无效", str(exc))
            return
        self.description_cache_path = path
        self._set_description_cache_identity(verified)
        self._save_config(description_cache_path=path)
        self._refresh_description_cache_state()
        self._reload_active_source()

    def on_clear_description_cache(self) -> None:
        self.description_cache_path = None
        self.description_cache_manifest_sha256 = ""
        self.description_cache_entry_count = 0
        self._save_config(description_cache_path=None)
        self._refresh_description_cache_state()
        self._reload_active_source()

    def _restore_description_cache(self) -> None:
        path = self._load_config().get("description_cache_path")
        self.description_cache_path = None
        self.description_cache_manifest_sha256 = ""
        self.description_cache_entry_count = 0
        if isinstance(path, str):
            try:
                verified = load_trusted_description_cache(Path(path))
            except TrustedDescriptionCacheError:
                verified = None
            if verified is not None:
                self.description_cache_path = path
                self._set_description_cache_identity(verified)
        self._refresh_description_cache_state()

    def _set_description_cache_identity(
        self,
        verified: VerifiedDescriptionCache,
    ) -> None:
        self.description_cache_manifest_sha256 = verified.manifest_sha256
        self.description_cache_entry_count = len(verified.cache.entries)

    def _refresh_description_cache_state(self) -> None:
        if hasattr(self, "data_tools_menu"):
            self.data_tools_menu.entryconfigure(
                "清除可信描述缓存",
                state="normal" if self.description_cache_path else "disabled",
            )
        if hasattr(self, "data_tools_button"):
            text = "数据工具*" if self.author_bundle_path else "数据工具"
            if self.description_cache_path is not None:
                text = (
                    f"缓存 {self.description_cache_manifest_sha256[:12]} · "
                    f"{self.description_cache_entry_count} 条"
                )
            self.data_tools_button.configure(text=text)

    def on_analyze_real_save_file(self) -> None:
        if not self._need_map():
            return
        path = filedialog.askopenfilename(
            title="选择真实存档文件", filetypes=[("所有文件", "*.*")]
        )
        if path:
            self._start_real_save_analysis(path)

    def on_analyze_real_save_directory(self) -> None:
        if not self._need_map():
            return
        path = filedialog.askdirectory(title="选择真实存档目录")
        if path:
            self._start_real_save_analysis(path)

    def _start_real_save_analysis(self, path: str) -> None:
        md = self.map_data
        if md is None:
            self.status.configure(text="先打开地图再分析存档")
            return
        out = tmp_extract_dir(md.name, "真实存档分析", clean=True)
        self.status.configure(text="正在只读分析真实存档 …")

        def work(ticket: GuiWorkerTicket) -> None:
            try:
                report = analyze_real_save_path(path, md)
                if ticket.cancellation.is_set():
                    return
                count = write_text(
                    out, "真实存档分析.tsv", format_real_save_report_tsv(report)
                )
                if report.warnings:
                    count += write_text(
                        out, "真实存档警告.txt", "\n".join(report.warnings) + "\n"
                    )
                _ = self._post_gui_worker(
                    ticket,
                    lambda: self._open_dir(out, count, "存档分析文件"),
                )
            except (
                Exception
            ) as exc:  # BROAD_EXCEPT_OK - GUI worker boundary reports failures.
                message = str(exc)
                _ = self._post_gui_worker(
                    ticket,
                    lambda: messagebox.showerror("存档分析失败", message),
                )

        _ = self._start_gui_map_worker("real-save-analysis", md, work, replace=True)
