"""Object gallery selection and detail panel rendering."""
# pyright: reportAttributeAccessIssue=false, reportUninitializedInstanceVariable=false

from __future__ import annotations

from .object_detail_presentation import (
    format_complete_text_section,
    format_object_fields,
    format_object_relation_sections,
    format_object_summary,
    object_detail_title,
)
from .object_gallery import render_object_gallery
from .icon_evidence_presentation import format_object_icon_evidence_section


class ObjectDetailMixin:
    """Keep object selection and detail rendering out of the app shell."""

    def _on_object_category(self, category: str) -> None:
        self.active_object_category = category
        self._render_object_cards()

    def _render_object_cards(self) -> None:
        if not hasattr(self, "object_gallery"):
            return
        render_object_gallery(
            gallery=self.object_gallery,
            active_category=self.active_object_category,
            results_by_category=self.col_results,
            show_detail=self._show_detail,
            get_icon=self._get_tree_photo,
        )

    def _on_col_select(self, category: str) -> None:
        tree = self.col_trees[category]
        current = tree.focus() or (tree.selection()[0] if tree.selection() else "")
        if not current:
            return
        results = self.col_results.get(category, [])
        index = int(current)
        if index >= len(results):
            return
        self._show_detail(results[index])

    def _show_detail(self, obj) -> None:
        self._selected_detail_object = obj
        self._render_selected_object_detail()

    def _render_selected_object_detail(self) -> None:
        obj = getattr(self, "_selected_detail_object", None)
        if obj is None:
            return
        self.detail_icon_image = (
            self._get_photo(getattr(obj, "icon", "")) or self.detail_blank_icon
        )
        self.detail_icon.configure(image=self.detail_icon_image, text="")
        self.detail_title.configure(text=object_detail_title(obj))
        self.detail_sub.configure(
            text=f"{obj.category}  ·  ID {obj.obj_id}  ·  基础 {obj.base_id}"
            + ("  ·  自定义" if obj.is_custom else "  ·  原始")
        )
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("end", format_object_summary(obj))
        md = self.map_data
        if md is not None:
            self.detail.insert(
                "end", format_complete_text_section(md, obj, self.object_text_view)
            )
            self.detail.insert("end", format_object_icon_evidence_section(md, obj))
        self.detail.insert("end", format_object_fields(obj))
        self._insert_references(obj)
        if md is not None:
            self.detail.insert("end", format_object_relation_sections(md, obj))
        self.detail.configure(state="disabled")

    def _insert_references(self, obj) -> None:
        md = self.map_data
        if md is None:
            return
        refs = (md.references or {}).get(obj.obj_id) or []
        if refs:
            self.detail.insert("end", "\n── 引用（→ 此对象用到的对象）──\n")
            for label, resolved in refs:
                items = "，".join(_format_ref(code, name) for code, name in resolved)
                self.detail.insert("end", f"{label}: {items}\n")
        back_refs = (md.referenced_by or {}).get(obj.obj_id) or []
        if back_refs:
            self.detail.insert("end", "\n── 被引用（← 谁用到此对象）──\n")
            seen = set()
            for ref_id, ref_name, label in back_refs:
                key = (ref_id, label)
                if key in seen:
                    continue
                seen.add(key)
                self.detail.insert(
                    "end", f"{_format_ref(ref_id, ref_name)}  ·  {label}\n"
                )


def _format_ref(code, name) -> str:
    return f"{name}({code})" if name else code
