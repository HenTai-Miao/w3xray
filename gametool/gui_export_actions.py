"""GUI export actions kept out of the main application shell."""

from __future__ import annotations

import os
from dataclasses import dataclass
from tkinter import messagebox
from typing import TYPE_CHECKING, assert_never

from .api import export_all_files, export_loaded_map_files, tmp_extract_dir
from .gui_worker_registry import GuiWorkerTicket
from .knowledge_io import safe_filename, write_text
from .knowledge_pack import format_box_id_text, write_knowledge_pack_family_report
from .extraction_profile import ExtractionProfile, load_profile
from .knowledge_results import KnowledgeWriteReport, KnowledgeWriteStatus
from .knowledge_script_exports import write_script_exports
from .presentation_safety import format_user_exception
from .script_text_export import build_readable_script_exports
from .map_data import MapData


@dataclass(frozen=True, slots=True)
class PackExportPresentation:
    title: str
    status_text: str
    message: str
    is_error: bool


@dataclass(frozen=True, slots=True)
class _CurrentMapPack:
    source: MapData
    directory: str


@dataclass(frozen=True, slots=True)
class _PendingPackQuery:
    source: MapData
    prefill: str
    command: str


def build_pack_export_presentation(
    out_dir: str,
    report: KnowledgeWriteReport,
) -> PackExportPresentation:
    """Build GUI copy from the exact pack publication outcome."""
    counts = f"成功 {report.written_count}，失败 {report.failed_count}"
    failure = report.first_failure
    failure_text = ""
    if failure is not None:
        failure_text = f"\n首个失败：{failure.path}\n{failure.error or '未知错误'}"
    match report.status:
        case KnowledgeWriteStatus.COMPLETE:
            return PackExportPresentation(
                "完成",
                f"资料包已完整导出：{report.written_count} 个文件",
                f"资料包已完整导出到临时目录：\n{out_dir}\n（临时文件，可随时清理）",
                False,
            )
        case KnowledgeWriteStatus.PARTIAL:
            return PackExportPresentation(
                "部分完成",
                f"资料包部分导出：{counts}",
                f"资料包仅部分写入临时目录：\n{out_dir}\n{counts}{failure_text}",
                False,
            )
        case KnowledgeWriteStatus.FAILED:
            return PackExportPresentation(
                "导出失败",
                f"资料包写入失败：{counts}",
                f"资料包没有成功写入：\n{out_dir}\n{counts}{failure_text}",
                True,
            )
        case unreachable:
            assert_never(unreachable)


class ExportActionsMixin:
    _current_map_pack: _CurrentMapPack | None = None
    _pending_pack_query: _PendingPackQuery | None = None
    _pack_export_source: MapData | None = None

    if TYPE_CHECKING:
        import customtkinter as ctk
        from collections.abc import Callable

        from .map_data import MapData

        _campaign_path: str | None  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        external_listfile_path: str | None  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        game_data_path: str | None  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        map_data: MapData | None  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        status: ctk.CTkLabel  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        _last_pack_dir: str | None = None
        _post_gui_worker: Callable[..., object]  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        _start_gui_worker: Callable[..., object]  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        _start_gui_map_worker: Callable[..., object]  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        update_idletasks: Callable[[], None]  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入

    def _need_map(self) -> "MapData | None":
        """未开图弹提示并返回 None；已开图返回 md (调用方以 is None 判空)。"""
        if not self.map_data:
            messagebox.showinfo("提示", "请先打开一张地图")
            return None
        return self.map_data

    def _invalidate_current_map_pack(self, md: MapData | None) -> None:
        binding = self._current_map_pack
        if binding is not None and binding.source is not md:
            self._current_map_pack = None
        pending = self._pending_pack_query
        if pending is not None and pending.source is not md:
            self._pending_pack_query = None

    def current_map_pack_dir(self, source_map: MapData | None = None) -> str | None:
        """Return only this loaded map instance's successfully published pack."""
        md = self.map_data
        self._invalidate_current_map_pack(md)
        if md is None or (source_map is not None and source_map is not md):
            return None
        binding = self._current_map_pack
        if binding is None or not os.path.isdir(binding.directory):
            return None
        return binding.directory

    def on_pack_query(
        self,
        prefill: str = "",
        prefill_command: str = "",
        *,
        source_map: MapData | None = None,
    ) -> None:
        """Open the current map's query, exporting it first when needed."""
        md = self._need_map()
        if md is None:
            return
        if source_map is not None and source_map is not md:
            self.status.configure(text="地图已切换，请从当前地图重新发起查询")
            return
        request = _PendingPackQuery(md, prefill, prefill_command)
        if self.current_map_pack_dir(md) is not None:
            self._open_current_map_query(request)
            return
        self._pending_pack_query = request
        self.on_export_pack()

    def _open_current_map_query(self, request: _PendingPackQuery) -> None:
        from .gui_pack_query import open_pack_query_dialog

        if self.map_data is not request.source:
            return
        open_pack_query_dialog(
            self,
            lambda: self.current_map_pack_dir(request.source),
            lambda: self.on_pack_query(
                request.prefill, request.command, source_map=request.source
            ),
            prefill=request.prefill,
            prefill_command=request.command,
        )

    def _open_dir(self, out, n, kind):
        self.status.configure(text=f"已导出 {n} 个{kind}到临时目录 {out}")
        message = f"已导出 {n} 个{kind}到临时目录：\n{out}\n（临时文件，可随时清理）"
        try:
            os.startfile(out)
        except AttributeError, OSError:
            messagebox.showinfo("完成", message)
            return
        messagebox.showinfo("完成", message)

    def _show_pack_result(self, out: str, report: KnowledgeWriteReport) -> None:
        presentation = build_pack_export_presentation(out, report)
        self.status.configure(text=presentation.status_text)
        if presentation.is_error:
            messagebox.showerror(presentation.title, presentation.message)
            return
        try:
            os.startfile(out)
        except AttributeError, OSError:
            messagebox.showinfo(presentation.title, presentation.message)
            return
        messagebox.showinfo(presentation.title, presentation.message)

    def _show_export_error(self, message: str) -> None:
        self.status.configure(text="导出失败")
        messagebox.showerror("导出失败", message)

    def on_export_all(self):
        md = self._need_map()
        if md is None:
            return
        campaign_path = self._campaign_path
        path = campaign_path or md.path
        is_campaign_child = campaign_path is not None and md.path != campaign_path
        external_listfile_path = self.external_listfile_path
        self.status.configure(text="正在解包全部文件到临时目录 …")
        self.update_idletasks()

        def work(ticket: GuiWorkerTicket) -> None:
            try:
                if is_campaign_child:
                    out = export_loaded_map_files(
                        md,
                        external_listfile_path=external_listfile_path,
                    )
                else:
                    out = export_all_files(
                        path,
                        external_listfile_path=external_listfile_path,
                    )
                n = sum(len(fs) for _, _, fs in os.walk(out))
                _ = self._post_gui_worker(
                    ticket,
                    lambda: self._open_dir(out, n, "文件"),
                )
            except (
                Exception
            ) as exc:  # BROAD_EXCEPT_OK - GUI worker boundary reports export failures.
                error_text = format_user_exception(exc, paths=(path, md.path))
                _ = self._post_gui_worker(
                    ticket,
                    lambda message=error_text: self._show_export_error(message),
                )

        _ = self._start_gui_map_worker("export-all", md, work, replace=True)

    def on_export_scripts(self):
        md = self._need_map()
        if md is None:
            return
        self.status.configure(text="正在导出脚本 …")

        def work(ticket: GuiWorkerTicket) -> None:
            out = ""
            try:
                out = tmp_extract_dir(md.name, "脚本", clean=True)
                scripts = build_readable_script_exports(md)
                n = write_script_exports(scripts, out)
                _ = self._post_gui_worker(
                    ticket,
                    lambda: self._open_dir(out, n, "脚本"),
                )
            except (
                Exception
            ) as exc:  # BROAD_EXCEPT_OK - GUI worker boundary reports export failures.
                error_text = format_user_exception(exc, paths=(out, md.path))
                _ = self._post_gui_worker(
                    ticket,
                    lambda message=error_text: self._show_export_error(message),
                )

        _ = self._start_gui_map_worker("export-scripts", md, work, replace=True)

    def on_export_ids(self):
        md = self._need_map()
        if md is None:
            return
        self.status.configure(text="正在导出ID列表 …")

        def work(ticket: GuiWorkerTicket) -> None:
            out = ""
            try:
                out = tmp_extract_dir(md.name, "ID列表", clean=True)
                n = 0
                for cat, objs in md.objects.items():
                    if ticket.cancellation.is_set():
                        return
                    name = f"{safe_filename(cat)}ID.txt"
                    n += write_text(out, name, format_box_id_text(objs, category=cat))
                _ = self._post_gui_worker(
                    ticket,
                    lambda: self._open_dir(out, n, "分类的ID列表"),
                )
            except (
                Exception
            ) as exc:  # BROAD_EXCEPT_OK - GUI worker boundary reports export failures.
                error_text = format_user_exception(exc, paths=(out, md.path))
                _ = self._post_gui_worker(
                    ticket,
                    lambda message=error_text: self._show_export_error(message),
                )

        _ = self._start_gui_map_worker("export-ids", md, work, replace=True)

    def on_export_pack(self):
        md = self._need_map()
        if md is None:
            return
        self._invalidate_current_map_pack(md)
        if self._pack_export_source is md:
            return
        self._pack_export_source = md
        automatic = (
            self._pending_pack_query is not None
            and self._pending_pack_query.source is md
        )
        # 首次导出大图时物化是主要开销；默认吃满可用核（用户可显式覆盖）。
        os.environ.setdefault("GAMEXRAY_MATERIALIZE_WORKERS", str(os.cpu_count() or 1))
        game_data_path = self.game_data_path
        self.status.configure(text="正在整理地图资料包 …")

        def work(ticket: GuiWorkerTicket) -> None:
            out = ""
            try:
                out = tmp_extract_dir(md.name, "资料包", clean=True)
                profile = ExtractionProfile() if automatic else load_profile()
                full_profile = not profile.disabled_categories()
                report = write_knowledge_pack_family_report(
                    md,
                    out,
                    game_data_path=game_data_path,
                    profile=profile,
                )

                def finish() -> None:
                    self._pack_export_source = None
                    if report.written_count > 0:
                        self._last_pack_dir = out
                        save_last_pack_dir(out)
                        if self.map_data is md and full_profile:
                            self._current_map_pack = _CurrentMapPack(md, out)
                    request = self._pending_pack_query
                    if request is not None and request.source is md:
                        if self.map_data is md and report.written_count > 0:
                            if not full_profile:
                                self.on_export_pack()
                                return
                            self._pending_pack_query = None
                            presentation = build_pack_export_presentation(out, report)
                            self.status.configure(text=presentation.status_text)
                            self._open_current_map_query(request)
                            if report.failed_count:
                                messagebox.showwarning(
                                    presentation.title, presentation.message
                                )
                            return
                        self._pending_pack_query = None
                    if not automatic or self.map_data is md:
                        self._show_pack_result(out, report)

                _ = self._post_gui_worker(
                    ticket,
                    finish,
                )
            except (
                Exception
            ) as exc:  # BROAD_EXCEPT_OK - GUI worker boundary reports export failures.
                error_text = format_user_exception(exc, paths=(out, md.path))

                def failed(message: str = error_text) -> None:
                    self._pack_export_source = None
                    request = self._pending_pack_query
                    if request is not None and request.source is md:
                        self._pending_pack_query = None
                    if not automatic or self.map_data is md:
                        self._show_export_error(message)

                _ = self._post_gui_worker(
                    ticket,
                    failed,
                )

        _ = self._start_gui_map_worker("export-pack", md, work, replace=True)

    def on_dump_runtime_objects(self):
        """live --dump-objects: 从运行中游戏读词缀/注册数据到内存导出包。"""
        pack_dir = self.current_map_pack_dir()
        if not pack_dir or not os.path.isdir(pack_dir):
            messagebox.showinfo(
                "需要资料包",
                "先「导出资料包」拿到当前地图的知识包目录，再导出运行时对象。",
            )
            return
        self.status.configure(text="正在从运行中游戏读取词缀/注册数据 …")

        def work(ticket: GuiWorkerTicket) -> None:
            out = ""
            try:
                from .live_object_dump import dump_live_objects

                out = tmp_extract_dir("runtime-objects", "运行时对象包")
                result = dump_live_objects(out)

                def finish() -> None:
                    notes = "\n".join(result.notes)
                    if not result.completed:
                        self.status.configure(text="运行时证据导出未完成")
                        messagebox.showwarning(
                            "导出未完成",
                            (notes + "\n\n" if notes else "")
                            + "请确认 Warcraft III 正在运行且已进入对局，再重试。",
                        )
                        return
                    if not (
                        result.objects
                        or result.registered_records
                        or result.affix_records
                    ):
                        self.status.configure(text="未捕获运行时证据")
                        messagebox.showwarning(
                            "未捕获运行时证据",
                            f"空证据包与诊断已保留: {out}\n\n"
                            + (notes + "\n\n" if notes else "")
                            + "请确认已进入目标对局，再重试。",
                        )
                        return
                    self.status.configure(text=f"运行时证据包已导出: {out}")
                    messagebox.showinfo(
                        "导出完成",
                        f"运行时证据包: {out}\n"
                        f"对象块 {result.records}，不同 ID {result.objects}；"
                        f"注册记录 {result.registered_records}，词缀记录 {result.affix_records}"
                        + ("\n\n" + notes if notes else ""),
                    )

                _ = self._post_gui_worker(ticket, finish)
            except Exception as exc:  # BROAD_EXCEPT_OK - GUI worker boundary.
                error_text = format_user_exception(exc, paths=(out,))
                _ = self._post_gui_worker(
                    ticket,
                    lambda message=error_text: self._show_export_error(message),
                )

        _ = self._start_gui_worker("dump-runtime", work, replace=True)


def _last_pack_memo_path() -> str:
    try:
        from .cache_root import gamexray_cache_root

        return str(gamexray_cache_root() / "gui-last-pack.txt")
    except OSError:
        return ""


def load_last_pack_dir() -> str:
    """读取最近导出的目录，供显式打开最近资料包使用。fail-open。"""
    path = _last_pack_memo_path()
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError, UnicodeError:
        return ""


def save_last_pack_dir(out: str) -> None:
    path = _last_pack_memo_path()
    if not path:
        return
    try:
        from pathlib import Path

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(out, encoding="utf-8")
    except OSError, UnicodeError:
        pass  # fail-open: 记忆失败不影响导出
