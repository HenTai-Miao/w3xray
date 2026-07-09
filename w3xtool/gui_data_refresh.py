"""Refresh logic for command, recipe, placement, and info tabs."""

from __future__ import annotations

from collections import Counter
from tkinter import font as tkfont

from .base_names import BASE_NAMES
from .map_info import format_map_info
from .search import compile_query
from .theme import CARD, FONT, ROW_ALT


class DataRefreshMixin:
    """Populate the read-only data tabs from the current map."""

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
            self.orphan_tree.insert("", "end", values=(orphan.category, orphan.obj_id, orphan.name),
                                    tags=("odd" if shown % 2 else "even",))
            shown += 1
        self.orphan_tree.tag_configure("odd", background=ROW_ALT)
        self.orphan_tree.tag_configure("even", background=CARD)
        self._set_orphan_hint(total=len(orphans), shown=shown)

    def _set_orphan_hint(self, *, total: int, shown: int) -> None:
        low = bool(getattr(self.map_data, "ref_low_coverage", False))
        if total and low:
            self.orphan_hint.configure(
                text=f"孤立自定义对象：{shown}/{total} —— ⚠ 此图引用覆盖低（疑为 SLK 优化图，"
                     "单位→技能等引用在未解析的 .slk 里），下列多为误报，仅供参考")
        elif total:
            self.orphan_hint.configure(
                text=f"孤立自定义对象：{shown}/{total} —— 定义了但没被任何对象/脚本/预放置引用"
                     "（只读报告，不会改图；可能是作者留下的废弃对象）")
        else:
            self.orphan_hint.configure(
                text="未发现孤立自定义对象（每个自定义对象都被引用，或此图无自定义对象数据）")

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
        shown_units = self._refresh_unit_rows(units, query, compiled)
        shown_doodads = self._refresh_doodad_rows(doodads, query, compiled)
        self.unit_title.configure(text=f"预放置单位  ({shown_units})")
        self.doodad_title.configure(text=f"装饰物 / 可破坏物  ({shown_doodads})")
        if units or doodads:
            self.pre_hint.configure(
                text=f"预放置：{len(units)} 单位 · {len(doodads)} 装饰物/可破坏物"
                     "（坐标为地图世界坐标；生命=默认表示用对象定义里的满血）")
        else:
            self.pre_hint.configure(text="此图无预放置数据（war3mapUnits.doo / war3map.doo 缺失或为空）")

    def _refresh_unit_rows(self, units, query: str, compiled) -> int:
        self.unit_tree.delete(*self.unit_tree.get_children())
        shown = 0
        for unit in units:
            name = self._item_name(unit.type_id)
            if query and compiled.score(name + " " + unit.type_id) is None:
                continue
            hp = "默认" if unit.hp < 0 else str(unit.hp)
            mana = "默认" if unit.mana < 0 else str(unit.mana)
            self.unit_tree.insert(
                "", "end",
                values=(name, unit.type_id, unit.player, f"{unit.x:.0f}, {unit.y:.0f}",
                        hp, mana, unit.hero_level),
                tags=("odd" if shown % 2 else "even",))
            shown += 1
        self.unit_tree.tag_configure("odd", background=ROW_ALT)
        self.unit_tree.tag_configure("even", background=CARD)
        return shown

    def _refresh_doodad_rows(self, doodads, query: str, compiled) -> int:
        self.doodad_tree.delete(*self.doodad_tree.get_children())
        shown = 0
        for doodad in doodads:
            name = self._item_name(doodad.type_id)
            if query and compiled.score(name + " " + doodad.type_id) is None:
                continue
            drops = "  ".join(f"{self._item_name(item)}×{count}%" for item, count in doodad.drops)
            scale = f"{doodad.scale[0]:.2g}" if doodad.scale else "1"
            self.doodad_tree.insert(
                "", "end",
                values=(name, doodad.type_id, f"{doodad.x:.0f}, {doodad.y:.0f}",
                        scale, doodad.life, drops),
                tags=("odd" if shown % 2 else "even",))
            shown += 1
        self.doodad_tree.tag_configure("odd", background=ROW_ALT)
        self.doodad_tree.tag_configure("even", background=CARD)
        return shown

    def _item_name(self, code):
        if self.map_data:
            obj = self.map_data.obj_index.get(code)
            if obj and obj.name and obj.name != code:
                return f"{obj.name}({code})"
        base_name = BASE_NAMES.get(code)
        return f"{base_name}({code})" if base_name else code

    def _measure_font(self):
        if not hasattr(self, "_rec_font"):
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
        for recipe in self.recipes:
            result_name = self._item_name(recipe.result)
            ingredients = _ingredient_text(recipe.ingredients, self._item_name)
            if query and compiled.score(result_name + " " + ingredients) is None:
                continue
            self.rec_tree.insert("", "end", values=(result_name, ingredients),
                                 tags=("odd" if shown % 2 else "even",))
            widest = max(widest, font.measure(ingredients))
            shown += 1
        self.rec_tree.column("ingredients", width=max(620, widest + 28))
        self.rec_tree.tag_configure("odd", background=ROW_ALT)
        self.rec_tree.tag_configure("even", background=CARD)
        if self.recipes:
            self.rec_hint.configure(text=f"识别到 {len(self.recipes)} 个合成配方"
                                    "（尽力识别，标准 YDWE 写法准确；非标准写法可能漏检）")
        else:
            self.rec_hint.configure(text="未识别到合成配方（此图可能无合成，或用了非标准写法）")

    def _refresh_cmds(self) -> None:
        query = self.cmd_search.get().strip()
        compiled = compile_query(query)
        self.cmd_tree.delete(*self.cmd_tree.get_children())
        shown = 0
        for command in self.commands:
            if query and compiled.score(command.command + " " + command.hint) is None:
                continue
            self.cmd_tree.insert("", "end",
                                 values=(command.command or "(空)",
                                         "精确" if command.exact else "前缀", command.hint),
                                 tags=("odd" if shown % 2 else "even",))
            shown += 1
        self.cmd_tree.tag_configure("odd", background=ROW_ALT)
        self.cmd_tree.tag_configure("even", background=CARD)
        font = self._measure_font()
        widest = max((font.measure(command.hint) for command in self.commands), default=0)
        self.cmd_tree.column("hint", width=max(420, widest + 28))
        if self.commands:
            self.cmd_hint.configure(text=f"共 {len(self.commands)} 条聊天指令"
                                    f"（前缀=输入以该串开头即触发，常带参数；精确=完全匹配）")
        else:
            self.cmd_hint.configure(text="未发现聊天指令（此图可能无聊天触发，或用了非标准写法）")


def _ingredient_text(ingredients, item_name) -> str:
    parts = []
    for code, count in Counter(ingredients).items():
        name = item_name(code)
        parts.append(f"{name}×{count}" if count > 1 else name)
    return "  +  ".join(parts)
