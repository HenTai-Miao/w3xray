"""Object gallery selection and detail panel rendering."""

from __future__ import annotations

from .object_gallery import render_object_gallery


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
        self.detail_icon_image = self._get_photo(getattr(obj, "icon", "")) or self.detail_blank_icon
        self.detail_icon.configure(image=self.detail_icon_image, text="")
        self.detail_title.configure(text=obj.name)
        self.detail_sub.configure(text=f"{obj.category}  ·  ID {obj.obj_id}  ·  基础 {obj.base_id}"
                                  + ("  ·  自定义" if obj.is_custom else "  ·  原始"))
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("end", f"ID：{obj.obj_id}\n10进制：{obj.decimal}\n名字：{obj.name}\n\n")
        if not obj.fields:
            self.detail.insert("end", "（无修改字段）")
        for label, value in obj.fields:
            self.detail.insert("end", f"{label}: {value}\n")
        self._insert_references(obj)
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
                self.detail.insert("end", f"{_format_ref(ref_id, ref_name)}  ·  {label}\n")


def _format_ref(code, name) -> str:
    return f"{name}({code})" if name else code
