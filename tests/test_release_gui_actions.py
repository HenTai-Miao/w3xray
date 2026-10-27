"""Release regressions for loaded-map actions and complete GUI handoffs."""

from __future__ import annotations

from pathlib import Path
import threading

import pytest

from gametool.api import MapData
from gametool.archive_source import BytesArchiveSource
import gametool.gui_export_actions as exports
import gametool.gui_loader_runner as loader
import gametool.gui_source_browser as browser
import gametool.gui_topbar as topbar
from gametool.gui_export_actions import ExportActionsMixin
from gametool.gui_loader import LoadedMap
from gametool.gui_lifecycle import GuiLifecycleMixin
from gametool.gui_loader_runner import BackgroundLoaderMixin
from gametool.gui_source_browser import SourceBrowserMixin
from gametool.gui_worker_registry import GuiWorkerRegistry
from gametool.knowledge_results import KnowledgeWriteItem, KnowledgeWriteReport
from tests.test_release_gui_lifecycle import _WorkerHost


class _Widget:
    def __init__(self) -> None:
        self.values = {}

    def configure(self, **values) -> None:
        self.values.update(values)


class _ActionHost(_WorkerHost, ExportActionsMixin, BackgroundLoaderMixin):
    game_data_path: str | None
    external_listfile_path: str | None
    status: _Widget  # pyright: ignore[reportIncompatibleVariableOverride] - minimal status widget fake.

    def __init__(self) -> None:
        super().__init__()
        self.map_data = MapData(path="Maps\\Chapter1.w3x", name="第一章")
        self._campaign_path = "campaign.w3n"
        self.game_data_path = None
        self.author_bundle_path = None
        self.external_listfile_path = None
        self.load_options = {}
        self.status = _Widget()  # pyright: ignore[reportIncompatibleVariableOverride] - minimal status widget fake.
        self.guide_button = _Widget()
        self.minimap_button = _Widget()
        self.opened: list[tuple[str, int, str]] = []
        self._last_pack_dir = "previous-pack"

    def _open_dir(self, out, n, kind) -> None:
        self.opened.append((out, n, kind))


def test_script_export_preparation_runs_in_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host = _ActionHost()
    host._gui_workers = GuiWorkerRegistry()
    prepared: list[int] = []
    written = threading.Event()
    monkeypatch.setattr(exports, "tmp_extract_dir", lambda *_args, **_kw: str(tmp_path))
    monkeypatch.setattr(
        exports,
        "build_readable_script_exports",
        lambda _md: prepared.append(threading.get_ident()) or (),
    )
    monkeypatch.setattr(
        exports, "write_script_exports", lambda *_args: written.set() or 0
    )
    try:
        host.on_export_scripts()
        assert written.wait(5)
        assert prepared and prepared != [threading.get_ident()]
    finally:
        assert host._shutdown_gui_worker_host(1) == ()


def test_export_preparation_failure_is_delivered_and_clears_busy_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _ActionHost()
    errors: list[str] = []

    def no_temp_dir(*_args, **_kwargs):
        raise OSError("temporary directory unavailable")

    monkeypatch.setattr(exports, "tmp_extract_dir", no_temp_dir)
    monkeypatch.setattr(
        exports.messagebox, "showerror", lambda _title, text: errors.append(text)
    )
    try:
        host.on_export_scripts()
        host.pump()
        assert errors and "temporary directory unavailable" in errors[0]
        assert host.status.values["text"] == "导出失败"
    finally:
        assert host._shutdown_gui_worker_host(1) == ()


@pytest.mark.parametrize("written", [False, True])
def test_pack_export_adopts_only_delivered_usable_results(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, written: bool
) -> None:
    host = _ActionHost()
    saved: list[str] = []
    report = KnowledgeWriteReport(
        (
            KnowledgeWriteItem(
                "地图信息.txt",
                written,
                1 if written else 0,
                None if written else "denied",
            ),
        )
    )
    monkeypatch.setattr(exports, "tmp_extract_dir", lambda *_args, **_kw: str(tmp_path))
    monkeypatch.setattr(
        exports, "write_knowledge_pack_family_report", lambda *_args, **_kw: report
    )
    monkeypatch.setattr(exports, "save_last_pack_dir", saved.append)
    monkeypatch.setattr(host, "_show_pack_result", lambda *_args: None)
    try:
        host.on_export_pack()
        assert host._last_pack_dir == "previous-pack"
        assert saved == []

        host.pump()

        assert host._last_pack_dir == (str(tmp_path) if written else "previous-pack")
        assert saved == ([str(tmp_path)] if written else [])
    finally:
        assert host._shutdown_gui_worker_host(1) == ()


def test_map_load_reads_external_listfile_in_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _ActionHost()
    host._gui_workers = GuiWorkerRegistry()
    reads: list[int] = []
    loaded = threading.Event()
    active = host.map_data
    assert active is not None
    monkeypatch.setattr(
        loader,
        "read_external_listfile",
        lambda _path: reads.append(threading.get_ident()) or (),
    )
    monkeypatch.setattr(
        loader,
        "load_path_payload",
        lambda *_args, **_kw: (
            loaded.set() or LoadedMap(active, [], [], None, None, None)
        ),
    )
    try:
        host._start_path_load("map.w3x")
        assert loaded.wait(5)
        assert reads and reads != [threading.get_ident()]
    finally:
        assert host._shutdown_gui_worker_host(1) == ()


class _Browser(_WorkerHost, SourceBrowserMixin):
    status: _Widget  # pyright: ignore[reportIncompatibleVariableOverride] - minimal status widget fake.

    def __init__(self) -> None:
        super().__init__()
        self._cur_dir = {"battle": None, "campaign": None}
        self.status = _Widget()  # pyright: ignore[reportIncompatibleVariableOverride] - minimal status widget fake.
        self.battle = None
        self.campaign = None

    def update_idletasks(self) -> None:
        pass

    def _fill_battle(self, items) -> None:
        self.battle = items

    def _fill_campaign(self, items) -> None:
        self.campaign = items


def test_startup_directory_scans_preserve_both_source_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _Browser()
    monkeypatch.setattr(
        browser, "scan_battle_maps", lambda _path: [("map.w3x", "地图")]
    )
    monkeypatch.setattr(browser.glob, "glob", lambda *_args, **_kw: [])
    try:
        host._scan_dir("battle", "battle")
        host._scan_dir("campaign", "campaign")
        host.pump()

        assert host.battle == [("map.w3x", "地图")]
        assert host.campaign == []
    finally:
        assert host._shutdown_gui_worker_host(1) == ()


def test_guide_uses_loaded_campaign_child_and_ignores_late_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gametool.guide_report as guide

    host = _ActionHost()
    rendered: list[MapData] = []
    shown: list[str] = []
    monkeypatch.setattr(
        guide,
        "format_guide_report",
        lambda md, *_args: rendered.append(md) or "chapter report",
    )
    monkeypatch.setattr(
        topbar, "_open_guide_window", lambda _host, text: shown.append(text)
    )
    try:
        topbar._show_guide(host)
        assert rendered == [host.map_data]
        host.map_data = MapData(path="next.w3x", name="下一张图")
        host.pump()
        assert shown == []

        topbar._show_guide(host)
        host.pump()
        assert shown == ["chapter report"]
    finally:
        assert host._shutdown_gui_worker_host(1) == ()


def test_minimap_uses_loaded_map_and_private_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import gametool.api as api
    import gametool.guide_minimap as minimap

    host = _ActionHost()
    rendered: list[tuple[MapData, str]] = []
    opened: list[str] = []

    def render(md, path, *_args):
        rendered.append((md, path))
        Path(path).write_bytes(b"png")
        return ("minimap rendered",)

    monkeypatch.setattr(api, "tmp_extract_dir", lambda *_args, **_kw: str(tmp_path))
    monkeypatch.setattr(minimap, "write_guide_minimap", render)
    monkeypatch.setattr(topbar.os, "startfile", opened.append, raising=False)
    try:
        topbar._render_minimap(host)
        host.pump()

        assert len(rendered) == 1
        assert rendered[0][0] is host.map_data
        assert Path(rendered[0][1]).parent == tmp_path
        assert opened == [rendered[0][1]]
        assert host.minimap_button.values["state"] == "normal"
    finally:
        assert host._shutdown_gui_worker_host(1) == ()


class _MapHost(_ActionHost, GuiLifecycleMixin):
    _campaign_path: str | None
    status: _Widget  # pyright: ignore[reportIncompatibleVariableOverride] - minimal status widget fake.
    map_label: _Widget  # pyright: ignore[reportIncompatibleVariableOverride] - minimal map label fake.

    def __init__(self) -> None:
        super().__init__()
        self.icons = None
        self.map_label = _Widget()  # pyright: ignore[reportIncompatibleVariableOverride] - minimal map label fake.
        self.recipes = []
        self._campaign_path = None
        self._campaign_views = None
        self._dir_campaigns = []
        self.destroyed = False

    def _reset_detail_panel(self) -> None:
        pass

    def _refresh_enabled_modules(self, _commands, _recipes) -> None:
        pass

    def _refresh_trigger_eca(self) -> None:
        pass

    def _shutdown_object_filter_runner(self) -> None:
        pass

    def _shutdown_current_map_gui(self) -> None:
        pass

    def _save_layout_state(self, **_kwargs) -> None:
        pass

    def geometry(self) -> str:
        return "1000x700"

    def destroy(self) -> None:
        self.destroyed = True


def _byte_map(name: str) -> tuple[MapData, BytesArchiveSource]:
    source = BytesArchiveSource(name, b"retained map bytes")
    return MapData(path=name, name=name, archive_source=source), source


def test_replaced_map_and_shutdown_release_retained_archive_sources() -> None:
    host = _MapHost()
    old, old_source = _byte_map("old.w3x")
    current, current_source = _byte_map("current.w3x")
    host.map_data = old

    host._render_map(current, [], [], None)

    assert old_source.is_closed
    assert not current_source.is_closed
    host._on_close()
    assert current_source.is_closed
    assert host.destroyed


def test_campaign_switch_keeps_navigation_sources_until_app_closes() -> None:
    host = _MapHost()
    root, root_source = _byte_map("campaign.w3n")
    child, child_source = _byte_map("child.w3x")
    root.sub_maps = [child]
    views = [("共享", root), ("子图", child)]
    host._campaign_views = views
    host._dir_campaigns = [
        {"path": "campaign.w3n", "name": "战役", "loaded": True, "views": views}
    ]
    host.map_data = root

    host._render_map(child, [], [], None)

    assert not root_source.is_closed
    assert not child_source.is_closed
    host._on_close()
    assert root_source.is_closed
    assert child_source.is_closed


def test_map_replacement_waits_for_inflight_export_before_closing_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host = _MapHost()
    host._gui_workers = GuiWorkerRegistry()
    old, source = _byte_map("old.w3x")
    host.map_data = old
    started = threading.Event()
    release = threading.Event()
    observed: list[bool] = []

    def prepare(_md):
        started.set()
        assert release.wait(5)
        observed.append(source.is_closed)
        return ()

    monkeypatch.setattr(exports, "tmp_extract_dir", lambda *_args, **_kw: str(tmp_path))
    monkeypatch.setattr(exports, "build_readable_script_exports", prepare)
    monkeypatch.setattr(exports, "write_script_exports", lambda *_args: 0)
    try:
        host.on_export_scripts()
        assert started.wait(5)
        current, _current_source = _byte_map("current.w3x")
        host._render_map(current, [], [], None)
        assert not source.is_closed
        release.set()
        assert host._gui_workers.shutdown(2) == ()

        assert observed == [False]
        assert source.is_closed
    finally:
        release.set()
        host._on_close()
