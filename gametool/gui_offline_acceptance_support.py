"""Shared real-Tk acceptance primitives and authored inert MPQ construction."""

from __future__ import annotations
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import csv
import json
import os
from pathlib import Path
import re
import struct
from time import monotonic, sleep
import tkinter as tk
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
    map_path: Path
    map_names: tuple[str, str]
    save_root: Path
    save_text: Path
    save_utf16: Path
    save_utf16_text: str
    pack_root: Path
    pack_child: Path
    unrelated_pack: Path
    hotkeys_old: Path
    hotkeys_new: Path
    payloads: dict[Path, bytes]
    identities: dict[Path, tuple[int, ...]]


def _fixture_mpq(members: dict[str, bytes], *, listed: bool = True) -> bytes:
    """Encode a tiny real MPQ for source and frozen acceptance without test imports."""
    from .mpq_crypto import CRYPT_TABLE, hash_name_bytes

    def encrypt(data: bytes, seed1: int) -> bytes:
        seed2 = 0xEEEEEEEE
        encrypted: list[int] = []
        for (value,) in struct.iter_unpack("<I", data):
            seed2 = (seed2 + CRYPT_TABLE[0x400 + (seed1 & 0xFF)]) & 0xFFFFFFFF
            encrypted.append(value ^ ((seed1 + seed2) & 0xFFFFFFFF))
            seed1 = (
                ((~seed1 & 0xFFFFFFFF) << 21) + 0x11111111 | (seed1 >> 11)
            ) & 0xFFFFFFFF
            seed2 = (value + seed2 + (seed2 << 5) + 3) & 0xFFFFFFFF
        return struct.pack(f"<{len(encrypted)}I", *encrypted)

    if listed:
        members = {
            **members,
            "(listfile)": "\r\n".join((*members, "(listfile)")).encode(),
        }
    hash_count = 1
    while hash_count < len(members) * 2:
        hash_count *= 2
    empty = b"\xff" * 16
    hashes = [empty] * hash_count
    blocks: list[bytes] = []
    data_pos = 32 + 16 * (hash_count + len(members))
    for index, (name, payload) in enumerate(members.items()):
        encoded = name.encode("utf-8")
        slot = hash_name_bytes(encoded, 0) & (hash_count - 1)
        while hashes[slot] != empty:
            slot = (slot + 1) & (hash_count - 1)
        hashes[slot] = struct.pack(
            "<IIHHI",
            hash_name_bytes(encoded, 1),
            hash_name_bytes(encoded, 2),
            0,
            0,
            index,
        )
        blocks.append(
            struct.pack("<IIII", data_pos, len(payload), len(payload), 0x81000000)
        )
        data_pos += len(payload)
    return b"".join(
        (
            struct.pack(
                "<4sIIHHIIII",
                b"MPQ\x1a",
                32,
                data_pos,
                0,
                3,
                32,
                32 + hash_count * 16,
                hash_count,
                len(members),
            ),
            encrypt(b"".join(hashes), hash_name_bytes(b"(hash table)", 3)),
            encrypt(b"".join(blocks), hash_name_bytes(b"(block table)", 3)),
            *members.values(),
        )
    )


def _set_entry(entry, value: str) -> None:
    entry.delete(0, "end")
    entry.insert(0, value)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"报告不是 JSON 对象: {path}")
    return value


def _read_selection_export(path: Path) -> dict[str, Any]:
    """Reparse the public report bytes instead of trusting the export callback."""
    from .batch_tsv import decode_tsv_cell
    from .csv_fields import full_csv_fields

    if path.suffix == ".json":
        return _read_json(path)
    if path.suffix == ".tsv":
        with path.open(encoding="utf-8", newline="") as source, full_csv_fields():
            rows = [
                {key: decode_tsv_cell(value) for key, value in row.items()}
                for row in csv.DictReader(source, delimiter="\t", strict=True)
            ]
        _require(rows and rows[0]["记录类型"] == "catalog", "选中 TSV 缺目录上下文")
        context = json.loads(rows[0]["完整证据_json"])
        context["records"] = [
            json.loads(row["完整证据_json"])
            for row in rows[1:]
            if row["记录类型"] == "record"
        ]
        _require(len(rows) == len(context["records"]) + 1, "选中 TSV 存在未解析记录")
        return context
    markdown = path.read_text(encoding="utf-8")
    blocks = re.findall(r"(?m)^```json\n(.*?)\n```$", markdown, re.DOTALL)
    reports = [json.loads(block) for block in blocks]
    contexts = [
        report
        for report in reports
        if isinstance(report, dict) and "selection" in report
    ]
    _require(len(contexts) == 1, "选中 Markdown 缺唯一完整来源上下文")
    records = [
        report
        for report in reports
        if isinstance(report, dict) and "kind" in report and "id" in report
    ]
    _require(len(reports) == len(records) + 1, "选中 Markdown 存在未解析 JSON 块")
    contexts[0]["records"] = records
    return contexts[0]


@contextmanager
def loaded_acceptance_map(app: App, path: Path) -> Iterator[None]:
    """Use the real loader/render path, then release only this authored map."""
    from .gui_loader import load_path_payload

    _require(app.map_data is None, "作者地图验收需要初始未载图状态")
    payload = load_path_payload(str(path))
    try:
        app._on_loaded(
            payload.active,
            payload.commands,
            payload.recipes,
            payload.resolver,
            payload.views,
            payload.campaign_path,
        )
        app.update_idletasks()
        app.update()
        yield
    finally:
        if app.icons is not None and hasattr(app.icons, "close"):
            app.icons.close()
        app.map_data = None
        app.icons = None
        app._campaign_views = None
        app._campaign_path = None
        app.commands = []
        app.recipes = []
        app._release_unused_gui_maps()
        app._refresh_editor_reports()
