"""GUI export actions kept out of the main application shell."""

from __future__ import annotations

import os
from dataclasses import dataclass
from tkinter import messagebox
from typing import assert_never

from .api import export_all_files, export_loaded_map_files, tmp_extract_dir
from .gui_worker_registry import GuiWorkerTicket
from .knowledge_io import safe_filename, write_text
from .knowledge_pack import format_box_id_text, write_knowledge_pack_report
from .knowledge_results import KnowledgeWriteReport, KnowledgeWriteStatus
from .knowledge_script_exports import write_script_exports
from .presentation_safety import format_user_exception
from .script_text_export import build_readable_script_exports


@dataclass(frozen=True, slots=True)
class PackExportPresentation:
    title: str
    status_text: str
    message: str
    is_error: bool


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
    def _need_map(self):
        if not self.map_data:
            messagebox.showinfo("提示", "请先打开一张地图")
            return False
        return True

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

    def on_export_all(self):
        if not self._need_map():
            return
        md = self.map_data
        campaign_path = self._campaign_path
        path = campaign_path or md.path
        is_campaign_child = campaign_path is not None and md.path != campaign_path
        self.status.configure(text="正在解包全部文件到临时目录 …")
        self.update_idletasks()

        def work(ticket: GuiWorkerTicket) -> None:
            try:
                if is_campaign_child:
                    out = export_loaded_map_files(
                        md,
                        external_listfile_path=self.external_listfile_path,
                    )
                else:
                    out = export_all_files(
                        path,
                        external_listfile_path=self.external_listfile_path,
                    )
                n = sum(len(fs) for _, _, fs in os.walk(out))
                _ = self._post_gui_worker(
                    ticket,
                    lambda: self._open_dir(out, n, "文件"),
                )
            except Exception as exc:  # noqa: BROAD_EXCEPT_OK - GUI worker boundary reports export failures.
                error_text = format_user_exception(exc, paths=(path, md.path))
                _ = self._post_gui_worker(
                    ticket,
                    lambda message=error_text: messagebox.showerror(
                        "导出失败", message
                    ),
                )

        _ = self._start_gui_worker("export-all", work, replace=True)

    def on_export_scripts(self):
        if not self._need_map():
            return
        md = self.map_data
        out = tmp_extract_dir(md.name, "脚本", clean=True)
        scripts = build_readable_script_exports(md)
        self.status.configure(text="正在导出脚本 …")

        def work(ticket: GuiWorkerTicket) -> None:
            try:
                n = write_script_exports(scripts, out)
                _ = self._post_gui_worker(
                    ticket,
                    lambda: self._open_dir(out, n, "脚本"),
                )
            except Exception as exc:  # noqa: BROAD_EXCEPT_OK - GUI worker boundary reports export failures.
                error_text = format_user_exception(exc, paths=(out, md.path))
                _ = self._post_gui_worker(
                    ticket,
                    lambda message=error_text: messagebox.showerror(
                        "导出失败", message
                    ),
                )

        _ = self._start_gui_worker("export-scripts", work, replace=True)

    def on_export_ids(self):
        if not self._need_map():
            return
        md = self.map_data
        out = tmp_extract_dir(md.name, "ID列表", clean=True)
        objects = {c: list(v) for c, v in md.objects.items()}
        self.status.configure(text="正在导出ID列表 …")

        def work(ticket: GuiWorkerTicket) -> None:
            try:
                n = 0
                for cat, objs in objects.items():
                    if ticket.cancellation.is_set():
                        return
                    name = f"{safe_filename(cat)}ID.txt"
                    n += write_text(out, name, format_box_id_text(objs, category=cat))
                _ = self._post_gui_worker(
                    ticket,
                    lambda: self._open_dir(out, n, "分类的ID列表"),
                )
            except Exception as exc:  # noqa: BROAD_EXCEPT_OK - GUI worker boundary reports export failures.
                error_text = format_user_exception(exc, paths=(out, md.path))
                _ = self._post_gui_worker(
                    ticket,
                    lambda message=error_text: messagebox.showerror(
                        "导出失败", message
                    ),
                )

        _ = self._start_gui_worker("export-ids", work, replace=True)

    def on_export_pack(self):
        if not self._need_map():
            return
        out = tmp_extract_dir(self.map_data.name, "资料包", clean=True)
        md = self.map_data
        self.status.configure(text="正在整理地图资料包 …")

        def work(ticket: GuiWorkerTicket) -> None:
            try:
                report = write_knowledge_pack_report(
                    md,
                    out,
                    game_data_path=self.game_data_path,
                )
                _ = self._post_gui_worker(
                    ticket,
                    lambda: self._show_pack_result(out, report),
                )
            except Exception as exc:  # noqa: BROAD_EXCEPT_OK - GUI worker boundary reports export failures.
                error_text = format_user_exception(exc, paths=(out, md.path))
                _ = self._post_gui_worker(
                    ticket,
                    lambda message=error_text: messagebox.showerror(
                        "导出失败", message
                    ),
                )

        _ = self._start_gui_worker("export-pack", work, replace=True)
