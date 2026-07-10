"""Author plaintext and real-save actions exposed through the GUI data menu."""

from __future__ import annotations

import os
import threading
from tkinter import filedialog, messagebox

from .api import tmp_extract_dir
from .author_plaintext_bundle import MANIFEST_NAME
from .knowledge_io import write_text
from .real_save_files import analyze_real_save_path, format_real_save_report_tsv


class ExternalDataToolsMixin:
    """Manage author plaintext selection and read-only save analysis actions."""

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

    def on_analyze_real_save_file(self) -> None:
        if not self._need_map():
            return
        path = filedialog.askopenfilename(title="选择真实存档文件", filetypes=[("所有文件", "*.*")])
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
        out = tmp_extract_dir(md.name, "真实存档分析", clean=True)
        self.status.configure(text="正在只读分析真实存档 …")

        def work() -> None:
            try:
                report = analyze_real_save_path(path, md)
                count = write_text(out, "真实存档分析.tsv", format_real_save_report_tsv(report))
                if report.warnings:
                    count += write_text(out, "真实存档警告.txt", "\n".join(report.warnings) + "\n")
                self.after(0, lambda: self._open_dir(out, count, "存档分析文件"))
            except Exception as exc:  # noqa: BROAD_EXCEPT_OK - GUI worker reports bounded analysis failures.
                message = str(exc)
                self.after(0, lambda: messagebox.showerror("存档分析失败", message))

        threading.Thread(target=work, daemon=True).start()
