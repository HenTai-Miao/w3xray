"""Read-only navigation over map and validated global icon gaps."""
# pyright: reportAttributeAccessIssue=false, reportUninitializedInstanceVariable=false

from __future__ import annotations

from .gui_icon_gap_layout import IconGapLayoutMixin
from .icon_evidence_presentation import format_icon_gap_evidence
from .icon_evidence_query import (
    IconGapFilter,
    IconGapViewRow,
    filter_icon_gap_rows,
    global_icon_gap_rows,
    map_icon_gap_rows,
)


class IconGapGuiMixin(IconGapLayoutMixin):
    """Refresh and navigate strict evidence without resolving or adopting hints."""

    def _init_icon_gap_gui(self) -> None:
        self._current_icon_gap_rows: tuple[IconGapViewRow, ...] = ()
        self._batch_icon_gap_rows: tuple[IconGapViewRow, ...] = ()
        self._batch_icon_evidence = None

    def _refresh_current_icon_gaps(self) -> None:
        md = self.map_data
        self._current_icon_gap_rows = (
            () if md is None else map_icon_gap_rows(md.icon_evidence)
        )
        if self._batch_icon_evidence is not None:
            self._batch_icon_gap_rows = global_icon_gap_rows(
                self._batch_icon_evidence, self._current_map_identity()
            )
        self._refresh_icon_gaps()

    def _refresh_icon_gaps(self) -> None:
        rows = (
            self._batch_icon_gap_rows
            if self.icon_gap_scope.get() == "批量结果"
            else self._current_icon_gap_rows
        )
        self._set_icon_gap_filter_values(rows)
        candidates = self.icon_gap_mode.get() == "候选（未采用）"
        visible = filter_icon_gap_rows(
            rows,
            IconGapFilter(
                self.icon_gap_search.get(),
                self.icon_gap_reason.get(),
                self.icon_gap_category.get(),
                self.icon_gap_archive.get(),
                candidates,
            ),
        )
        self.icon_gap_tree.delete(*self.icon_gap_tree.get_children())
        self.icon_gap_rows = {}
        for row in visible:
            self.icon_gap_rows[row.row_id] = row
            self.icon_gap_tree.insert(
                "",
                "end",
                iid=row.row_id,
                values=(
                    row.reason,
                    row.category,
                    row.rawcode,
                    row.path,
                    row.archive_status,
                    row.reference_count,
                ),
                tags=("candidate" if row.candidate else "gap",),
            )
        self.icon_gap_tree.tag_configure("candidate", foreground="#a06b00")
        self.icon_gap_status.configure(
            text=f"显示 {len(visible)} 条严格{'候选（未采用）' if candidates else '未解析'}证据"
        )
        self._show_icon_gap_evidence()

    def _show_icon_gap_evidence(self, _event=None) -> None:
        selected = self.icon_gap_tree.selection()
        row = self.icon_gap_rows.get(selected[0]) if selected else None
        self.icon_gap_detail.configure(state="normal")
        self.icon_gap_detail.delete("1.0", "end")
        if row is not None:
            self.icon_gap_detail.insert("end", format_icon_gap_evidence(row))
        self.icon_gap_detail.configure(state="disabled")
        self.icon_gap_open_button.configure(
            state="normal" if self._can_open_icon_gap(row) else "disabled"
        )

    def _open_icon_gap_object(self) -> None:
        selected = self.icon_gap_tree.selection()
        row = self.icon_gap_rows.get(selected[0]) if selected else None
        if not self._can_open_icon_gap(row):
            return
        assert row is not None
        assert row.object_identity is not None
        assert self.map_data is not None
        obj = self.map_data.obj_identity_index.get(row.object_identity)
        if obj is None:
            return
        self.tabs.set("对象编辑器")
        self._on_object_category(obj.category)
        self._show_detail(obj)

    def _set_batch_icon_gaps(self, rows: tuple[IconGapViewRow, ...] | None) -> None:
        self._batch_icon_evidence = None
        self._batch_icon_gap_rows = () if rows is None else rows
        self._refresh_icon_gaps()

    def _set_global_icon_evidence(self, evidence) -> None:
        self._batch_icon_evidence = evidence
        self._batch_icon_gap_rows = global_icon_gap_rows(
            evidence, self._current_map_identity()
        )
        self._refresh_icon_gaps()

    def _set_icon_gap_filter_values(self, rows: tuple[IconGapViewRow, ...]) -> None:
        self._set_filter_values(self.icon_gap_reason, (row.reason for row in rows))
        self._set_filter_values(self.icon_gap_category, (row.category for row in rows))
        self._set_filter_values(
            self.icon_gap_archive, (row.archive_status for row in rows)
        )

    def _set_filter_values(self, control, values) -> None:
        options = ("全部", *sorted({value for value in values if value}))
        control.configure(values=options)
        if control.get() not in options:
            control.set("全部")

    def _can_open_icon_gap(self, row: IconGapViewRow | None) -> bool:
        current_map = self._current_map_identity()
        return bool(
            row is not None
            and row.object_identity is not None
            and current_map is not None
            and (row.map_path, row.map_sha256) == current_map
        )

    def _current_map_identity(self) -> tuple[str, str] | None:
        md = self.map_data
        ledger = None if md is None else md.extraction_ledger
        return None if ledger is None else (ledger.source_path, ledger.source_sha256)
