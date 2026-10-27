"""Current-map query routes never adopt another map's recent export."""

from __future__ import annotations

from pathlib import Path

import pytest

from gametool.api import GameObject, MapData
import gametool.gui_export_actions as exports
import gametool.gui_pack_query as query_gui
import gametool.gui_topbar as topbar
import gametool.gui_shell_object_panel as object_panel
from gametool.knowledge_results import KnowledgeWriteItem, KnowledgeWriteReport
from tests.test_release_gui_actions import _ActionHost


class _Selection:
    def __init__(self, text: str) -> None:
        self.text = text

    def get(self, _start, _end) -> str:
        return self.text


def _prepare_exports(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    exported: list[MapData] = []
    opened: list[tuple[str | None, str, str]] = []
    report = KnowledgeWriteReport((KnowledgeWriteItem("地图信息.txt", True, 1, None),))

    def write(md, *_args, **_kwargs):
        exported.append(md)
        return report

    def fresh_dir(*_args, **_kwargs):
        path = tmp_path / f"pack-{len(exported)}"
        path.mkdir(exist_ok=True)
        return str(path)

    def open_query(_host, provider, _ensure, prefill="", prefill_command=""):
        opened.append((provider(), prefill, prefill_command))

    monkeypatch.setattr(exports, "write_knowledge_pack_family_report", write)
    monkeypatch.setattr(exports, "tmp_extract_dir", fresh_dir)
    monkeypatch.setattr(exports, "save_last_pack_dir", lambda _path: None)
    monkeypatch.setattr(query_gui, "open_pack_query_dialog", open_query)
    monkeypatch.setattr(topbar, "open_pack_query_dialog", open_query, raising=False)
    return exported, opened


def test_current_map_handoff_exports_before_querying_a_previous_maps_pack(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host = _ActionHost()
    previous = tmp_path / "previous-map-pack"
    previous.mkdir()
    host._last_pack_dir = str(previous)
    monkeypatch.setattr(exports, "load_last_pack_dir", lambda: str(previous))
    exported, opened = _prepare_exports(monkeypatch, tmp_path)
    try:
        topbar._code_selected(host, _Selection("I001"))

        assert opened == []
        assert exported == [host.map_data]
        host.pump()

        assert opened == [(str(tmp_path / "pack-0"), "I001", "doc")]
        assert host.current_map_pack_dir() == str(tmp_path / "pack-0")
    finally:
        host._shutdown_gui_worker_host(1)


def test_current_pack_binding_uses_loaded_map_identity_and_resumes_one_export(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host = _ActionHost()
    exported, opened = _prepare_exports(monkeypatch, tmp_path)
    monkeypatch.setattr(host, "_show_pack_result", lambda *_args: None)
    first = host.map_data
    assert first is not None
    try:
        host.on_export_pack()
        host.pump()
        assert host.current_map_pack_dir() == str(tmp_path / "pack-0")

        # Campaign children from different containers may have the same inner path.
        second = MapData(path=first.path, name="另一张同路径地图")
        host.map_data = second
        assert host.current_map_pack_dir() is None
        host.on_pack_query(prefill="near 1 2 100", prefill_command="near")
        host.on_pack_query(prefill="I002", prefill_command="where")
        assert exported == [first, second]
        assert opened == []

        host.pump()

        assert opened == [(str(tmp_path / "pack-1"), "I002", "where")]
        assert host.current_map_pack_dir() == str(tmp_path / "pack-1")
    finally:
        host._shutdown_gui_worker_host(1)


def test_export_result_after_map_switch_does_not_resume_old_map_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host = _ActionHost()
    exported, opened = _prepare_exports(monkeypatch, tmp_path)
    monkeypatch.setattr(host, "_show_pack_result", lambda *_args: None)
    try:
        host.on_pack_query(prefill="I001", prefill_command="doc")
        assert len(exported) == 1
        host.map_data = MapData(path="next.w3x", name="下一张地图")

        host.pump()

        assert opened == []
        assert host.current_map_pack_dir() is None
        assert host._last_pack_dir == str(tmp_path / "pack-0")
    finally:
        host._shutdown_gui_worker_host(1)


def test_object_handoff_uses_current_map_export_and_preserves_category_route(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host = _ActionHost()
    _exported, opened = _prepare_exports(monkeypatch, tmp_path)
    monkeypatch.setattr(
        host,
        "_selected_detail_object",
        GameObject("单位", "w3u", "n001", "hfoo", "单位", True),
        raising=False,
    )
    try:
        object_panel._pack_query_selected(host, "where")
        assert opened == []
        host.pump()

        assert opened == [(str(tmp_path / "pack-0"), "n001", "drop")]
    finally:
        host._shutdown_gui_worker_host(1)


def test_live_probe_routes_and_names_use_its_current_map_binding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host = _ActionHost()
    exported, opened = _prepare_exports(monkeypatch, tmp_path)
    probe = {}

    def open_probe(_app, pack_dir, **kwargs):
        probe.update(pack_dir=pack_dir, **kwargs)

    monkeypatch.setattr(topbar, "open_live_probe_dialog", open_probe)
    try:
        topbar._open_live_probe(host)
        assert probe["pack_dir"] is None
        assert probe["pack_dir_provider"]() is None
        probe["query_callback"]("near 1 2 100")
        host.pump()
        assert opened == [(str(tmp_path / "pack-0"), "near 1 2 100", "near")]
        assert probe["pack_dir_provider"]() == str(tmp_path / "pack-0")

        host.map_data = MapData(path="other.w3x", name="其他地图")
        assert probe["pack_dir_provider"]() is None
        probe["query_callback"]("where I001")
        assert len(exported) == 1
        assert len(opened) == 1
        assert "地图已切换" in host.status.values["text"]
    finally:
        host._shutdown_gui_worker_host(1)


def test_failed_auto_export_keeps_recent_asset_and_can_retry_current_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host = _ActionHost()
    _exported, opened = _prepare_exports(monkeypatch, tmp_path)
    failure = KnowledgeWriteReport(
        (KnowledgeWriteItem("地图信息.txt", False, 0, "denied"),)
    )
    monkeypatch.setattr(host, "_show_pack_result", lambda *_args: None)
    with monkeypatch.context() as failing:
        failing.setattr(
            exports, "write_knowledge_pack_family_report", lambda *_args, **_kw: failure
        )
        host.on_pack_query(prefill_command="list")
        host.pump()

    try:
        assert opened == []
        assert host.current_map_pack_dir() is None
        assert host._last_pack_dir == "previous-pack"
        host.on_pack_query(prefill_command="list")
        host.pump()
        assert opened == [(str(tmp_path / "pack-0"), "", "list")]
    finally:
        host._shutdown_gui_worker_host(1)
