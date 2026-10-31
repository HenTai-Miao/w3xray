"""Actual Tk controls and independently checked exports for source adoption."""

from __future__ import annotations

import json
from pathlib import Path
import tkinter as tk
from typing import Any, TYPE_CHECKING

import customtkinter as ctk

from .gui_offline_acceptance_support import (
    _dialog_response,
    _require,
    _set_entry,
    _temporary_attribute,
    _wait_for,
    loaded_acceptance_map,
)
from .gui_offline_acceptance_v12_evidence import (
    read_loadout_export,
    validate_call_evidence,
    validate_campaign_metadata,
    validate_loadout_evidence,
    validate_map_object,
)
from .gui_offline_acceptance_v12_fixtures import (
    CAMPAIGN_NAME,
    CHILD_MEMBER,
    HUGE_QUANTITY,
)

if TYPE_CHECKING:
    from .gui import App
    from .gui_offline_acceptance_support import _Fixtures


V12_CASE_NAMES = (
    "calls-source-query-history-replay",
    "offline-loadout-complete-records",
    "unicode-wts-w3f-inheritance",
)
V12_EXPORT_NAMES = (
    "查询结果.md",
    "loadout-six.json",
    "loadout-nine.tsv",
    "loadout-nine.md",
    "loadout-filtered.json",
    "loadout-partial.json",
    "loadout-empty.json",
    "unicode-inheritance.json",
)
LEGACY_EXPORT_NAMES = (
    "reference.json",
    "map-reference.json",
    "selected-map.json",
    "selected-map.tsv",
    "selected-map.md",
    "save-report.json",
    "save-utf16le.json",
    "upgrade-fields.json",
    "upgrade-fields-selected.tsv",
    "archive-recovery/war3map.j",
    "archive-recovery/asset.blp",
    "archive-recovery/RecoveredNames/blocks/block_000002-locale_0409-platform_00.blp",
    "archive-recovery/Models/Hero.mdx",
    "archive-recovery/Models/Hero_Portrait.mdx",
    "archive-recovery/war3mapImported/ImportedHero.mdx",
    "archive-recovery/war3mapImported/ImportedHero_Portrait.mdx",
    "archive-recovery/Textures/英雄.blp",
    "archive-recovery/UnknownRaw/File000008.mpqraw",
    "archive-recovery/RecoveredNames/manifest.tsv",
    "archive-recovery/UnknownRaw/manifest.tsv",
)


def expected_export_names() -> set[str]:
    return (
        set(LEGACY_EXPORT_NAMES)
        | {"archive-recovery/RecoveredNames/name-hint-catalog.json"}
        | {"v12/" + name for name in V12_EXPORT_NAMES}
    )


def _widgets(parent: tk.Misc) -> list[tk.Misc]:
    pending = [parent]
    result = []
    while pending:
        widget = pending.pop()
        result.append(widget)
        pending.extend(widget.winfo_children())
    return result


def _button(parent: tk.Misc, text: str) -> ctk.CTkButton:
    matches = [
        widget
        for widget in _widgets(parent)
        if isinstance(widget, ctk.CTkButton) and widget.cget("text") == text
    ]
    _require(len(matches) == 1, "真实按钮不存在或不唯一: " + text)
    return matches[0]


def _menu(parent: tk.Misc, label: str) -> tk.Menu:
    matches = []
    for widget in _widgets(parent):
        if isinstance(widget, tk.Menu):
            end = widget.index("end")
            if end is not None and any(
                widget.type(index) == "command"
                and widget.entrycget(index, "label") == label
                for index in range(end + 1)
            ):
                matches.append(widget)
    _require(len(matches) == 1, "真实菜单项不存在或不唯一: " + label)
    return matches[0]


def _query_json(window) -> dict[str, Any] | None:
    try:
        value, _end = json.JSONDecoder().raw_decode(window._output.get("1.0", "end-1c"))
    except ValueError, TypeError:
        return None
    return value if isinstance(value, dict) else None


def exercise_source_calls(
    app: App, fixtures: _Fixtures, owned: list[tk.Toplevel], errors: list[str]
) -> None:
    from . import archive_export, gui_pack_query as query

    destination = fixtures.root / "exports/v12"
    destination.mkdir(parents=True, exist_ok=True)
    with (
        _temporary_attribute(query, "_HISTORY", []),
        _temporary_attribute(query, "_PINNED", []),
        _temporary_attribute(query, "_LAST_RESULT", ""),
    ):
        window = query._PackQueryWindow(
            app, str(fixtures.root / "v12/calls-pack"), prefill_command="calls"
        )
        owned.append(window)
        window._mode_extra2._buttons_dict["脚本调用"].invoke()
        _require(
            window._mode.get() == "calls", "脚本调用可见按钮没有传 canonical calls"
        )
        window._var_json.set(True)
        _set_entry(window._keyword, "")
        _button(window, "查询").invoke()

        def result() -> dict[str, Any]:
            _wait_for(
                app,
                lambda: _query_json(window) is not None,
                "真实调用查询交付 JSON",
                errors,
            )
            value = _query_json(window)
            assert value is not None
            return value

        full = result()
        _require(
            (full["calls_total"], full["calls_omitted"]) == (10, 0),
            "空调用查询没有列出全量源记录",
        )
        validate_call_evidence([row["call"] for row in full["calls"]])
        _require(
            "calls" in window._history.cget("values"), "空 calls 查询未进入真实历史控件"
        )
        _set_entry(window._keyword, "h001 && CreateUnit")
        _button(window, "查询").invoke()
        filtered = result()
        _require(
            filtered["calls_total"] == 1
            and filtered["calls"][0]["callee"] == "CreateUnit",
            "实际查询框 Boolean 过滤未选择完整调用",
        )
        history_menu = window._history._dropdown_menu
        history_end = history_menu.index("end")
        history_entries = [
            index
            for index in range(history_end + 1 if history_end is not None else 0)
            if history_menu.entrycget(index, "label").strip() == "calls"
        ]
        _require(len(history_entries) == 1, "真实历史菜单遗漏或重复空 calls 查询")
        history_menu.invoke(history_entries[0])
        replay = result()
        _require(
            replay["query"] == "" and replay["calls_total"] == 10,
            "真实历史重放丢失空 calls 查询",
        )
        window._mode_extra._buttons_dict["again"].invoke()
        _button(window, "查询").invoke()
        again = result()
        _require(
            again["query"] == "" and again["calls_total"] == 10,
            "again 未恢复全量调用请求",
        )
        validate_call_evidence([row["call"] for row in again["calls"]])
        expected_bytes = (window._output.get("1.0", "end").strip() + "\n").encode(
            "utf-8"
        )
        with _temporary_attribute(
            archive_export,
            "tmp_extract_dir",
            lambda *_args, **_kwargs: str(destination),
        ):
            _menu(window, "导出为 .md").invoke("导出为 .md")
        output = destination / "查询结果.md"
        _require(
            output.read_bytes() == expected_bytes,
            "实际菜单 Markdown 导出改变完整查询字节",
        )
        _require(Path(window.clipboard_get()) == output, "导出路径没有交付到剪贴板")
        window.destroy()


def exercise_loadout_workbench(
    app: App, fixtures: _Fixtures, owned: list[tk.Toplevel], errors: list[str]
) -> None:
    from . import gui_loadout_workbench as loadout

    previous = set(app.winfo_children())
    with _temporary_attribute(loadout, "_session_selection", None):
        app.data_tools_menu.invoke("离线装备方案")
    windows = [
        child
        for child in app.winfo_children()
        if child not in previous and isinstance(child, loadout.LoadoutWorkbench)
    ]
    _require(len(windows) == 1, "数据工具菜单没有打开装备方案工作台")
    window = windows[0]
    owned.append(window)
    destination = fixtures.root / "exports/v12"
    destination.mkdir(parents=True, exist_ok=True)

    def read(name: str, count: int) -> None:
        window.query_var.set("")
        _set_entry(window.source_entry, str(fixtures.root / f"v12/plans/{name}.json"))
        window.refresh_button.invoke()
        _wait_for(
            app,
            lambda: (
                window._fresh
                and window._selection is not None
                and len(window.tree.get_children()) == count
                and window.details.get("1.0", "end-1c") == window._detail_text
            ),
            "真实装备读取及完整文本交付: " + name,
            errors,
        )
        _require(
            str(window.export_json_button.cget("state")) == "normal",
            "稳定来源未启用实际导出按钮",
        )

    def export(
        name: str,
        suffix: str,
        *,
        filename: str | None = None,
        selected: tuple[int, ...] | None = None,
    ) -> None:
        output = destination / (filename or f"loadout-{name}.{suffix}")
        with _dialog_response(loadout.filedialog, "asksaveasfilename", str(output)):
            window.export_buttons[suffix].invoke()
        _wait_for(
            app,
            lambda: output.is_file() and "已导出" in str(window.status.cget("text")),
            "真实装备完整导出: " + output.name,
            errors,
        )
        validate_loadout_evidence(
            read_loadout_export(output),
            fixtures.payloads[fixtures.root / f"v12/plans/{name}.json"],
            name,
            selected=selected,
        )

    read("six", 1)
    export("six", "json")
    read("nine", 2)
    _require(
        HUGE_QUANTITY in window.details.get("1.0", "end-1c"), "真实文本控件截断长数量"
    )
    window.jump_buttons["完整来源与证据"].invoke()
    _require(
        bool(window.details.tag_ranges("section-current")), "段落跳转没有当前段高亮"
    )
    window.find_var.set("守城乙")
    _button(window, "下一处").invoke()
    _require(bool(window.details.tag_ranges("search-hit")), "实际内搜没有定位命中")
    for suffix in ("tsv", "md"):
        export("nine", suffix)
    window.query_var.set("远征甲 && I001")
    _button(window, "搜索").invoke()
    _wait_for(
        app,
        lambda: (
            window._selection is not None
            and window._selection.query == "远征甲 && I001"
            and window.tree.get_children() == ("1",)
        ),
        "实际装备完整记录 Boolean 筛选",
        errors,
    )
    export("nine", "json", filename="loadout-filtered.json", selected=(1,))
    read("partial", 2)
    _require(
        "duplicate-json-key" in window.details.get("1.0", "end-1c"),
        "真实详情遗漏重复键诊断",
    )
    export("partial", "json")
    read("empty", 0)
    _require(
        "确认的空 records 数组表示零记录" in window.details.get("1.0", "end-1c"),
        "确认零记录未交付清空搜索出路",
    )
    export("empty", "json")
    for key in ("a", "A", "f", "F", "r", "R"):
        _require(
            bool(window.bind(f"<Control-{key}>")),
            "新增工作台快捷键缺少大小写绑定: " + key,
        )
    window.destroy()


def exercise_unicode_sources(
    app: App, fixtures: _Fixtures, owned: list[tk.Toplevel], errors: list[str]
) -> None:
    from . import gui_reference_catalog as reference
    from .map_metadata_exports import format_map_metadata_evidence

    map_path = fixtures.root / "v12/unicode-inheritance.w3x"
    previous = set(app.winfo_children())
    with _dialog_response(reference.filedialog, "askopenfilename", str(map_path)):
        app.data_tools_menu.invoke("直接打开地图对象目录（离线）")
    windows = [
        child
        for child in app.winfo_children()
        if child not in previous and isinstance(child, reference.ReferenceCatalogWindow)
    ]
    _require(len(windows) == 1, "实际直接地图目录入口没有打开窗口")
    window = windows[0]
    owned.append(window)
    for entry in (window._pack_entry, window._profile_entry, window._build_entry):
        _set_entry(entry, "")
    _set_entry(window._source_entry, str(map_path))
    _set_entry(window._query_entry, '="yV12"')
    window._kind.set("objects")
    window._category.set("物品")
    window._run_button.invoke()
    _wait_for(
        app,
        lambda: (
            window._result is not None
            and not window._busy
            and [row.id for row in window._result.records] == ["yV12"]
        ),
        "真实 Unicode 继承物品读取",
        errors,
    )
    output = fixtures.root / "exports/v12/unicode-inheritance.json"
    with _dialog_response(reference.filedialog, "asksaveasfilename", str(output)):
        window._export_button.invoke()
    _wait_for(
        app,
        lambda: output.is_file() and not window._exporting,
        "真实 Unicode 物品完整导出",
        errors,
    )
    validate_map_object(json.loads(output.read_text("utf-8")))
    window.destroy()
    with loaded_acceptance_map(app, fixtures.root / "v12/unicode-campaign.w3n"):
        app.tabs.set("地图信息")
        _wait_for(
            app,
            lambda: CAMPAIGN_NAME in app.info_box.get("1.0", "end-1c"),
            "真实 UTF16BE 战役标题可见",
            errors,
        )
        _require(
            app.map_data is not None and len(app.map_data.sub_maps) == 1,
            "真实战役加载遗漏无 listfile 的 Unicode 子地图",
        )
        assert app.map_data is not None
        _require(
            app.map_data.sub_maps[0].path == CHILD_MEMBER, "真实子地图路径被显示名替换"
        )
        validate_campaign_metadata(
            json.loads(format_map_metadata_evidence(app.map_data))["w3f"]
        )


__all__ = (
    "V12_CASE_NAMES",
    "V12_EXPORT_NAMES",
    "exercise_loadout_workbench",
    "exercise_source_calls",
    "exercise_unicode_sources",
)
