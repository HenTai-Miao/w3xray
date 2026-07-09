"""GUI trigger ECA workbench hierarchy, detail, search, and state tests."""

from tkinter import ttk

from tests.gui_base import GuiTestCase
from w3xtool.api import MapData
from w3xtool.wtg_diagnostics import TriggerParseFailure, UnknownTriggerFunction
from w3xtool.wtg_models import (
    TriggerEcaFunction,
    TriggerEcaParameter,
    TriggerHeader,
    TriggerTreeSummary,
)


class TestGuiTriggerEca(GuiTestCase):
    def test_gui_trigger_tab_renders_function_hierarchy(self) -> None:
        # Given: a map with a top-level action and a nested function.
        md = _map_with_nested_eca()

        # When: the map is rendered.
        self.app._render_map(md, [], [], None)

        # Then: the trigger, action, and nested call are one tree hierarchy.
        roots = self.app.trigger_eca_tree.get_children()
        self.assertEqual(self.app.trigger_eca_tree.item(roots[0], "text"), "初始化")
        action = self.app.trigger_eca_tree.get_children(roots[0])[0]
        nested = self.app.trigger_eca_tree.get_children(action)[0]
        self.assertEqual(self.app.trigger_eca_tree.item(action, "text"), "创建单位")
        self.assertEqual(self.app.trigger_eca_tree.item(nested, "text"), "整数比较")

    def test_gui_trigger_tab_inserts_deeper_descendants_lazily(self) -> None:
        # Given: an ECA tree with a third function level.
        self.app._render_map(_map_with_nested_eca(), [], [], None)
        root = self.app.trigger_eca_tree.get_children()[0]
        action = self.app.trigger_eca_tree.get_children(root)[0]
        nested = self.app.trigger_eca_tree.get_children(action)[0]

        # When: the nested row is expanded.
        before = _child_texts(self.app.trigger_eca_tree, nested)
        self.app.trigger_eca_tree.focus(nested)
        self.app._on_trigger_eca_open()

        # Then: its real child replaces the lazy placeholder only on demand.
        self.assertNotIn("取玩家编号", before)
        self.assertIn("取玩家编号", _child_texts(self.app.trigger_eca_tree, nested))

    def test_gui_trigger_detail_is_read_only_and_includes_raw_parameters(self) -> None:
        # Given: a rendered action with typed parameters and source metadata.
        self.app._render_map(_map_with_nested_eca(), [], [], None)
        root = self.app.trigger_eca_tree.get_children()[0]
        action = self.app.trigger_eca_tree.get_children(root)[0]
        self.app.trigger_eca_tree.selection_set(action)

        # When: details are requested for the selected row.
        self.app._show_trigger_eca_detail()

        # Then: raw values, types, state, and source offset are visible but immutable.
        detail = self.app.trigger_eca_detail.get("1.0", "end")
        self.assertIn("创建单位", detail)
        self.assertIn("动作", detail)
        self.assertIn("启用：是", detail)
        self.assertIn("hfoo", detail)
        self.assertIn("unitcode", detail)
        self.assertIn("0x20", detail)
        self.assertEqual(self.app.trigger_eca_detail._textbox.cget("state"), "disabled")

    def test_gui_trigger_search_matches_trigger_text(self) -> None:
        # Given: two named triggers are rendered.
        self.app._render_map(_map_with_nested_eca(), [], [], None)

        # When: the user searches by trigger name.
        self.app.trigger_eca_search.set("战斗循环")
        self.app._search_trigger_eca()

        # Then: only that trigger and its function remain.
        roots = self.app.trigger_eca_tree.get_children()
        self.assertEqual(_item_texts(self.app.trigger_eca_tree, roots), ["战斗循环"])
        self.assertEqual(_child_texts(self.app.trigger_eca_tree, roots[0]), ["播放音乐"])

    def test_gui_trigger_search_matches_nested_function_text(self) -> None:
        # Given: a nested call under an action.
        self.app._render_map(_map_with_nested_eca(), [], [], None)

        # When: the user searches by nested function name.
        self.app.trigger_eca_search.set("整数比较")
        self.app._search_trigger_eca()

        # Then: the matching row and its ancestor path are visible.
        root = self.app.trigger_eca_tree.get_children()[0]
        action = self.app.trigger_eca_tree.get_children(root)[0]
        self.assertEqual(self.app.trigger_eca_tree.item(root, "text"), "初始化")
        self.assertEqual(_child_texts(self.app.trigger_eca_tree, action)[0], "整数比较")

    def test_gui_trigger_search_matches_parameter_and_preserves_selection(self) -> None:
        # Given: an action is selected before filtering.
        self.app._render_map(_map_with_nested_eca(), [], [], None)
        root = self.app.trigger_eca_tree.get_children()[0]
        action = self.app.trigger_eca_tree.get_children(root)[0]
        self.app.trigger_eca_tree.selection_set(action)

        # When: the user searches by a raw parameter value.
        self.app.trigger_eca_search.set("hfoo")
        self.app._search_trigger_eca()

        # Then: the same stable row remains selected in the filtered tree.
        filtered_root = self.app.trigger_eca_tree.get_children()[0]
        filtered_action = self.app.trigger_eca_tree.get_children(filtered_root)[0]
        self.assertEqual(filtered_action, action)
        self.assertEqual(self.app.trigger_eca_tree.selection(), (action,))

    def test_gui_trigger_refresh_preserves_selection_for_same_map(self) -> None:
        # Given: an action remains selected in the currently rendered map.
        md = _map_with_nested_eca()
        self.app._render_map(md, [], [], None)
        root = self.app.trigger_eca_tree.get_children()[0]
        action = self.app.trigger_eca_tree.get_children(root)[0]
        self.app.trigger_eca_tree.selection_set(action)
        self.app._show_trigger_eca_detail()

        # When: the same map view is refreshed.
        self.app._refresh_trigger_eca()

        # Then: the stable row and its detail remain selected.
        self.assertEqual(self.app.trigger_eca_tree.selection(), (action,))
        self.assertIn("创建单位", self.app.trigger_eca_detail.get("1.0", "end"))

    def test_gui_trigger_array_indexer_value_is_searchable(self) -> None:
        # Given: an array variable parameter has a recursive index parameter.
        self.app._render_map(_map_with_array_indexer(), [], [], None)

        # When: the user searches for the raw array-index value.
        self.app.trigger_eca_search.set("索引值")
        self.app._search_trigger_eca()

        # Then: the containing action remains visible.
        root = self.app.trigger_eca_tree.get_children()[0]
        self.assertEqual(_child_texts(self.app.trigger_eca_tree, root), ["读取数组"])

    def test_gui_trigger_array_indexer_nested_function_is_visible_in_tree_and_detail(self) -> None:
        # Given: an array index is itself produced by a nested call.
        self.app._render_map(_map_with_array_indexer(), [], [], None)
        root = self.app.trigger_eca_tree.get_children()[0]
        action = self.app.trigger_eca_tree.get_children(root)[0]

        # When: the action hierarchy and details are inspected.
        self.app.trigger_eca_tree.selection_set(action)
        self.app._show_trigger_eca_detail()

        # Then: both the nested index call and raw index value are represented.
        self.assertIn("取数组下标", _child_texts(self.app.trigger_eca_tree, action))
        self.assertIn("索引值", self.app.trigger_eca_detail.get("1.0", "end"))

    def test_gui_trigger_tab_distinguishes_missing_schema_from_parse_failure(self) -> None:
        # Given: both schema and malformed-byte diagnostics exist.
        md = _map_with_trigger_diagnostics()

        # When: the map is rendered.
        self.app._render_map(md, [], [], None)

        # Then: neither diagnostic is collapsed into the other.
        text = self.app.trigger_eca_status.cget("text")
        self.assertIn("缺 TriggerData", text)
        self.assertIn("解析失败", text)
        self.assertIn("MissingAction", text)
        self.assertIn("BadAction", text)

    def test_gui_trigger_empty_map_clears_search_selection_and_detail(self) -> None:
        # Given: a prior map left filtered rows and details visible.
        self.app._render_map(_map_with_nested_eca(), [], [], None)
        root = self.app.trigger_eca_tree.get_children()[0]
        action = self.app.trigger_eca_tree.get_children(root)[0]
        self.app.trigger_eca_tree.selection_set(action)
        self.app._show_trigger_eca_detail()
        self.app.trigger_eca_search.set("hfoo")
        self.app._search_trigger_eca()

        # When: a different, valid empty trigger summary is rendered.
        self.app._render_map(_empty_trigger_map(), [], [], None)

        # Then: no row, query, selection, or detail leaks from the old map.
        self.assertEqual(self.app.trigger_eca_tree.get_children(), ())
        self.assertEqual(self.app.trigger_eca_tree.selection(), ())
        self.assertEqual(self.app.trigger_eca_search.get(), "")
        self.assertEqual(self.app.trigger_eca_detail.get("1.0", "end").strip(), "")
        self.assertIn("没有可显示", self.app.trigger_eca_status.cget("text"))

    def test_gui_trigger_render_allocates_no_icons_or_per_eca_widgets(self) -> None:
        # Given: the fixed workbench widget tree and an icon resolver that must not run.
        before = tuple(_widget_types(self.app.tab_trigger_eca))
        resolver = _RejectingIconResolver()

        # When: nested ECAs are rendered.
        self.app._render_map(_map_with_nested_eca(), [], [], resolver)

        # Then: only Treeview rows changed; no widgets or icons were allocated per ECA.
        self.assertEqual(tuple(_widget_types(self.app.tab_trigger_eca)), before)
        self.assertEqual(before.count("Treeview"), 1)
        self.assertEqual(resolver.calls, 0)


def _map_with_nested_eca() -> MapData:
    deep = TriggerEcaFunction(
        "初始化", 3, "取玩家编号", True,
        (TriggerEcaParameter(0, "Player(0)", expected_type="player", source_offset=0x3C),),
        (), depth=2, source_offset=0x38,
    )
    nested = TriggerEcaFunction(
        "初始化", 3, "整数比较", True,
        (TriggerEcaParameter(3, "玩家编号", nested_function=deep, expected_type="integer"),),
        (), depth=1, source_offset=0x30,
    )
    action = TriggerEcaFunction(
        "初始化", 2, "创建单位", True,
        (
            TriggerEcaParameter(0, "1", expected_type="integer", source_offset=0x24),
            TriggerEcaParameter(0, "hfoo", expected_type="unitcode", source_offset=0x28),
            TriggerEcaParameter(3, "比较", nested_function=nested, expected_type="boolean"),
        ),
        (), depth=0, source_offset=0x20,
    )
    music = TriggerEcaFunction(
        "战斗循环", 2, "播放音乐", True,
        (TriggerEcaParameter(0, "battle_theme", expected_type="string"),),
        (), source_offset=0x60,
    )
    return _map_with_summary("ECA图", (action, music))


def _map_with_trigger_diagnostics() -> MapData:
    return _map_with_summary(
        "诊断图",
        (),
        missing=(UnknownTriggerFunction("初始化", "MissingAction", 2, 0x24),),
        failures=(TriggerParseFailure("初始化", "BadAction", 0x48, "bad bytes"),),
    )


def _map_with_array_indexer() -> MapData:
    index_call = TriggerEcaFunction(
        "数组测试", 3, "取数组下标", True,
        (TriggerEcaParameter(0, "2", expected_type="integer", source_offset=0x84),),
        (), depth=1, source_offset=0x80,
    )
    index = TriggerEcaParameter(
        2, "索引值", nested_function=index_call,
        expected_type="integer", source_offset=0x78,
    )
    array = TriggerEcaParameter(
        1, "Numbers", have_array_indexer=1, array_indexer=index,
        expected_type="integer", source_offset=0x70,
    )
    action = TriggerEcaFunction(
        "数组测试", 2, "读取数组", True, (array,), (), source_offset=0x68,
    )
    return _map_with_summary("数组图", (action,))


def _empty_trigger_map() -> MapData:
    return _map_with_summary("空触发图", ())


def _map_with_summary(
    name: str,
    functions: tuple[TriggerEcaFunction, ...],
    *,
    missing: tuple[UnknownTriggerFunction, ...] = (),
    failures: tuple[TriggerParseFailure, ...] = (),
) -> MapData:
    trigger_names = tuple(dict.fromkeys(function.trigger_name for function in functions))
    headers = tuple(
        TriggerHeader(trigger, "", False, True, False, False, False, 0, 1)
        for trigger in trigger_names
    )
    md = MapData(path=f"{name}.w3x", name=name)
    md.trigger_summary = TriggerTreeSummary(
        version=7,
        is_reforged=False,
        category_count=0,
        variable_count=0,
        trigger_count=len(headers),
        comment_count=0,
        script_count=0,
        categories=(),
        variables=(),
        triggers=headers,
        eca_functions=functions,
        has_unexpanded_functions=bool(missing or failures),
        missing_schema_functions=missing,
        parse_failures=failures,
    )
    return md


def _item_texts(tree: ttk.Treeview, items: tuple[str, ...]) -> list[str]:
    return [tree.item(item, "text") for item in items if tree.item(item, "text")]


def _child_texts(tree: ttk.Treeview, parent: str) -> list[str]:
    return _item_texts(tree, tree.get_children(parent))


def _widget_types(widget) -> list[str]:
    result = [widget.winfo_class()]
    for child in widget.winfo_children():
        result.extend(_widget_types(child))
    return result


class _RejectingIconResolver:
    def __init__(self) -> None:
        self.calls = 0

    def get_image(self, _path: str):
        self.calls += 1
        raise AssertionError("GUI trigger ECA rendering must not load icons")
