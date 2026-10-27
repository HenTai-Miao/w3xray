"""The read-only workbench's public handoffs keep category and map identity."""

from __future__ import annotations

from types import ModuleType, SimpleNamespace
from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog
from typing import Any

import pytest

from gametool import app, gui_topbar
from gametool import gui_export_actions, gui_pack_query


def test_open_local_partial_pack_without_map_keeps_explicit_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GAMEXRAY_CACHE_DIR", str(tmp_path / "cache"))
    pack = tmp_path / "legacy-pack"
    pack.mkdir()
    (pack / "物品.tsv").write_text("I001\t旧包物品\n", encoding="utf-8")
    host = SimpleNamespace(map_data=None)
    calls: list[dict[str, Any]] = []

    def open_dialog(parent, provider, ensure, **kwargs: Any) -> None:
        calls.append(
            {"parent": parent, "provider": provider, "ensure": ensure, **kwargs}
        )

    monkeypatch.setattr(filedialog, "askdirectory", lambda **_kwargs: str(pack))
    monkeypatch.setattr(gui_pack_query, "open_pack_query_dialog", open_dialog)

    selected = gui_topbar._open_local_pack_query(
        host, prefill="id:=I001", prefill_command="item"
    )

    assert selected == str(pack)
    assert len(calls) == 1
    assert calls[0]["parent"] is host
    assert calls[0]["provider"]() == str(pack)
    assert calls[0]["prefill"] == "id:=I001"
    assert calls[0]["prefill_command"] == "item"
    assert host._last_pack_dir == gui_export_actions.load_last_pack_dir() == str(pack)
    host.map_data = object()
    assert calls[0]["provider"]() == str(pack)


@pytest.mark.parametrize("failure", ("cancel", "missing", "picker", "window"))
def test_local_pack_cancel_and_errors_preserve_previous_memory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    monkeypatch.setenv("GAMEXRAY_CACHE_DIR", str(tmp_path / "cache"))
    previous = tmp_path / "previous"
    previous.mkdir()
    selected = tmp_path / "selected"
    if failure != "missing":
        selected.mkdir()
    gui_export_actions.save_last_pack_dir(str(previous))
    host = SimpleNamespace(map_data=None, _last_pack_dir=str(previous))
    errors: list[tuple[object, ...]] = []
    opened: list[str] = []

    def choose(**kwargs: Any) -> str:
        assert kwargs["initialdir"] == str(previous)
        if failure == "picker":
            raise tk.TclError("directory picker unavailable")
        return "" if failure == "cancel" else str(selected)

    def open_dialog(_parent, provider, _ensure, **_kwargs: Any) -> None:
        opened.append(provider())
        raise tk.TclError("query window unavailable")

    monkeypatch.setattr(filedialog, "askdirectory", choose)
    monkeypatch.setattr(gui_pack_query, "open_pack_query_dialog", open_dialog)
    monkeypatch.setattr(
        gui_topbar.messagebox, "showerror", lambda *args, **_kwargs: errors.append(args)
    )

    assert gui_topbar._open_local_pack_query(host) is None
    assert host._last_pack_dir == str(previous)
    assert gui_export_actions.load_last_pack_dir() == str(previous)
    assert len(opened) == (1 if failure == "window" else 0)
    assert len(errors) == (0 if failure == "cancel" else 1)


def test_local_pack_memory_failure_does_not_block_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pack = tmp_path / "partial-pack"
    pack.mkdir()
    host = SimpleNamespace(map_data=None)
    opened: list[str] = []

    def cannot_save(_directory: str) -> None:
        raise OSError("read-only memo")

    monkeypatch.setattr(filedialog, "askdirectory", lambda **_kwargs: str(pack))
    monkeypatch.setattr(gui_export_actions, "load_last_pack_dir", lambda: "")
    monkeypatch.setattr(gui_export_actions, "save_last_pack_dir", cannot_save)
    monkeypatch.setattr(
        gui_pack_query,
        "open_pack_query_dialog",
        lambda _parent, provider, _ensure, **_kwargs: opened.append(provider()),
    )

    assert gui_topbar._open_local_pack_query(host) == str(pack)
    assert opened == [str(pack)]
    assert host._last_pack_dir == str(pack)


@pytest.mark.parametrize(
    ("handoff", "command", "keyword"),
    (
        ("units id:=hfoo", "units", "id:=hfoo"),
        ('item id:="I.01"', "item", 'id:="I.01"'),
        ("skills A000", "skills", "A000"),
        ("heroes H000", "heroes", "H000"),
        ("buffs B000", "buffs", "B000"),
        ("tech R000", "tech", "R000"),
        ("near -1.25 6e2 100", "near", "-1.25 6e2 100"),
        ("where I000", "where", "I000"),
        ("drop hfoo", "drop", "hfoo"),
        ("I000", "doc", "I000"),
    ),
)
def test_unbound_offline_report_selects_and_retains_pack_across_map_switch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    handoff: str,
    command: str,
    keyword: str,
) -> None:
    monkeypatch.setenv("GAMEXRAY_CACHE_DIR", str(tmp_path / "cache"))
    pack = tmp_path / "chosen-pack"
    pack.mkdir()
    captured: dict[str, Any] = {}
    queries: list[dict[str, Any]] = []
    choices: list[object] = []

    def no_map_fallback(*_args: object, **_kwargs: object) -> None:
        pytest.fail("An unbound report must never borrow the current map")

    host = SimpleNamespace(
        map_data=None,
        current_map_pack_dir=no_map_fallback,
        on_pack_query=no_map_fallback,
    )

    def choose(**kwargs: Any) -> str:
        choices.append(kwargs["parent"])
        return str(pack)

    def open_report(_parent, initial_pack, **kwargs: Any) -> None:
        assert initial_pack is None
        captured.update(kwargs)

    def open_query(_parent, provider, _ensure, **kwargs: Any) -> None:
        queries.append({"provider": provider, **kwargs})

    monkeypatch.setattr(filedialog, "askdirectory", choose)
    monkeypatch.setattr(gui_topbar, "open_live_probe_dialog", open_report)
    monkeypatch.setattr(gui_pack_query, "open_pack_query_dialog", open_query)

    gui_topbar._open_live_probe(host, auto_start=False)
    assert captured["pack_dir_provider"]() is None
    assert choices == []
    host.map_data = object()
    captured["query_callback"](handoff)
    host.map_data = object()
    captured["query_callback"](handoff)

    assert choices == [host]
    assert len(queries) == 2
    assert all(query["provider"]() == str(pack) for query in queries)
    assert all(query["prefill"] == keyword for query in queries)
    assert all(query["prefill_command"] == command for query in queries)
    assert captured["pack_dir_provider"]() == str(pack)
    assert captured["auto_start"] is False


def test_unbound_report_cancel_does_not_pick_a_later_current_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def no_map_fallback(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Cancel must not query or export a current map")

    host = SimpleNamespace(
        map_data=None,
        current_map_pack_dir=no_map_fallback,
        on_pack_query=no_map_fallback,
    )
    monkeypatch.setattr(filedialog, "askdirectory", lambda **_kwargs: "")
    monkeypatch.setattr(gui_export_actions, "load_last_pack_dir", lambda: "")
    monkeypatch.setattr(
        gui_topbar,
        "open_live_probe_dialog",
        lambda _parent, _pack_dir, **kwargs: captured.update(kwargs),
    )
    monkeypatch.setattr(gui_pack_query, "open_pack_query_dialog", no_map_fallback)

    gui_topbar._open_live_probe(host, auto_start=False)
    host.map_data = object()
    captured["query_callback"]("where I001")

    assert captured["pack_dir_provider"]() is None


@pytest.mark.parametrize(
    ("handoff", "command", "keyword"),
    (
        ("units hfoo", "units", "hfoo"),
        ("item I000", "item", "I000"),
        ("skills A000", "skills", "A000"),
        ("heroes H000", "heroes", "H000"),
        ("buffs B000", "buffs", "B000"),
        ("tech R000", "tech", "R000"),
        ("near -1.25 6e2", "near", "-1.25 6e2"),
        ("where I000", "where", "I000"),
        ("drop hfoo", "drop", "hfoo"),
        ("I000", "doc", "I000"),
    ),
)
def test_live_handoff_keeps_category_and_original_map(
    monkeypatch: pytest.MonkeyPatch, handoff: str, command: str, keyword: str
) -> None:
    original_map = object()
    captured: dict[str, Any] = {}
    queries: list[dict[str, object]] = []
    host = SimpleNamespace(
        map_data=original_map,
        current_map_pack_dir=lambda source: (
            "bound-pack" if source is original_map else None
        ),
        on_pack_query=lambda **kwargs: queries.append(kwargs),
    )

    def open_dialog(_parent: object, _pack_dir: str, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(gui_topbar, "open_live_probe_dialog", open_dialog)
    gui_topbar._open_live_probe(host)
    host.map_data = object()
    captured["query_callback"](handoff)

    assert queries == [
        {
            "prefill": keyword,
            "prefill_command": command,
            "source_map": original_map,
        }
    ]
    assert captured["pack_dir_provider"]() == "bound-pack"
    assert captured["auto_start"] is True


def test_offline_report_entry_does_not_schedule_a_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    host = SimpleNamespace(map_data=None, current_map_pack_dir=lambda _source: None)

    def open_dialog(_parent: object, _pack_dir: str | None, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(gui_topbar, "open_live_probe_dialog", open_dialog)

    gui_topbar._open_live_probe(host, auto_start=False)

    assert captured["auto_start"] is False


@pytest.mark.parametrize("has_map", (False, True))
def test_reference_catalog_opens_offline_or_with_only_current_pack(
    monkeypatch: pytest.MonkeyPatch, has_map: bool
) -> None:
    calls: list[tuple[object, object]] = []
    source = object() if has_map else None
    host = SimpleNamespace(
        map_data=source,
        current_map_pack_dir=lambda value: (
            "current-pack" if value is source and value is not None else None
        ),
    )
    module = ModuleType("gametool.gui_reference_catalog")
    setattr(
        module,
        "open_reference_catalog_dialog",
        lambda parent, pack_dir=None: calls.append((parent, pack_dir)),
    )
    monkeypatch.setitem(sys.modules, module.__name__, module)

    gui_topbar._open_reference_catalog(host)

    assert calls == [(host, "current-pack" if has_map else None)]


@pytest.mark.parametrize(
    ("command", "module_name", "function"),
    (
        ("reference", "gametool.reference_cli", "run_reference_cli"),
        ("live-report", "gametool.live_report_cli", "run_live_report_cli"),
    ),
)
def test_offline_dispatch_forwards_arguments_and_exit_code(
    monkeypatch: pytest.MonkeyPatch, command: str, module_name: str, function: str
) -> None:
    arguments: list[tuple[str, ...]] = []
    module = ModuleType(module_name)

    def run(argv: tuple[str, ...]) -> int:
        arguments.append(argv)
        return 2

    setattr(module, function, run)
    monkeypatch.setitem(sys.modules, module_name, module)
    monkeypatch.setattr(sys, "argv", ["gamexray", command, "--json", "literal value"])

    with pytest.raises(SystemExit) as error:
        app.main()

    assert error.value.code == 2
    assert arguments == [("--json", "literal value")]
