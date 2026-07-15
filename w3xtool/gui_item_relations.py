"""Searchable item acquisition and equipment-skill GUI workspace."""

from __future__ import annotations

from .gui_item_relation_layout import ItemRelationLayoutMixin
from .item_relation_models import ItemRelation, ItemRelationKind, RelationObject
from .item_relation_presentation import format_relation_evidence
from .item_relation_query import filter_item_relations
from .map_data import GameObject
from .theme import CARD, ROW_ALT


class ItemRelationGuiMixin(ItemRelationLayoutMixin):
    """Filter, inspect, and navigate immutable item relations."""

    def _refresh_item_relations(self) -> None:
        selected = self._selected_item_relation()
        selected_id = "" if selected is None else selected.relation_id
        tree = self.item_relation_tree
        tree.delete(*tree.get_children())
        self.item_relation_rows = {}
        md = self.map_data
        records = () if md is None else md.item_relations.records
        visible = filter_item_relations(
            records,
            self.item_relation_search.get(),
            self.item_relation_kind.get(),
            self.item_relation_confidence.get(),
        )
        for relation in visible:
            iid = relation.relation_id
            self.item_relation_rows[iid] = relation
            tag = "odd" if len(self.item_relation_rows) % 2 else "even"
            tree.insert(
                "", "end", iid=iid, values=_relation_values(relation), tags=(tag,)
            )
        tree.tag_configure("odd", background=ROW_ALT)
        tree.tag_configure("even", background=CARD)
        self.item_relation_status.configure(
            text=f"显示 {len(self.item_relation_rows)} / {len(records)} 条静态关系"
        )
        if selected_id in self.item_relation_rows:
            tree.selection_set(selected_id)
            tree.focus(selected_id)
            self._show_relation_evidence()
        else:
            self._show_relation_evidence()

    def _show_relation_evidence(self, _event=None) -> None:
        relation = self._selected_item_relation()
        self._set_relation_detail(
            "" if relation is None else format_relation_evidence(relation)
        )
        target_endpoint = None if relation is None else _target_endpoint(relation)
        target = self._resolve_relation_object(target_endpoint)
        source_endpoint = None if relation is None else _source_endpoint(relation)
        source = self._resolve_relation_object(source_endpoint)
        self.item_relation_target_button.configure(
            state="normal" if target is not None else "disabled",
            text=_open_button_label(target_endpoint, target=True),
        )
        self.item_relation_source_button.configure(
            state="normal" if source is not None else "disabled",
            text=_open_button_label(source_endpoint, target=False),
        )

    def _open_relation_target(self) -> None:
        relation = self._selected_item_relation()
        if relation is not None:
            self._open_relation_endpoint(_target_endpoint(relation))

    def _open_relation_source(self) -> None:
        relation = self._selected_item_relation()
        if relation is not None:
            self._open_relation_endpoint(_source_endpoint(relation))

    def _selected_item_relation(self) -> ItemRelation | None:
        selected = self.item_relation_tree.selection()
        return self.item_relation_rows.get(selected[0]) if selected else None

    def _resolve_relation_object(
        self,
        endpoint: RelationObject | None,
    ) -> GameObject | None:
        md = self.map_data
        if md is None or endpoint is None:
            return None
        candidate = md.obj_identity_index.get((endpoint.category, endpoint.object_id))
        if candidate is None:
            indexed = md.obj_index.get(endpoint.object_id)
            if indexed is not None and indexed.category == endpoint.category:
                candidate = indexed
        if candidate is None:
            candidate = next(
                (
                    obj
                    for obj in md.objects.get(endpoint.category, ())
                    if obj.obj_id == endpoint.object_id
                ),
                None,
            )
        return (
            candidate if candidate is not None and candidate.ext != "script" else None
        )

    def _open_relation_endpoint(self, endpoint: RelationObject | None) -> None:
        obj = self._resolve_relation_object(endpoint)
        if obj is None:
            return
        self.tabs.set("对象编辑器")
        if obj.category in self.col_results:
            self._on_object_category(obj.category)
        self._show_detail(obj)

    def _set_relation_detail(self, text: str) -> None:
        self.item_relation_detail.configure(state="normal")
        self.item_relation_detail.delete("1.0", "end")
        self.item_relation_detail.insert("end", text)
        self.item_relation_detail.configure(state="disabled")


def _source_endpoint(relation: ItemRelation) -> RelationObject | None:
    return relation.item if _is_skill_relation(relation) else relation.source


def _target_endpoint(relation: ItemRelation) -> RelationObject:
    if _is_skill_relation(relation) and relation.skill is not None:
        return relation.skill
    return relation.item


def _relation_values(relation: ItemRelation) -> tuple[str, ...]:
    target = _target_endpoint(relation)
    source = _source_endpoint(relation)
    context = " · ".join(
        value
        for value in (
            None if relation.chance is None else f"{relation.chance}%",
            None if relation.player is None else f"玩家 {relation.player}",
            None
            if relation.x is None or relation.y is None
            else f"({relation.x!r}, {relation.y!r})",
        )
        if value is not None
    )
    evidence = relation.evidence.source or relation.evidence.location
    return (
        relation.kind.value,
        _endpoint_label(target),
        "" if source is None else _endpoint_label(source),
        context,
        relation.confidence.value,
        relation.completeness.value,
        evidence,
    )


def _endpoint_label(endpoint: RelationObject) -> str:
    return (
        f"{endpoint.name}({endpoint.object_id})"
        if endpoint.name
        else endpoint.object_id
    )


def _is_skill_relation(relation: ItemRelation) -> bool:
    return relation.kind in {
        ItemRelationKind.ITEM_ABILITY,
        ItemRelationKind.COOLDOWN_ABILITY,
    }


def _open_button_label(
    endpoint: RelationObject | None,
    *,
    target: bool,
) -> str:
    if endpoint is None:
        return "打开目标" if target else "打开来源"
    if endpoint.category == "技能":
        return "打开技能"
    if endpoint.category == "物品":
        return "打开装备"
    return "打开目标" if target else "打开来源"
