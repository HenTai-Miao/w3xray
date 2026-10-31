"""Refresh logic for command, recipe, placement, and info tabs."""

from __future__ import annotations

from collections import Counter
from tkinter import font as tkfont, ttk
from typing import TYPE_CHECKING

from .base_catalog import base_name_for
from .map_info import format_map_info
from .placement_identity import PlacementIdentity, PlacementObjectIndex
from .search import compile_query
from .static_numbers import format_number
from .theme import CARD, FONT, ROW_ALT

if TYPE_CHECKING:
    import customtkinter as ctk
    from .map_data import MapData
    from .script_scan import ChatCommand, Recipe


class DataRefreshMixin:
    """Populate the read-only data tabs from the current map."""

    # 宿主 (App) 组合时注入的控件与状态 — 类级注解仅作静态声明, 无运行时值
    if TYPE_CHECKING:
        commands: list[ChatCommand]  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        map_data: MapData | None  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        info_box: ctk.CTkTextbox  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        cmd_hint: ctk.CTkLabel  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        cmd_search: ctk.StringVar  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        cmd_tree: ttk.Treeview  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        rec_hint: ctk.CTkLabel  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        rec_search: ctk.StringVar  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        rec_tree: ttk.Treeview  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        pre_hint: ctk.CTkLabel  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        pre_search: ctk.StringVar  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        orphan_hint: ctk.CTkLabel  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        orphan_search: ctk.StringVar  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        orphan_tree: ttk.Treeview  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        unit_title: ctk.CTkLabel  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        unit_tree: ttk.Treeview  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        doodad_title: ctk.CTkLabel  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        doodad_tree: ttk.Treeview  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        recipes: list[Recipe]  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入

    def _refresh_orphans(self) -> None:
        if not hasattr(self, "orphan_tree"):
            return
        self.orphan_tree.delete(*self.orphan_tree.get_children())
        orphans = getattr(self.map_data, "orphans", []) if self.map_data else []
        query = self.orphan_search.get().strip()
        compiled = compile_query(query)
        shown = 0
        for orphan in orphans:
            blob = f"{orphan.category} {orphan.obj_id} {orphan.name}"
            if query and compiled.score(blob) is None:
                continue
            self.orphan_tree.insert(
                "",
                "end",
                values=(orphan.category, orphan.obj_id, orphan.name),
                tags=("odd" if shown % 2 else "even",),
            )
            shown += 1
        self.orphan_tree.tag_configure("odd", background=ROW_ALT)
        self.orphan_tree.tag_configure("even", background=CARD)
        self._set_orphan_hint(total=len(orphans), shown=shown)

    def _set_orphan_hint(self, *, total: int, shown: int) -> None:
        low = bool(getattr(self.map_data, "ref_low_coverage", False))
        if total and low:
            self.orphan_hint.configure(
                text=f"孤立自定义对象：{shown}/{total} —— ⚠ 此图引用覆盖低（疑为 SLK 优化图，"
                "单位→技能等引用在未解析的 .slk 里），下列多为误报，仅供参考"
            )
        elif total:
            self.orphan_hint.configure(
                text=f"孤立自定义对象：{shown}/{total} —— 定义了但没被任何对象/脚本/预放置引用"
                "（只读报告，不会改图；可能是作者留下的废弃对象）"
            )
        else:
            self.orphan_hint.configure(
                text="未发现孤立自定义对象（每个自定义对象都被引用，或此图无自定义对象数据）"
            )

    def _refresh_info(self) -> None:
        self.info_box.configure(state="normal")
        self.info_box.delete("1.0", "end")
        self.info_box.insert("end", format_map_info(self.map_data))
        self.info_box.configure(state="disabled")

    def _refresh_preplaced(self) -> None:
        if not self.map_data:
            return
        query = self.pre_search.get().strip()
        compiled = compile_query(query)
        units = getattr(self.map_data, "units", []) or []
        doodads = getattr(self.map_data, "doodads", []) or []
        index = PlacementObjectIndex(self.map_data)
        shown_units = self._refresh_unit_rows(units, query, compiled, index)
        shown_doodads = self._refresh_doodad_rows(doodads, query, compiled, index)
        self.unit_title.configure(text=f"预放置单位  ({shown_units})")
        self.doodad_title.configure(text=f"装饰物 / 可破坏物  ({shown_doodads})")
        if units or doodads:
            self.pre_hint.configure(
                text=f"预放置：{len(units)} 单位 · {len(doodads)} 装饰物/可破坏物"
                "（坐标为地图世界坐标；生命=默认表示用对象定义里的满血）"
            )
        else:
            self.pre_hint.configure(
                text="此图无预放置数据（war3mapUnits.doo / war3map.doo 缺失或为空）"
            )

    def _refresh_unit_rows(
        self, units, query: str, compiled, index: PlacementObjectIndex
    ) -> int:
        self.unit_tree.delete(*self.unit_tree.get_children())
        shown = 0
        for unit in units:
            identity = index.placement(unit.type_id, ("单位", "物品"))
            name = _placement_label(unit.type_id, identity)
            if (
                query
                and compiled.score(f"{name} {unit.type_id} {identity.english}") is None
            ):
                continue
            hp = "默认" if unit.hp < 0 else str(unit.hp)
            mana = "默认" if unit.mana < 0 else str(unit.mana)
            self.unit_tree.insert(
                "",
                "end",
                values=(
                    name,
                    unit.type_id,
                    unit.player,
                    f"{format_number(unit.x)}, {format_number(unit.y)}",
                    hp,
                    mana,
                    unit.hero_level,
                ),
                tags=("odd" if shown % 2 else "even",),
            )
            shown += 1
        self.unit_tree.tag_configure("odd", background=ROW_ALT)
        self.unit_tree.tag_configure("even", background=CARD)
        return shown

    def _refresh_doodad_rows(
        self, doodads, query: str, compiled, index: PlacementObjectIndex
    ) -> int:
        self.doodad_tree.delete(*self.doodad_tree.get_children())
        shown = 0
        for doodad in doodads:
            identity = index.placement(doodad.type_id, ("装饰物", "可破坏物"))
            name = _placement_label(doodad.type_id, identity)
            if (
                query
                and compiled.score(f"{name} {doodad.type_id} {identity.english}")
                is None
            ):
                continue
            drops = "  ".join(
                f"{self._item_name(item, index)}×{count}%"
                for item, count in doodad.drops
            )
            scale = format_number(doodad.scale[0]) if doodad.scale else "1"
            self.doodad_tree.insert(
                "",
                "end",
                values=(
                    name,
                    doodad.type_id,
                    f"{format_number(doodad.x)}, {format_number(doodad.y)}",
                    scale,
                    doodad.life,
                    drops,
                ),
                tags=("odd" if shown % 2 else "even",),
            )
            shown += 1
        self.doodad_tree.tag_configure("odd", background=ROW_ALT)
        self.doodad_tree.tag_configure("even", background=CARD)
        return shown

    def _item_name(self, code: str, index: PlacementObjectIndex | None = None) -> str:
        if index is None and self.map_data is not None:
            index = PlacementObjectIndex(self.map_data)
        name = (
            index.name("物品", code)
            if index is not None
            else base_name_for(code, category="物品")
        )
        return f"{name}({code})" if name and name != code else code

    _rec_font: tkfont.Font | None = None

    def _measure_font(self):
        if self._rec_font is None:
            self._rec_font = tkfont.Font(family=FONT, size=11)
        return self._rec_font

    def _autosize_tree(self, tree, col="#0", minw=120, pad=46) -> None:
        font = self._measure_font()
        widest = 0
        stack = list(tree.get_children(""))
        while stack:
            iid = stack.pop()
            widest = max(widest, font.measure(tree.item(iid, "text")))
            stack.extend(tree.get_children(iid))
        tree.column(col, width=max(minw, widest + pad), stretch=False)

    def _refresh_recipes(self) -> None:
        query = self.rec_search.get().strip()
        compiled = compile_query(query)
        self.rec_tree.delete(*self.rec_tree.get_children())
        shown = 0
        widest = 0
        font = self._measure_font()
        index = (
            PlacementObjectIndex(self.map_data) if self.map_data is not None else None
        )
        for recipe in self.recipes:
            result_name = self._item_name(recipe.result, index)
            ingredients = _ingredient_text(
                recipe.ingredients, lambda code: self._item_name(code, index)
            )
            if query and compiled.score(result_name + " " + ingredients) is None:
                continue
            self.rec_tree.insert(
                "",
                "end",
                values=(result_name, ingredients),
                tags=("odd" if shown % 2 else "even",),
            )
            widest = max(widest, font.measure(ingredients))
            shown += 1
        self.rec_tree.column("ingredients", width=max(620, widest + 28))
        self.rec_tree.tag_configure("odd", background=ROW_ALT)
        self.rec_tree.tag_configure("even", background=CARD)
        if self.recipes:
            self.rec_hint.configure(
                text=f"识别到 {len(self.recipes)} 个合成配方"
                "（尽力识别，标准 YDWE 写法准确；非标准写法可能漏检）"
            )
        else:
            self.rec_hint.configure(
                text="未识别到合成配方（此图可能无合成，或用了非标准写法）"
            )

    def _refresh_cmds(self) -> None:
        query = self.cmd_search.get().strip()
        compiled = compile_query(query)
        self.cmd_tree.delete(*self.cmd_tree.get_children())
        shown = 0
        for command in self.commands:
            if query and compiled.score(command.command + " " + command.hint) is None:
                continue
            self.cmd_tree.insert(
                "",
                "end",
                values=(
                    command.command or "(空)",
                    "精确" if command.exact else "前缀",
                    command.hint,
                ),
                tags=("odd" if shown % 2 else "even",),
            )
            shown += 1
        self.cmd_tree.tag_configure("odd", background=ROW_ALT)
        self.cmd_tree.tag_configure("even", background=CARD)
        font = self._measure_font()
        widest = max(
            (font.measure(command.hint) for command in self.commands), default=0
        )
        self.cmd_tree.column("hint", width=max(420, widest + 28))
        if self.commands:
            self.cmd_hint.configure(
                text=f"共 {len(self.commands)} 条聊天指令"
                f"（前缀=输入以该串开头即触发，常带参数；精确=完全匹配）"
            )
        else:
            self.cmd_hint.configure(
                text="未发现聊天指令（此图可能无聊天触发，或用了非标准写法）"
            )


def _placement_label(code: str, identity: PlacementIdentity) -> str:
    name = f"{identity.name}({code})" if identity.name != code else code
    return f"{name}〔{identity.diagnostic}〕" if identity.diagnostic else name


def _ingredient_text(ingredients, item_name) -> str:
    parts = []
    for code, count in Counter(ingredients).items():
        name = item_name(code)
        parts.append(f"{name}×{count}" if count > 1 else name)
    return "  +  ".join(parts)
