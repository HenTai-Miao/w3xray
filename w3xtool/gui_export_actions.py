"""GUI export actions kept out of the main application shell."""

from __future__ import annotations

import os
import threading
from tkinter import messagebox

from .api import export_all_files, tmp_extract_dir
from .external_listfile import read_external_listfile
from .knowledge_pack import format_box_id_text, write_knowledge_pack
from .script_text_export import build_readable_script_exports


class ExportActionsMixin:
    def _need_map(self):
        if not self.map_data:
            messagebox.showinfo("提示", "请先打开一张地图")
            return False
        return True

    def _open_dir(self, out, n, kind):
        self.status.configure(text=f"已导出 {n} 个{kind}到临时目录 {out}")
        try:
            os.startfile(out)
        except (AttributeError, OSError):
            pass
        messagebox.showinfo("完成", f"已导出 {n} 个{kind}到临时目录：\n{out}\n（临时文件，可随时清理）")

    def on_export_all(self):
        if not self._need_map():
            return
        path = self._campaign_path or self.map_data.path
        self.status.configure(text="正在解包全部文件到临时目录 …")
        self.update_idletasks()

        def work():
            try:
                out = export_all_files(path, external_listfile_path=self.external_listfile_path)
                n = sum(len(fs) for _, _, fs in os.walk(out))
                self.after(0, lambda: self._open_dir(out, n, "文件"))
            except Exception as exc:  # noqa: BROAD_EXCEPT_OK - GUI worker boundary reports export failures.
                error_text = str(exc)
                self.after(0, lambda message=error_text: messagebox.showerror("导出失败", message))

        threading.Thread(target=work, daemon=True).start()

    def on_export_scripts(self):
        if not self._need_map():
            return
        out = tmp_extract_dir(self.map_data.name, "脚本", clean=True)
        scripts = build_readable_script_exports(self.map_data)
        self.status.configure(text="正在导出脚本 …")

        def work():
            try:
                n = 0
                for item in scripts:
                    path = os.path.join(out, os.path.basename(item.name))
                    with open(path, "w", encoding="utf-8") as handle:
                        handle.write(item.text)
                    n += 1
                self.after(0, lambda: self._open_dir(out, n, "脚本"))
            except Exception as exc:  # noqa: BROAD_EXCEPT_OK - GUI worker boundary reports export failures.
                error_text = str(exc)
                self.after(0, lambda message=error_text: messagebox.showerror("导出失败", message))

        threading.Thread(target=work, daemon=True).start()

    def on_export_ids(self):
        if not self._need_map():
            return
        out = tmp_extract_dir(self.map_data.name, "ID列表", clean=True)
        objects = {c: list(v) for c, v in self.map_data.objects.items()}
        self.status.configure(text="正在导出ID列表 …")

        def work():
            try:
                n = 0
                for cat, objs in objects.items():
                    with open(os.path.join(out, f"{cat}ID.txt"), "w", encoding="utf-8") as handle:
                        handle.write(format_box_id_text(objs))
                    n += 1
                self.after(0, lambda: self._open_dir(out, n, "分类的ID列表"))
            except Exception as exc:  # noqa: BROAD_EXCEPT_OK - GUI worker boundary reports export failures.
                error_text = str(exc)
                self.after(0, lambda message=error_text: messagebox.showerror("导出失败", message))

        threading.Thread(target=work, daemon=True).start()

    def on_export_pack(self):
        if not self._need_map():
            return
        out = tmp_extract_dir(self.map_data.name, "资料包", clean=True)
        md = self.map_data
        self.status.configure(text="正在整理地图资料包 …")

        def work():
            try:
                n = write_knowledge_pack(
                    md,
                    out,
                    external_names=read_external_listfile(self.external_listfile_path),
                    game_data_path=self.game_data_path,
                )
                self.after(0, lambda: self._open_dir(out, n, "资料包文件"))
            except Exception as exc:  # noqa: BROAD_EXCEPT_OK - GUI worker boundary reports export failures.
                error_text = str(exc)
                self.after(0, lambda message=error_text: messagebox.showerror("导出失败", message))

        threading.Thread(target=work, daemon=True).start()
