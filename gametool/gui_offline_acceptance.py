"""Real, isolated Tk acceptance for the three map-independent workspaces."""

from __future__ import annotations

from collections.abc import Callable, Iterator
import base64
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from time import monotonic, sleep
import tkinter as tk
from tkinter import messagebox
from traceback import format_exception
from typing import Any, TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from .gui import App


_STEP_TIMEOUT_SECONDS = 45.0
_CLOSE_PUMP_SECONDS = 0.35


@contextmanager
def _temporary_attribute(
    owner: object, name: str, replacement: object
) -> Iterator[None]:
    """Restore the exact existing attribute even when the GUI action fails."""
    previous = getattr(owner, name)
    setattr(owner, name, replacement)
    try:
        yield
    finally:
        setattr(owner, name, previous)


@contextmanager
def _dialog_response(owner: object, name: str, response: object) -> Iterator[None]:
    """Answer only a file picker; parsing, workers and exports remain real."""

    def selected(*_args: object, **_kwargs: object) -> object:
        return response

    with _temporary_attribute(owner, name, selected):
        yield


@contextmanager
def _temporary_environment(values: dict[str, str]) -> Iterator[None]:
    """Restore touched keys, preserving absent, empty and configured values."""
    previous = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class _CallbackErrors(list[str]):
    """Remember callback owners before Tk deletes their registered commands."""

    def __init__(self) -> None:
        super().__init__()
        self.owners: dict[str, str] = {}

    def remember(self, app: App) -> None:
        pending: list[tk.Misc] = [app]
        while pending:
            widget = pending.pop()
            label = f"{type(widget).__module__}.{type(widget).__name__} {widget}"
            for command in getattr(widget, "_tclCommands", ()) or ():
                self.owners[command] = label
            pending.extend(widget.children.values())


def _require(condition: object, message: str) -> None:
    if not condition:
        raise RuntimeError("离线 GUI 验收失败: " + message)


def _raise_callback_errors(errors: list[str]) -> None:
    if errors:
        raise RuntimeError("离线 GUI 回调异常:\n" + "\n\n".join(errors))


@contextmanager
def _capture_callbacks(app: App) -> Iterator[_CallbackErrors]:
    """Capture Python callbacks and Tcl background errors on this interpreter."""
    errors = _CallbackErrors()
    errors.remember(app)
    previous = app.report_callback_exception
    saved_bgerror = "::gamexray_offline_bgerror_" + uuid4().hex
    had_bgerror = bool(app.tk.call("info", "commands", "bgerror"))
    if had_bgerror:
        app.tk.call("rename", "bgerror", saved_bgerror)

    def record_python(kind, error, trace) -> None:
        errors.append("".join(format_exception(kind, error, trace)).rstrip())

    def record_tcl(message: str) -> None:
        command = message.partition('invalid command name "')[2].partition('"')[0]
        errors.append(
            "Tcl background error: "
            + message
            + "\nregistered owner: "
            + errors.owners.get(command, "not observed before destruction")
            + "\n"
            + str(app.tk.call("set", "::errorInfo"))
        )

    app.report_callback_exception = record_python
    app.tk.createcommand("bgerror", record_tcl)
    try:
        yield errors
    finally:
        app.report_callback_exception = previous
        app.tk.deletecommand("bgerror")
        if had_bgerror:
            app.tk.call("rename", saved_bgerror, "bgerror")


def _wait_for(
    app: App,
    ready: Callable[[], bool],
    label: str,
    errors: list[str],
    *,
    timeout: float = _STEP_TIMEOUT_SECONDS,
) -> None:
    deadline = monotonic() + timeout
    while True:
        if isinstance(errors, _CallbackErrors):
            errors.remember(app)
        app.update_idletasks()
        app.update()
        _raise_callback_errors(errors)
        if ready():
            return
        if monotonic() >= deadline:
            raise RuntimeError(f"离线 GUI 验收超时 ({timeout:g}s): {label}")
        sleep(0.01)


def _pump_after_close(app: App, errors: list[str]) -> None:
    """Give delayed CTk titlebar/theme callbacks time to reveal stale widgets."""
    deadline = monotonic() + _CLOSE_PUMP_SECONDS
    while monotonic() < deadline:
        if isinstance(errors, _CallbackErrors):
            errors.remember(app)
        app.update_idletasks()
        app.update()
        sleep(0.01)
    _raise_callback_errors(errors)


def _identity(path: Path) -> tuple[int, ...]:
    value = path.stat()
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_mode,
    )


@dataclass(frozen=True, slots=True)
class _Fixtures:
    root: Path
    marker: str
    id_table: Path
    id_blocks: tuple[str, str]
    descriptions: tuple[str, str]
    save_root: Path
    save_text: Path
    hotkeys_old: Path
    hotkeys_new: Path
    payloads: dict[Path, bytes]
    identities: dict[Path, tuple[int, ...]]


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
    save_root = root / "save-inputs"
    save_root.mkdir()
    save_text = save_root / "alpha.txt"
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
        id_table: b"\xef\xbb\xbf" + "".join(blocks).encode("utf-8"),
        save_text: (
            "function PreloadFiles takes nothing returns nothing\r\n"
            f'    call Preload( "-load {marker}-alpha" )\r\n'
            "endfunction\r\n"
        ).encode("utf-8"),
        save_root / "beta.ini": (
            f'[save]\r\nnote="{marker} beta 完整记录"\r\ngold=0\r\n'
        ).encode("utf-8"),
        hotkeys_old: (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        ),
        hotkeys_new: (json.dumps(changed, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        ),
    }
    for path, payload in payloads.items():
        path.write_bytes(payload)
    return _Fixtures(
        root,
        marker,
        id_table,
        blocks,
        descriptions,
        save_root,
        save_text,
        hotkeys_old,
        hotkeys_new,
        payloads,
        {path: _identity(path) for path in payloads},
    )


def _set_entry(entry, value: str) -> None:
    entry.delete(0, "end")
    entry.insert(0, value)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"报告不是 JSON 对象: {path}")
    return value


def _exercise_reference(
    app: App, fixtures: _Fixtures, owned: list[tk.Toplevel], errors: list[str]
) -> None:
    from . import gui_reference_catalog as reference

    window = reference.ReferenceCatalogWindow(app, id_tables=(str(fixtures.id_table),))
    owned.append(window)
    for entry in (
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
    fixtures = _create_fixtures()
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
            _exercise_reference(app, fixtures, owned, errors)
            _exercise_save(app, fixtures, owned, errors)
            _exercise_hotkeys(app, fixtures, owned, errors)
            for path, payload in fixtures.payloads.items():
                _require(
                    path.read_bytes() == payload
                    and _identity(path) == fixtures.identities[path],
                    f"源输入被修改: {path}",
                )
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
                if state == "withdrawn":
                    app.withdraw()
                elif state == "iconic":
                    app.iconify()
        _raise_callback_errors(errors)
    return (
        "offline-workspaces=reference/save/hotkeys; offline-id-records=2; "
        "offline-save-files=2; hotkeys-declared-bindings=2; hotkeys-projection=2x42; "
        "offline-gui-exports=4; hotkeys-runtime-verified=False; "
        f"offline-artifacts={fixtures.root}"
    )


__all__ = ("exercise_offline_workspaces",)
