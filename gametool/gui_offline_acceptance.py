"""Real, isolated Tk acceptance for offline data and direct-map workspaces."""

from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import threading
import tkinter as tk
from tkinter import messagebox
from typing import Any, TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from .gui import App


from .gui_offline_acceptance_support import (
    _CallbackErrors as _CallbackErrors,
    _Fixtures as _Fixtures,
    _capture_callbacks as _capture_callbacks,
    _dialog_response as _dialog_response,
    _fixture_mpq as _fixture_mpq,
    _identity as _identity,
    _pump_after_close as _pump_after_close,
    _raise_callback_errors as _raise_callback_errors,
    _read_json as _read_json,
    _read_selection_export as _read_selection_export,
    _require as _require,
    _set_entry as _set_entry,
    _temporary_attribute as _temporary_attribute,
    _temporary_environment as _temporary_environment,
    _wait_for as _wait_for,
)


def _fixture_map(names: tuple[str, str], descriptions: tuple[str, str]) -> bytes:
    """Store two explicitly authored item definitions in a Warcraft III map."""
    records = [struct.pack("<iii", 2, 0, 2)]
    for code, name, description in zip(
        (b"yM01", b"yM02"), names, descriptions, strict=True
    ):
        records.append(b"ratf" + code + struct.pack("<i", 2))
        for key, value in ((b"unam", name), (b"ides", description)):
            records.append(
                key + struct.pack("<i", 3) + value.encode("utf-8") + b"\0" * 5
            )
    return _fixture_mpq({"war3map.w3t": b"".join(records)})


def _create_fixtures() -> _Fixtures:
    root = Path(tempfile.mkdtemp(prefix="gamexray-offline-gui-")).resolve()
    repository = Path(__file__).resolve().parents[1]
    _require(not root.is_relative_to(repository), "临时输入目录必须在仓库外")
    (root / "exports").mkdir()
    marker = "offline" + uuid4().hex
    descriptions = (
        f'{marker} alpha 首行\r\n\r\n完整续行|n保留 TAB\t与引号"甲"\r\n\r\n',
        f"{marker} beta 首行\r\n末尾完整证据乙\r\n",
    )
    blocks = (
        "ID：yA01\r\n名字：离线 alpha 物品\r\n描述：" + descriptions[0],
        "ID：yA02\r\n名字：离线 beta 物品\r\n描述：" + descriptions[1],
    )
    id_table = root / "物品ID.txt"
    map_path = root / "直接读取地图.w3x"
    map_names = (f"{marker} alpha 地图物品", f"{marker} beta 地图物品")
    save_root = root / "save-inputs"
    save_root.mkdir()
    save_text = save_root / "alpha.txt"
    save_utf16 = root / "explicit-utf16le.txt"
    save_utf16_text = (
        "function PreloadFiles takes nothing returns nothing\r\n"
        f'    call Preload( "-load {marker}-utf16-甲" )\r\n'
        f'    call Preload( "-load {marker}-utf16-乙" )\r\n'
        "endfunction\r\n"
    )
    pack_root = root / "reference-pack"
    pack_child = pack_root / "子地图" / "章一"
    unrelated_pack = root / "unrelated-pack"
    config: dict[str, Any] = {
        "language": "auto",
        "active_profile": "One",
        "profiles": {
            "One": {
                "bindings": [
                    {
                        "binding_id": "ability_1",
                        "source": "M",
                        "target": "M",
                        "group": "ability",
                        "slot_index": 0,
                    }
                ]
            },
            "Two": {
                "bindings": [
                    {
                        "binding_id": "item_1",
                        "source": "1",
                        "target": "1",
                        "group": "item",
                        "slot_index": 0,
                    }
                ]
            },
        },
    }
    changed = deepcopy(config)
    changed["profiles"]["One"]["bindings"][0]["smartcast"] = True
    hotkeys_old, hotkeys_new = root / "hotkeys-old.json", root / "hotkeys-new.json"
    payloads = {
        map_path: _fixture_map(map_names, descriptions),
        id_table: b"\xef\xbb\xbf" + "".join(blocks).encode("utf-8"),
        save_text: (
            "function PreloadFiles takes nothing returns nothing\r\n"
            f'    call Preload( "-load {marker}-alpha" )\r\n'
            "endfunction\r\n"
        ).encode("utf-8"),
        save_root / "beta.ini": (
            f'[save]\r\nnote="{marker} beta 完整记录"\r\ngold=0\r\n'
        ).encode("utf-8"),
        save_utf16: save_utf16_text.encode("utf-16-le"),
        hotkeys_old: (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        ),
        hotkeys_new: (json.dumps(changed, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        ),
    }
    from .batch_tsv import format_tsv_rows

    for pack, name in (
        (pack_root, "根包"),
        (pack_child, "章一"),
        (unrelated_pack, "禁止串入的另包"),
    ):
        ids = pack / "对象ID" / "物品.tsv"
        fields = pack / "对象字段.tsv"
        ids.parent.mkdir(parents=True)
        payloads[ids] = format_tsv_rows(
            (
                ("分类", "ID", "数值", "基础ID", "名称", "自定义", "说明"),
                ("物品", "yP01", "", "", name + "物品", "True", name + "说明"),
            )
        ).encode("utf-8")
        payloads[fields] = format_tsv_rows(
            (
                ("分类", "ID", "名称", "字段键", "字段名", "值", "来源"),
                ("物品", "yP01", name + "物品", "ides", "说明", name + "证据", name),
            )
        ).encode("utf-8")
    from .gui_offline_acceptance_2122 import adoption_fixture_payloads
    from .gui_offline_acceptance_v12_fixtures import source_adoption_fixture_payloads

    payloads.update(
        {root / name: data for name, data in adoption_fixture_payloads().items()}
    )
    payloads.update(
        {root / name: data for name, data in source_adoption_fixture_payloads().items()}
    )
    for path, payload in payloads.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return _Fixtures(
        root,
        marker,
        id_table,
        blocks,
        descriptions,
        map_path,
        map_names,
        save_root,
        save_text,
        save_utf16,
        save_utf16_text,
        pack_root,
        pack_child,
        unrelated_pack,
        hotkeys_old,
        hotkeys_new,
        payloads,
        {path: _identity(path) for path in payloads},
    )


def _exercise_selected_exports(app, fixtures, window, errors) -> None:
    from . import gui_reference_catalog as reference
    from .reference_cli import reference_result_to_dict

    result = window._result
    _require(
        result is not None and len(result.records) == 2, "多选验收需要两条实际记录"
    )
    assert result is not None
    _require(
        all(row.values and row.raw_rows and row.scope for row in result.records),
        "多选记录没有完整字段、原始记录与范围",
    )
    window._list.selection_clear(0, "end")
    window._list.selection_set(0, 1)
    window._list.event_generate("<<ListboxSelect>>", when="tail")
    _wait_for(
        app,
        lambda: len(window._list.curselection()) == 2 and window._render_id is None,
        "实际 Listbox 多选两条",
        errors,
    )
    expected = reference_result_to_dict(result)
    expected = json.loads(json.dumps(expected, ensure_ascii=False))
    for extension in ("json", "tsv", "md"):
        destination = fixtures.root / "exports" / f"selected-map.{extension}"
        with _dialog_response(
            reference.filedialog, "asksaveasfilename", str(destination)
        ):
            window._export_selected_button.invoke()
        _wait_for(
            app,
            lambda: (
                destination.is_file()
                and not window._exporting
                and "已导出" in str(window._status.cget("text"))
            ),
            f"GUI 多选 {extension} 导出",
            errors,
        )
        exported = _read_selection_export(destination)
        _require(
            exported.pop("selection")
            == {
                "indices": [0, 1],
                "selected": 2,
                "displayed": 2,
                "matched": 2,
                "omitted_by_query": 0,
            },
            f"{extension} 多选计数或索引错误",
        )
        _require(exported == expected, f"{extension} 重解析后字段/raw/scope/来源不完整")
    window._list.selection_clear(0, "end")
    window._list.event_generate("<<ListboxSelect>>", when="tail")
    _wait_for(
        app,
        lambda: str(window._export_selected_button.cget("state")) == "disabled",
        "清空多选后导出按钮禁用",
        errors,
    )


def _exercise_reference(
    app: App, fixtures: _Fixtures, owned: list[tk.Toplevel], errors: list[str]
) -> None:
    from . import gui_reference_catalog as reference

    window = reference.ReferenceCatalogWindow(app, id_tables=(str(fixtures.id_table),))
    owned.append(window)
    for entry in (
        window._map_entry,
        window._pack_entry,
        window._profile_entry,
        window._build_entry,
        window._source_entry,
    ):
        _set_entry(entry, "")
    _set_entry(window._query_entry, fixtures.marker + " && (alpha || beta)")
    window._kind.set("objects")
    window._category.set("物品")
    _wait_for(
        app,
        lambda: window._result is not None and not window._busy,
        "外部 ID 的真实后台查询",
        errors,
    )
    result = window._result
    _require(result is not None and len(result.records) == 2, "ID 查询未交付完整两条")
    assert result is not None
    _require(result.catalog_complete, "合成 ID 来源未完整读取")
    _require(window._list.size() == 2, "ID 窗口列表未显示两条记录")
    digest = hashlib.sha256(fixtures.payloads[fixtures.id_table]).hexdigest()
    sources = [
        source for source in result.sources if source.path == str(fixtures.id_table)
    ]
    _require(len(sources) == 1 and sources[0].sha256 == digest, "ID 来源 SHA 缺失")
    for index, record in enumerate(result.records):
        number = ("yA01", "yA02").index(record.id)
        details = dict(record.details)
        _require(
            record.scope == "external" and record.category == "物品", "ID 范围/类别错误"
        )
        _require(
            details["描述"] == fixtures.descriptions[number], "ID 多行描述被截断或改写"
        )
        raw = fixtures.id_blocks[number].encode("utf-8")
        start, end = int(details["字节起点"]), int(details["字节终点（不含）"])
        _require(
            fixtures.payloads[fixtures.id_table][start:end] == raw, "ID 原字节偏移错误"
        )
        _require(
            record.raw_rows == ((fixtures.id_blocks[number], raw.hex()),),
            "ID 原文/字节未保留",
        )
        _require(
            details["记录SHA-256"] == hashlib.sha256(raw).hexdigest(),
            "ID 记录 SHA 错误",
        )
        window._list.selection_clear(0, "end")
        window._list.selection_set(index)
        window._list.event_generate("<<ListboxSelect>>", when="tail")
        _wait_for(
            app,
            lambda: (
                raw.hex() in window._output.get("1.0", "end-1c")
                and window._render_id is None
            ),
            "ID 选中记录的完整详情",
            errors,
        )
        _require(
            window._output.get("1.0", "end-1c") == window._detail_content,
            "ID 详情未完整渲染",
        )
        _require(digest in window._detail_content, "ID 详情未展示来源 SHA")
    destination = fixtures.root / "exports" / "reference.json"
    with _dialog_response(reference.filedialog, "asksaveasfilename", str(destination)):
        window._export_button.invoke()
    _wait_for(
        app,
        lambda: destination.is_file() and "已导出" in str(window._status.cget("text")),
        "ID GUI 完整导出",
        errors,
    )
    exported = _read_json(destination)
    _require(
        exported["matched"] == 2 and len(exported["records"]) == 2, "ID 导出丢记录"
    )
    _require(
        all(row["scope"] == "external" for row in exported["records"]),
        "ID 导出丢外部范围",
    )
    _require(
        {row["id"] for row in exported["records"]} == {"yA01", "yA02"},
        "ID 导出身份错误",
    )
    for row in exported["records"]:
        number = ("yA01", "yA02").index(row["id"])
        details = dict(row["details"])
        raw = fixtures.id_blocks[number].encode("utf-8")
        _require(details["描述"] == fixtures.descriptions[number], "ID 导出截断描述")
        _require(
            row["raw_rows"] == [[fixtures.id_blocks[number], raw.hex()]],
            "ID 导出丢原文/字节",
        )
        _require(
            details["记录SHA-256"] == hashlib.sha256(raw).hexdigest(),
            "ID 导出记录指纹错误",
        )
    _require(
        any(
            source["path"] == str(fixtures.id_table) and source["sha256"] == digest
            for source in exported["sources"]
        ),
        "ID 导出丢来源 SHA",
    )
    previous = window._result
    window._id_controls[-1].invoke()
    _wait_for(
        app,
        lambda: window._result is not previous and not window._busy,
        "清空 ID 来源",
        errors,
    )
    _require(
        window._id_tables == () and window._list.size() == 0, "清空 ID 后仍显示旧结果"
    )
    previous = window._result
    with _dialog_response(
        reference.filedialog, "askopenfilenames", (str(fixtures.id_table),)
    ):
        window._id_controls[0].invoke()
    _wait_for(
        app,
        lambda: window._result is not previous and not window._busy,
        "重新选择 ID 来源",
        errors,
    )
    _require(
        window._result is not None and len(window._result.records) == 2,
        "重新选择 ID 未恢复两条",
    )


def _exercise_map_reference(
    app: App, fixtures: _Fixtures, owned: list[tk.Toplevel], errors: list[str]
) -> None:
    from . import gui_reference_catalog as reference

    previous_windows = set(app.winfo_children())
    with _dialog_response(
        reference.filedialog, "askopenfilename", str(fixtures.map_path)
    ):
        app.data_tools_menu.invoke("直接打开地图对象目录（离线）")
    windows = [
        child
        for child in app.winfo_children()
        if child not in previous_windows
        and isinstance(child, reference.ReferenceCatalogWindow)
    ]
    _require(len(windows) == 1, "数据工具没有打开直接地图目录窗口")
    window = windows[0]
    owned.append(window)
    _set_entry(window._query_entry, "")
    _set_entry(window._build_entry, "")
    _set_entry(window._profile_entry, "")
    _set_entry(window._source_entry, str(fixtures.map_path))
    window._kind.set("objects")
    window._category.set("物品")
    _wait_for(
        app,
        lambda: window._result is not None and not window._busy,
        "合成 MPQ 全量对象目录读取",
        errors,
    )
    result = window._result
    _require(result is not None and result.catalog_complete, "合成 MPQ 目录读取不完整")
    assert result is not None
    _require(window._pack_entry.get() == "", "选地图后知识包来源未清空")
    _require(result.map_path == str(fixtures.map_path), "地图来源身份丢失")
    _require(
        {row.id for row in result.records} == {"yM01", "yM02"}, "地图两物品未完整读取"
    )
    _require(window._list.size() == 2 and result.omitted == 0, "地图列表被截断")
    _require(len(result.map_scopes) == 1, "地图范围数量错误")
    scope = result.map_scopes[0]
    _require(
        dict(scope.category_counts)["物品"] == 2 and scope.complete,
        "地图分类计数不完整",
    )
    digest = hashlib.sha256(fixtures.payloads[fixtures.map_path]).hexdigest()
    _require(scope.sha256 == digest, "地图范围没有原文件 SHA")
    _require(
        any(
            source.member_path == "war3map.w3t"
            and source.path == str(fixtures.map_path)
            for source in result.sources
        ),
        "地图对象来源缺归档成员",
    )
    window._overview_button.invoke()
    _wait_for(
        app,
        lambda: (
            digest in window._detail_content
            and "已确认分类数:" in window._detail_content
            and window._render_id is None
        ),
        "地图来源总览",
        errors,
    )
    _require(
        "物品 2" in window._detail_content and "war3map.w3t" in window._detail_content,
        "地图总览缺分类或成员",
    )
    _exercise_selected_exports(app, fixtures, window, errors)
    _set_entry(window._query_entry, fixtures.marker + " && alpha")
    window._run_button.invoke()
    _wait_for(
        app,
        lambda: window._result is not result and not window._busy,
        "地图 Boolean 筛选",
        errors,
    )
    selected = window._result
    _require(
        selected is not None and [row.id for row in selected.records] == ["yM01"],
        "地图筛选没有保留完整目标对象",
    )
    assert selected is not None
    _wait_for(
        app,
        lambda: (
            fixtures.map_names[0] in window._detail_content
            and window._render_id is None
        ),
        "地图对象完整详情",
        errors,
    )
    _require(
        digest in window._detail_content and "war3map.w3t" in window._detail_content,
        "地图详情丢原文件或成员来源",
    )
    destination = fixtures.root / "exports" / "map-reference.json"
    with _dialog_response(reference.filedialog, "asksaveasfilename", str(destination)):
        window._export_button.invoke()
    _wait_for(
        app,
        lambda: destination.is_file() and "已导出" in str(window._status.cget("text")),
        "地图 GUI 完整导出",
        errors,
    )
    exported = _read_json(destination)
    _require(
        exported["map_path"] == str(fixtures.map_path) and exported["catalog_complete"],
        "地图导出丢来源状态",
    )
    _require(
        len(exported["records"]) == 1 and exported["records"][0]["id"] == "yM01",
        "地图导出丢筛选对象",
    )
    _require(exported["map_scopes"][0]["sha256"] == digest, "地图导出丢范围 SHA")
    _require(
        any(
            value["key"] == "ides" and value["value"] == fixtures.descriptions[0]
            for value in exported["records"][0]["values"]
        ),
        "地图导出截断多行字段",
    )
    _set_entry(window._source_entry, "")
    _set_entry(window._query_entry, "")
    window._clear_source_button.invoke()
    _wait_for(
        app,
        lambda: window._result is not selected and not window._busy,
        "清空地图回到基础目录",
        errors,
    )
    _require(
        window._result is not None
        and not window._result.map_path
        and not window._result.map_scopes,
        "清空地图仍显示原地图范围",
    )
    _require(window._id_tables == (str(fixtures.id_table),), "切换地图丢已选 ID 来源")


def _exercise_pack_handoff(
    app: App, fixtures: _Fixtures, owned: list[tk.Toplevel], errors: list[str]
) -> None:
    from . import gui_reference_catalog as reference
    from .gui_export_actions import save_last_pack_dir
    from .gui_pack_query import _PackQueryWindow

    save_last_pack_dir(str(fixtures.unrelated_pack))
    window = reference.ReferenceCatalogWindow(app, fixtures.pack_root, id_tables=())
    owned.append(window)
    for entry in (
        window._map_entry,
        window._profile_entry,
        window._build_entry,
        window._source_entry,
        window._query_entry,
    ):
        _set_entry(entry, "")
    window._kind.set("objects")
    window._category.set("物品")
    _set_entry(window._query_entry, '="yP01"')
    _wait_for(
        app,
        lambda: window._result is not None and not window._busy,
        "实际知识包及直接子章查询",
        errors,
    )
    result = window._result
    _require(result is not None and len(result.records) == 2, "根包和子章同码证据丢失")
    assert result is not None
    for scope, expected_text, forbidden in (
        (fixtures.pack_root, "根包证据", "禁止串入的另包"),
        (fixtures.pack_child, "章一证据", "根包证据"),
    ):
        index = next(
            i for i, record in enumerate(result.records) if record.scope == str(scope)
        )
        window._list.selection_clear(0, "end")
        window._list.selection_set(index)
        window._list.event_generate("<<ListboxSelect>>", when="tail")
        _wait_for(app, lambda: window._render_id is None, "绑定选中包范围", errors)
        previous = set(window.winfo_children()) | set(app.winfo_children())
        window._query_selected()
        opened: list[_PackQueryWindow] = []

        def find_window() -> bool:
            opened[:] = [
                child
                for child in (*window.winfo_children(), *app.winfo_children())
                if child not in previous and isinstance(child, _PackQueryWindow)
            ]
            return len(opened) == 1

        _wait_for(app, find_window, "实际打开范围绑定的包查询窗口", errors)
        query = opened[0]
        owned.append(query)
        _require(Path(query._pack_dir) == scope, "包查询串入其他包或父级范围")
        query._run(query._mode.get())
        _wait_for(
            app,
            lambda: expected_text in query._output.get("1.0", "end-1c"),
            "实际执行范围绑定的完整对象查询",
            errors,
        )
        output = query._output.get("1.0", "end-1c")
        _require(
            forbidden not in output and "禁止串入的另包" not in output,
            "包查询结果串入其他范围",
        )
        query.destroy()


def _exercise_save(
    app: App, fixtures: _Fixtures, owned: list[tk.Toplevel], errors: list[str]
) -> None:
    from . import gui_save_workspace as saves

    window = saves.open_save_workspace(
        app, initial_path=str(fixtures.save_root), map_data=None
    )
    owned.append(window)
    window.map_var.set("")
    window.query_var.set("")
    window.kind_var.set("全部")
    window.limit_var.set("0")
    _wait_for(
        app,
        lambda: window._selection is not None and len(window._row_records) == 2,
        "无地图存档目录全量读取",
        errors,
    )
    report = window._report
    _require(
        report is not None and report.complete and not report.map_associated,
        "存档未独立完整读取",
    )
    assert report is not None
    _require(len(report.files) == 2, "存档目录文件数错误")
    row, record = next(
        (key, row)
        for key, row in window._row_records.items()
        if row.relative_path == "alpha.txt"
    )
    digest = hashlib.sha256(fixtures.payloads[fixtures.save_text]).hexdigest()
    _require(
        record.sha256 == digest and record.text_carriers and record.codes,
        "存档载体/码/SHA 缺失",
    )
    _require(
        all(carrier.byte_offset is not None for carrier in record.text_carriers),
        "存档载体缺原字节偏移",
    )
    window.tree.selection_set(row)
    window.tree.event_generate("<<TreeviewSelect>>", when="tail")
    _wait_for(
        app,
        lambda: (
            digest in window.details.get("1.0", "end-1c")
            and "byte_offset" in window.details.get("1.0", "end-1c")
        ),
        "存档文件完整详情",
        errors,
    )
    _require(
        window.details.get("1.0", "end-1c") == window._detail_text, "存档详情未完整渲染"
    )
    query = fixtures.marker + " && alpha"
    window.query_var.set(query)
    window.search()
    _wait_for(
        app,
        lambda: (
            window._selection is not None
            and window._selection.query == query
            and len(window._row_records) == 1
        ),
        "存档 Boolean 结构检索",
        errors,
    )
    _require(
        window._selection is not None and window._selection.matched_files == 1,
        "存档查询未选完整文件",
    )
    destination = fixtures.root / "exports" / "save-report.json"
    with _dialog_response(saves.filedialog, "asksaveasfilename", str(destination)):
        window.export_button.invoke()
    _wait_for(
        app,
        lambda: destination.is_file() and "已导出" in str(window.status.cget("text")),
        "存档 GUI 完整导出",
        errors,
    )
    exported = _read_json(destination)
    _require(exported["map_association"] == "not_performed", "存档导出误称已关联地图")
    _require(
        exported["selection"]["total_files"] == 2
        and exported["selection"]["selected_files"] == 1,
        "存档导出分母错误",
    )
    _require(
        len(exported["files"]) == 1 and exported["files"][0]["sha256"] == digest,
        "存档导出丢选中文件",
    )
    _require(
        exported["files"][0]["text_carriers"] and exported["files"][0]["codes"],
        "存档导出缺完整载体/码",
    )


def _exercise_utf16_save(
    app: App, fixtures: _Fixtures, owned: list[tk.Toplevel], errors: list[str]
) -> None:
    from . import gui_save_workspace as saves

    window = saves.open_save_workspace(app, initial_path="", map_data=None)
    owned.append(window)
    window.source_var.set(str(fixtures.save_utf16))
    window.map_var.set("")
    window.query_var.set("")
    window.kind_var.set("全部")
    window.limit_var.set("0")
    window.encoding_menu.set("utf-16-le")
    _wait_for(app, lambda: bool(window.winfo_ismapped()), "显示独立存档窗口", errors)
    from customtkinter import CTkButton

    refresh_button = next(
        button
        for button in window.source_entry.master.winfo_children()
        if isinstance(button, CTkButton) and button.cget("text") == "读取 / 刷新"
    )
    refresh_button.invoke()
    _wait_for(
        app,
        lambda: window._selection is not None and len(window._row_records) == 1,
        "无 BOM UTF-16LE 的显式 GUI 读取",
        errors,
    )
    report = window._report
    _require(report is not None and report.complete, "显式 UTF-16LE 存档读取不完整")
    assert report is not None
    _require(report.text_encoding == "utf-16-le", "GUI 编码选择未传递至报告")
    record = report.files[0]
    _require(record.raw_text == fixtures.save_utf16_text, "UTF-16LE 完整文本被改写")
    assert record.raw_text is not None
    _require(
        record.encoding == "utf-16-le" and len(record.text_carriers) == 2,
        "UTF-16LE 载体未完整提取",
    )
    payload = fixtures.payloads[fixtures.save_utf16]
    _require(
        record.raw_text.encode(record.encoding) == payload, "UTF-16LE 原字节不可恢复"
    )
    _require(
        all(carrier.byte_offset is not None for carrier in record.text_carriers),
        "UTF-16LE 载体缺源字节偏移",
    )
    row = next(iter(window._row_records))
    window.tree.selection_set(row)
    window.tree.event_generate("<<TreeviewSelect>>", when="tail")
    _wait_for(
        app,
        lambda: "utf-16-le" in window.details.get("1.0", "end-1c"),
        "UTF-16LE 编码证据展示",
        errors,
    )
    destination = fixtures.root / "exports" / "save-utf16le.json"
    with _dialog_response(saves.filedialog, "asksaveasfilename", str(destination)):
        window.export_button.invoke()
    _wait_for(
        app,
        lambda: destination.is_file() and "已导出" in str(window.status.cget("text")),
        "UTF-16LE GUI 完整导出",
        errors,
    )
    exported = _read_json(destination)
    _require(exported["text_encoding"] == "utf-16-le", "导出丢失编码选择")
    parsed = exported["files"][0]
    _require(
        parsed["raw_text"] == fixtures.save_utf16_text
        and parsed["encoding"] == "utf-16-le",
        "导出后重解析丢失 UTF-16LE 完整文本",
    )
    _require(
        parsed["text_decoding"]["bom_hex"] == ""
        and parsed["text_decoding"]["byte_roundtrip"],
        "导出没有明确无 BOM 及字节可逆证据",
    )
    _require(
        len(parsed["text_carriers"]) == 2 and len(parsed["codes"]) == 2,
        "导出丢失 UTF-16LE 两条载体或码",
    )
    window.destroy()
    reopened = saves.open_save_workspace(app, initial_path="", map_data=None)
    owned.append(reopened)
    _require(reopened.encoding_var.get() == "utf-16-le", "关闭重开丢失显式编码选择")
    _require(
        reopened.source_var.get() == str(fixtures.save_utf16), "关闭重开丢失存档来源"
    )


def _check_hotkey_profiles(inspection, payload: bytes) -> None:
    _require(
        inspection.inspection_complete and not inspection.input_error,
        "键位方案检查不完整",
    )
    _require(
        inspection.source.stable and not inspection.runtime_verified,
        "静态方案来源状态错误",
    )
    _require(
        inspection.source.sha256 == hashlib.sha256(payload).hexdigest(),
        "键位来源 SHA 错误",
    )
    _require(
        base64.b64decode(inspection.source.raw_base64) == payload,
        "键位来源原字节被改写",
    )
    _require(
        inspection.profiles_total == 2 and len(inspection.profiles) == 2,
        "键位方案数错误",
    )
    _require(
        sum(len(profile.bindings) for profile in inspection.profiles) == 2,
        "原声明两绑定被推导条目替换",
    )
    _require(
        all(
            len(profile.compatibility_bindings) == 42 for profile in inspection.profiles
        ),
        "每方案42条兼容推导不完整",
    )


def _exercise_hotkeys(
    app: App, fixtures: _Fixtures, owned: list[tk.Toplevel], errors: list[str]
) -> None:
    from . import gui_hotkey_config as hotkeys
    from .hotkey_config_models import HotkeyDiff, HotkeyInspection

    window = hotkeys._HotkeyConfigDialog(app)
    owned.append(window)
    window._path_var.set(str(fixtures.hotkeys_old))
    window._compare_var.set("")
    window._profile_var.set("")
    window._mode.set("检查详情")
    window._run_button.invoke()
    _wait_for(app, lambda: not window._busy, "键位方案真实后台检查", errors)
    _require(
        isinstance(window._result, HotkeyInspection) and window._result_fresh,
        "键位检查未交付",
    )
    inspection = window._result
    assert isinstance(inspection, HotkeyInspection)
    _check_hotkey_profiles(inspection, fixtures.payloads[fixtures.hotkeys_old])
    text = window._output.get("1.0", "end-1c")
    _require(
        "== 原声明 ==" in text and "== 原工具兼容推导 ==" in text,
        "声明与推导没有分开呈现",
    )
    for profile in inspection.profiles:
        _require(
            all(
                binding.binding_id in text for binding in profile.compatibility_bindings
            ),
            "键位检查正文丢推导记录",
        )
    window._mode.set("完整 JSON")
    window._switch_mode("完整 JSON")
    displayed = json.loads(window._output.get("1.0", "end-1c"))
    _require(
        displayed["report_type"] == "hotkeys_inspection"
        and not displayed["runtime_verified"],
        "键位完整 JSON 不是静态检查",
    )
    destination = fixtures.root / "exports" / "hotkeys-inspect.json"
    with _dialog_response(hotkeys.filedialog, "asksaveasfilename", str(destination)):
        window._export_button.invoke()
    _wait_for(
        app,
        lambda: destination.is_file() and not window._busy,
        "键位 GUI 检查导出",
        errors,
    )
    _require(_read_json(destination) == displayed, "键位导出与完整检查 JSON 不一致")
    window._path_var.set(str(fixtures.hotkeys_new))
    window._compare_var.set(str(fixtures.hotkeys_old))
    window._run_button.invoke()
    _wait_for(app, lambda: not window._busy, "键位方案真实后台比较", errors)
    difference = window._result
    _require(
        isinstance(difference, HotkeyDiff) and window._result_fresh, "键位比较未交付"
    )
    assert isinstance(difference, HotkeyDiff)
    _require(
        difference.comparison_complete
        and difference.has_changes
        and difference.differences,
        "键位比较未确认变化",
    )
    _require(
        any(
            "smartcast" in row.path and row.after == "true"
            for row in difference.differences
        ),
        "smartcast 变化未完整交付",
    )
    _check_hotkey_profiles(difference.old, fixtures.payloads[fixtures.hotkeys_old])
    _check_hotkey_profiles(difference.new, fixtures.payloads[fixtures.hotkeys_new])
    displayed = json.loads(window._output.get("1.0", "end-1c"))
    _require(
        displayed["report_type"] == "hotkeys_diff"
        and not displayed["runtime_verified"],
        "键位比较 JSON 失去静态来源",
    )
    destination = fixtures.root / "exports" / "hotkeys-diff.json"
    with _dialog_response(hotkeys.filedialog, "asksaveasfilename", str(destination)):
        window._export_button.invoke()
    _wait_for(
        app,
        lambda: destination.is_file() and not window._busy,
        "键位 GUI 比较导出",
        errors,
    )
    _require(_read_json(destination) == displayed, "键位导出丢失完整比较结构")


def exercise_offline_workspaces(app: App) -> str:
    """Exercise real GUI workflows before a map is loaded, using private assets."""
    _require(
        threading.current_thread() is threading.main_thread(), "必须在 Tk 主线程验收"
    )
    _require(app.map_data is None, "离线验收必须在主地图载入前执行")
    from .gui_offline_acceptance_2122 import exercise_upgrade_metadata
    from .gui_offline_acceptance_mpq import exercise_archive_recovery
    from .gui_offline_acceptance_diagnostics import exercise_script_diagnostics
    from .gui_offline_acceptance_v12 import (
        V12_CASE_NAMES,
        exercise_loadout_workbench,
        exercise_source_calls,
        exercise_unicode_sources,
        expected_export_names,
    )

    fixtures = _create_fixtures()
    inventory: dict[str, Any] = {
        "schema_version": 1,
        "input_kind": "explicitly-authored-synthetic-fixtures",
        "root": str(fixtures.root),
        "cases": [
            {"name": name, "status": "not-run"}
            for name in (
                "external-id-full-records",
                "direct-map-multiselect-json-tsv-md",
                "pack-scope-real-query-handoff",
                "save-independent-full-files",
                "save-explicit-utf16le-no-bom",
                "hotkeys-complete-static-projections",
                "upgrade-explicit-category-full-exports",
                "archive-all-export-exact-recovered-members",
                "script-diagnostics-visible-complete-evidence",
                *V12_CASE_NAMES,
                "source-bytes-and-metadata-unchanged",
                "owned-window-teardown",
            )
        ],
    }
    owned: list[tk.Toplevel] = []
    state = app.state()

    def fail_dialog(title: str, message: str, **_kwargs: object) -> None:
        raise RuntimeError(f"离线 GUI 错误弹窗 {title}: {message}")

    environment = {
        "GAMEXRAY_CACHE_DIR": str(fixtures.root / "runtime-cache"),
        "GAMEXRAY_GUI_CONFIG_PATH": str(fixtures.root / "runtime-cache" / "gui.json"),
    }
    with (
        _temporary_environment(environment),
        _temporary_attribute(messagebox, "showerror", fail_dialog),
        _capture_callbacks(app) as errors,
    ):
        try:
            app.deiconify()
            app.lift()
            for case, operation in zip(
                inventory["cases"][:-2],
                (
                    _exercise_reference,
                    _exercise_map_reference,
                    _exercise_pack_handoff,
                    _exercise_save,
                    _exercise_utf16_save,
                    _exercise_hotkeys,
                    exercise_upgrade_metadata,
                    exercise_archive_recovery,
                    exercise_script_diagnostics,
                    exercise_source_calls,
                    exercise_loadout_workbench,
                    exercise_unicode_sources,
                ),
                strict=True,
            ):
                case["status"] = "running"
                try:
                    operation(app, fixtures, owned, errors)
                    if operation is exercise_unicode_sources:
                        actual_exports = {
                            path.relative_to(fixtures.root / "exports").as_posix()
                            for path in (fixtures.root / "exports").rglob("*")
                            if path.is_file()
                        }
                        inventory["exports"] = sorted(actual_exports)
                        _require(
                            actual_exports == expected_export_names(),
                            "原有和新增 GUI 导出清单不完整或出现额外文件",
                        )
                except Exception as exc:  # BROAD_EXCEPT_OK - persist the exact failed acceptance case before re-raising.
                    case.update(status="failed", error=f"{type(exc).__name__}: {exc}")
                    raise
                case["status"] = "accepted"
        finally:
            for window in reversed(owned):
                try:
                    if window.winfo_exists():
                        window.destroy()
                except Exception as exc:  # BROAD_EXCEPT_OK - close every owned window and fail with all cleanup evidence.
                    errors.append(f"关闭自有窗口 {type(window).__name__}: {exc}")
            try:
                _pump_after_close(app, errors)
            finally:
                input_errors: list[str] = []
                for path, payload in fixtures.payloads.items():
                    try:
                        preserved = (
                            path.read_bytes() == payload
                            and _identity(path) == fixtures.identities[path]
                        )
                    except OSError as exc:
                        input_errors.append(
                            f"源输入无法复核: {path}: {type(exc).__name__}: {exc}"
                        )
                    else:
                        if not preserved:
                            input_errors.append(
                                f"源输入字节或完整文件元数据被修改: {path}"
                            )
                inventory["cases"][-2]["status"] = (
                    "failed" if input_errors else "accepted"
                )
                inventory["input_errors"] = input_errors
                errors.extend(input_errors)
                if state == "withdrawn":
                    app.withdraw()
                elif state == "iconic":
                    app.iconify()
                inventory["cases"][-1]["status"] = "failed" if errors else "accepted"
                for case in inventory["cases"]:
                    if case["status"] == "running":
                        case["status"] = "failed"
                inventory["callback_errors"] = list(errors)
                inventory["accepted"] = sum(
                    case["status"] == "accepted" for case in inventory["cases"]
                )
                inventory["failed"] = sum(
                    case["status"] == "failed" for case in inventory["cases"]
                )
                inventory["not_run"] = sum(
                    case["status"] == "not-run" for case in inventory["cases"]
                )
                (fixtures.root / "acceptance-inventory.json").write_text(
                    json.dumps(inventory, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
        _raise_callback_errors(errors)
    return (
        "offline-workspaces=reference/map-reference/pack-handoff/save/utf16-save/hotkeys/upgrade/archive/diagnostics/calls/loadout/unicode; offline-id-records=2; "
        "offline-map-records=2; offline-map-filtered=1; "
        "offline-save-files=2; hotkeys-declared-bindings=2; hotkeys-projection=2x42; "
        "offline-selected-exports=json/tsv/md; offline-pack-handoffs=2; offline-utf16-carriers=2; "
        "upgrade-field-records=37; upgrade-field-exports=json/tsv; archive-recovered-members=7; "
        "diagnostic-maps=4; diagnostic-groups=4; diagnostic-mutations=4; diagnostic-static-only=True; "
        "calls-source-records=10; loadout-gui-exports=6; unicode-wts-carriers=2; w3f-version=3; "
        "legacy-gui-exports=22; resource-hint-catalogs=1; v12-gui-exports=8; "
        f"offline-gui-exports={sum(path.is_file() for path in (fixtures.root / 'exports').rglob('*'))}; "
        f"offline-acceptance-cases={len(inventory['cases'])}; hotkeys-runtime-verified=False; "
        f"offline-artifacts={fixtures.root}"
    )


__all__ = ("exercise_offline_workspaces",)
