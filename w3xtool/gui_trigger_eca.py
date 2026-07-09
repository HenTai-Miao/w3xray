"""GUI browser for parsed WTG event/condition/action trees."""

from __future__ import annotations

from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from .deferred_paned import add_deferred_pane, build_deferred_horizontal_paned
from .search import compile_query
from .theme import BG, BORDER, CARD, FONT, MONO_FONT, PANEL, SUBTLE, TEXT, card_style, entry_style
from .wtg_eca import function_type_label, parameter_type_label
from .wtg_models import TriggerEcaFunction, TriggerEcaParameter


@dataclass(frozen=True, slots=True)
class _EcaNode:
    iid: str
    function: TriggerEcaFunction
    children: tuple[_EcaNode, ...]


@dataclass(frozen=True, slots=True)
class _TriggerGroup:
    iid: str
    name: str
    children: tuple[_EcaNode, ...]


class TriggerEcaViewMixin:
    """Build and refresh the read-only GUI trigger workbench."""

    def _build_trigger_eca_tab(self, parent) -> None:
        top = ctk.CTkFrame(parent, fg_color=BG)
        top.pack(fill="x", padx=2, pady=(8, 6))
        self.trigger_eca_search = tk.StringVar()
        entry = ctk.CTkEntry(
            top, textvariable=self.trigger_eca_search, height=38, font=(FONT, 13),
            justify="center", placeholder_text="回车搜索：触发器 / 函数 / 参数",
            **entry_style(),
        )
        entry.pack(fill="x")
        entry.bind("<Return>", lambda *_: self._search_trigger_eca())
        self._attach_ctx_menu(entry, paste=True)
        self.trigger_eca_status = ctk.CTkLabel(
            parent, text="没有可显示的 GUI 触发器", font=(FONT, 12),
            text_color=SUBTLE, anchor="w", justify="left", wraplength=1100,
        )
        self.trigger_eca_status.pack(fill="x", padx=6, pady=(0, 6))

        paned = build_deferred_horizontal_paned(parent)
        paned.pack(fill="both", expand=True, padx=4, pady=(0, 8))
        left = ctk.CTkFrame(paned, **card_style())
        left_inner = tk.Frame(left, bg=CARD)
        left_inner.pack(fill="both", expand=True, padx=8, pady=8)
        self.trigger_eca_tree = ttk.Treeview(left_inner, show="tree", selectmode="browse")
        self.trigger_eca_tree.column("#0", width=430, minwidth=240, stretch=True, anchor="w")
        tree_vsb = ttk.Scrollbar(left_inner, orient="vertical", command=self.trigger_eca_tree.yview)
        tree_hsb = ttk.Scrollbar(left_inner, orient="horizontal", command=self.trigger_eca_tree.xview)
        self.trigger_eca_tree.configure(yscrollcommand=tree_vsb.set, xscrollcommand=tree_hsb.set)
        tree_vsb.pack(side="right", fill="y")
        tree_hsb.pack(side="bottom", fill="x")
        self.trigger_eca_tree.pack(side="left", fill="both", expand=True)
        self.trigger_eca_tree.bind("<<TreeviewSelect>>", self._show_trigger_eca_detail)
        self.trigger_eca_tree.bind("<<TreeviewOpen>>", self._on_trigger_eca_open)
        self._attach_tree_copy(self.trigger_eca_tree)
        add_deferred_pane(paned, left, minsize=320, stretch="always")

        right = ctk.CTkFrame(paned, **card_style())
        self.trigger_eca_detail = ctk.CTkTextbox(
            right, font=(MONO_FONT, 12), fg_color=PANEL, text_color=TEXT,
            border_width=1, border_color=BORDER, wrap="word",
        )
        self.trigger_eca_detail.pack(fill="both", expand=True, padx=8, pady=8)
        self.trigger_eca_detail.configure(state="disabled")
        self._attach_ctx_menu(self.trigger_eca_detail, copy_all=True)
        add_deferred_pane(paned, right, minsize=300, stretch="never")
        self._trigger_eca_groups: tuple[_TriggerGroup, ...] = ()
        self._trigger_eca_nodes: dict[str, _EcaNode] = {}
        self._trigger_eca_map = None

    def _refresh_trigger_eca(self) -> None:
        summary = getattr(self.map_data, "trigger_summary", None) if self.map_data else None
        functions = tuple(getattr(summary, "eca_functions", ()) or ())
        same_map = self.map_data is self._trigger_eca_map
        selected = self.trigger_eca_tree.selection()
        selected_iid = selected[0] if same_map and selected else ""
        query = self.trigger_eca_search.get().strip() if same_map else ""
        self._trigger_eca_map = self.map_data
        self.trigger_eca_search.set(query)
        self._trigger_eca_groups = _group_functions(functions)
        self._rebuild_trigger_eca_tree(query, selected_iid)
        self._set_trigger_eca_status(summary, functions)

    def _search_trigger_eca(self) -> None:
        selected = self.trigger_eca_tree.selection()
        selected_iid = selected[0] if selected else ""
        self._rebuild_trigger_eca_tree(self.trigger_eca_search.get().strip(), selected_iid)

    def _rebuild_trigger_eca_tree(self, query: str, selected_iid: str) -> None:
        tree = self.trigger_eca_tree
        tree.delete(*tree.get_children())
        self._trigger_eca_nodes = {}
        compiled = compile_query(query)
        for group in self._trigger_eca_groups:
            group_match = not query or compiled.score(group.name) is not None
            visible = tuple(node for node in group.children if group_match or _node_matches(node, compiled))
            if not visible:
                continue
            tree.insert("", "end", iid=group.iid, text=group.name, open=True)
            for node in visible:
                if query and not group_match:
                    self._insert_filtered_node(group.iid, node, compiled)
                else:
                    self._insert_trigger_node(group.iid, node, eager_children=True)
        if selected_iid and tree.exists(selected_iid):
            tree.selection_set(selected_iid)
            tree.focus(selected_iid)
            self._show_trigger_eca_detail()
        else:
            self._clear_trigger_eca_detail()

    def _insert_trigger_node(self, parent: str, node: _EcaNode, *, eager_children: bool) -> None:
        self.trigger_eca_tree.insert(parent, "end", iid=node.iid, text=node.function.name, open=eager_children)
        self._trigger_eca_nodes[node.iid] = node
        if eager_children:
            for child in node.children:
                self._insert_trigger_node(node.iid, child, eager_children=False)
        elif node.children:
            self.trigger_eca_tree.insert(node.iid, "end", iid=f"{node.iid}:lazy", text="")

    def _insert_filtered_node(self, parent: str, node: _EcaNode, compiled) -> None:
        self.trigger_eca_tree.insert(parent, "end", iid=node.iid, text=node.function.name, open=True)
        self._trigger_eca_nodes[node.iid] = node
        for child in node.children:
            if _node_matches(child, compiled):
                self._insert_filtered_node(node.iid, child, compiled)

    def _on_trigger_eca_open(self, _event=None) -> None:
        iid = self.trigger_eca_tree.focus()
        node = self._trigger_eca_nodes.get(iid)
        if node is None or not self.trigger_eca_tree.exists(f"{iid}:lazy"):
            return
        self.trigger_eca_tree.delete(f"{iid}:lazy")
        for child in node.children:
            self._insert_trigger_node(iid, child, eager_children=False)

    def _show_trigger_eca_detail(self, _event=None) -> None:
        selected = self.trigger_eca_tree.selection()
        node = self._trigger_eca_nodes.get(selected[0]) if selected else None
        if node is None:
            self._clear_trigger_eca_detail()
            return
        self._set_trigger_eca_detail(_format_function_detail(node.function))

    def _set_trigger_eca_detail(self, text: str) -> None:
        self.trigger_eca_detail.configure(state="normal")
        self.trigger_eca_detail.delete("1.0", "end")
        self.trigger_eca_detail.insert("end", text)
        self.trigger_eca_detail.configure(state="disabled")

    def _clear_trigger_eca_detail(self) -> None:
        self._set_trigger_eca_detail("")

    def _set_trigger_eca_status(self, summary, functions: tuple[TriggerEcaFunction, ...]) -> None:
        parts = [f"已展开 {_count_functions(functions)} 个函数"] if functions else ["没有可显示的 GUI 触发器"]
        for item in tuple(getattr(summary, "missing_schema_functions", ()) or ()):
            parts.append(f"缺 TriggerData：{item.trigger_name}/{item.function_name} @ 0x{item.offset:x}")
        for failure in tuple(getattr(summary, "parse_failures", ()) or ()):
            parts.append(f"解析失败：{failure.trigger_name}/{failure.function_name} @ 0x{failure.offset:x}：{failure.reason}")
        self.trigger_eca_status.configure(text="  |  ".join(parts))


def _group_functions(functions: tuple[TriggerEcaFunction, ...]) -> tuple[_TriggerGroup, ...]:
    order: list[str] = []
    grouped: dict[str, list[_EcaNode]] = {}
    for index, function in enumerate(functions):
        name = function.trigger_name or "(未命名触发器)"
        if name not in grouped:
            order.append(name)
            grouped[name] = []
        grouped[name].append(_build_node(function, f"eca:{index}"))
    return tuple(_TriggerGroup(f"trigger:{index}", name, tuple(grouped[name])) for index, name in enumerate(order))


def _build_node(function: TriggerEcaFunction, iid: str) -> _EcaNode:
    nested = tuple(
        node
        for index, parameter in enumerate(function.parameters)
        for node in _build_parameter_nodes(parameter, f"{iid}:p{index}")
    )
    children = tuple(_build_node(child, f"{iid}:c{index}") for index, child in enumerate(function.children))
    return _EcaNode(iid, function, nested + children)


def _build_parameter_nodes(parameter: TriggerEcaParameter, iid: str) -> tuple[_EcaNode, ...]:
    nodes = () if parameter.nested_function is None else (_build_node(parameter.nested_function, f"{iid}:f"),)
    if parameter.array_indexer is None:
        return nodes
    return nodes + _build_parameter_nodes(parameter.array_indexer, f"{iid}:a")


def _node_matches(node: _EcaNode, compiled) -> bool:
    return (
        compiled.score(_function_search_text(node.function)) is not None
        or any(_node_matches(child, compiled) for child in node.children)
    )


def _function_search_text(function: TriggerEcaFunction) -> str:
    parameters = " ".join(_parameter_search_text(parameter) for parameter in function.parameters)
    return f"{function.trigger_name} {function.name} {function_type_label(function.function_type)} {parameters}"


def _parameter_search_text(parameter: TriggerEcaParameter) -> str:
    own = f"{parameter.expected_type} {parameter.value}"
    if parameter.array_indexer is None:
        return own
    return f"{own} {_parameter_search_text(parameter.array_indexer)}"


def _format_function_detail(function: TriggerEcaFunction) -> str:
    lines = [
        f"函数：{function.name}", f"触发器：{function.trigger_name}",
        f"类型：{function_type_label(function.function_type)}", f"启用：{'是' if function.is_enabled else '否'}",
        f"层级：{function.depth}", f"分支：{function.branch}", f"源偏移：0x{function.source_offset:x}", "", "参数：",
    ]
    if not function.parameters:
        lines.append("(无)")
    for index, parameter in enumerate(function.parameters, 1):
        _append_parameter_detail(lines, str(index), parameter)
    return "\n".join(lines) + "\n"


def _append_parameter_detail(lines: list[str], label: str, parameter: TriggerEcaParameter) -> None:
    expected = f" / {parameter.expected_type}" if parameter.expected_type else ""
    lines.append(
        f"{label}. {parameter_type_label(parameter.parameter_type)}{expected}: "
        f"{parameter.value} @ 0x{parameter.source_offset:x}"
    )
    if parameter.array_indexer is not None:
        _append_parameter_detail(lines, f"{label}.索引", parameter.array_indexer)


def _count_functions(functions: tuple[TriggerEcaFunction, ...]) -> int:
    return sum(_count_function(function) for function in functions)


def _count_function(function: TriggerEcaFunction) -> int:
    return 1 + sum(_count_function(child) for child in _function_children(function))


def _function_children(function: TriggerEcaFunction) -> tuple[TriggerEcaFunction, ...]:
    nested = tuple(child for parameter in function.parameters for child in _parameter_functions(parameter))
    return nested + function.children


def _parameter_functions(parameter: TriggerEcaParameter) -> tuple[TriggerEcaFunction, ...]:
    functions = () if parameter.nested_function is None else (parameter.nested_function,)
    if parameter.array_indexer is None:
        return functions
    return functions + _parameter_functions(parameter.array_indexer)
