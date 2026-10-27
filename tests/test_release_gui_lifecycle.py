"""Release regressions for background delivery and campaign navigation."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path

import pytest

from gametool.api import MapData
from gametool.archive_source import BytesArchiveSource
from gametool.gui_loader import LoadedMap, load_path_payload, switch_map_payload
from gametool.gui_loader_runner import _discard_loader_payload
from gametool.gui_lifecycle import GuiLifecycleMixin
from gametool.gui_source_browser import SourceBrowserMixin
from gametool.gui_worker_host import GuiWorkerHostMixin
from gametool.gui_worker_registry import GuiWorkerRegistry, GuiWorkerTicket
from tests.gui_worker_fakes import InlineGuiThread


class _WorkerHost(GuiWorkerHostMixin):
    def __init__(self) -> None:
        self.scheduled: dict[str, Callable[[], object]] = {}
        self._next_after = 0
        self._init_gui_worker_host()
        self._gui_workers = GuiWorkerRegistry(thread_factory=InlineGuiThread)

    def after(self, ms: int, func: Callable[..., object], *args, **kwargs) -> str:
        assert ms > 0
        self._next_after += 1
        key = f"after-{self._next_after}"
        self.scheduled[key] = lambda: func(*args, **kwargs)
        return key

    def after_cancel(self, id: str) -> None:
        self.scheduled.pop(id, None)

    def pump(self) -> None:
        key = next(iter(self.scheduled))
        self.scheduled.pop(key)()

    def post(
        self,
        group: str,
        callback: Callable[[], None],
        cleanup: Callable[[], None] | None = None,
    ) -> None:
        def work(ticket: GuiWorkerTicket) -> None:
            _ = self._post_gui_worker(ticket, callback, cleanup=cleanup)

        _ = self._start_gui_worker(group, work, replace=True)


def test_failed_result_delivery_keeps_later_background_results_live() -> None:
    host = _WorkerHost()
    delivered: list[str] = []

    def fail() -> None:
        raise ValueError("view rendering failed")

    host.post("broken-view", fail)
    host.post("export", lambda: delivered.append("export"))
    try:
        host.pump()
        assert delivered == ["export"]
        assert len(host.scheduled) == 1
        host.post("loader", lambda: delivered.append("map"))
        host.pump()
        assert delivered == ["export", "map"]
    finally:
        assert host._shutdown_gui_worker_host(1) == ()


def test_failed_payload_cleanup_does_not_abort_shutdown() -> None:
    host = _WorkerHost()
    cleaned: list[str] = []

    def fail_cleanup() -> None:
        raise OSError("resolver close failed")

    host.post("first", lambda: None, cleanup=fail_cleanup)
    host.post("second", lambda: None, cleanup=lambda: cleaned.append("second"))

    assert host._shutdown_gui_worker_host(1) == ()
    assert cleaned == ["second"]
    assert host.scheduled == {}


class _ModeSelector:
    def __init__(self) -> None:
        self.value = "战役图"

    def set(self, value: str) -> None:
        self.value = value


class _CampaignHost(_WorkerHost, SourceBrowserMixin, GuiLifecycleMixin):
    _campaign_path: str | None
    _campaign_views: object | None
    mode_seg: _ModeSelector  # pyright: ignore[reportIncompatibleVariableOverride] - minimal widget fake.
    _node_map: dict[str, tuple[str, int | str | MapData]]  # pyright: ignore[reportIncompatibleVariableOverride] - exercise the real MapData node variant.

    def __init__(self) -> None:
        super().__init__()
        self.parent = MapData(path="campaign.w3n", name="战役")
        self.child = MapData(path="Maps\\Chapter1.w3x", name="第一章")
        self.views = [("共享", self.parent), ("第一章", self.child)]
        self._dir_campaigns = [
            {
                "path": "campaign.w3n",
                "name": "战役",
                "loaded": True,
                "views": self.views,
            }
        ]
        self._campaign_views = self.views
        self._campaign_path = "campaign.w3n"
        self._node_map = {"child": ("md", self.child)}  # pyright: ignore[reportIncompatibleVariableOverride] - exercise the real MapData node variant.
        self.map_data = self.parent
        self.mode = "campaign"
        self.mode_seg = _ModeSelector()  # pyright: ignore[reportIncompatibleVariableOverride] - minimal widget fake.
        self.switches: list[tuple[MapData, str | None]] = []
        self.rendered: list[MapData] = []

    def _start_map_switch(self, md: MapData, campaign_path: str | None) -> None:
        self.switches.append((md, campaign_path))

    def _populate_left(self) -> None:
        pass

    def _render_map(self, md, cmds, recipes, resolver) -> None:
        self.map_data = md
        self.rendered.append(md)


def test_campaign_child_delivery_preserves_source_and_navigation() -> None:
    host = _CampaignHost()
    host._open_node("child")
    assert host.switches == [(host.child, "campaign.w3n")]

    host._on_loaded(host.child, [], [], None, None, "campaign.w3n")

    assert host.mode == "campaign"
    assert host.mode_seg.value == "战役图"
    assert host._campaign_path == "campaign.w3n"
    assert host._campaign_views is host.views
    assert host.map_data is host.child


def test_pending_campaign_switch_does_not_relabel_current_map() -> None:
    host = _CampaignHost()
    previous = MapData(path="previous.w3x", name="当前对战图")
    host.map_data = previous
    host._campaign_path = None
    host._campaign_views = None
    host.mode = "battle"

    host._open_node("child")

    assert host.switches == [(host.child, "campaign.w3n")]
    assert host.map_data is previous
    assert host._campaign_path is None


class _ConfigHost(GuiLifecycleMixin):
    def __init__(self, path: Path) -> None:
        self.path = path

    def _config_path(self) -> str:
        return str(self.path)


@pytest.mark.parametrize("contents", [b"[]", b"null", b"\xff\xfe"])
def test_bad_gui_config_keeps_startup_and_preference_writes_available(
    tmp_path: Path, contents: bytes
) -> None:
    path = tmp_path / "gui.json"
    path.write_bytes(contents)
    host = _ConfigHost(path)

    assert host._load_config() == {}
    host._save_config(last_dir_battle="maps")

    assert host._load_config() == {"last_dir_battle": "maps"}


def test_gui_config_path_honors_explicit_test_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "gui-config.json"
    monkeypatch.setenv("GAMEXRAY_GUI_CONFIG_PATH", str(path))

    assert GuiLifecycleMixin()._config_path() == str(path)

    monkeypatch.delenv("GAMEXRAY_GUI_CONFIG_PATH")
    assert GuiLifecycleMixin()._config_path() == os.path.join(
        os.path.expanduser("~"), ".w3x_extractor.json"
    )


def test_stale_fresh_loader_payload_closes_owned_map_sources() -> None:
    source = BytesArchiveSource("stale.w3x", b"retained")
    md = MapData(path="stale.w3x", name="stale", archive_source=source)

    _discard_loader_payload(LoadedMap(md, [], [], None, None, None))

    assert source.is_closed


def test_stale_campaign_switch_keeps_shared_navigation_map_open() -> None:
    source = BytesArchiveSource("child.w3x", b"retained")
    md = MapData(path="child.w3x", name="child", archive_source=source)

    def prepare(active, campaign_path, views, *, load_options):
        return LoadedMap(active, [], [], None, views, campaign_path)

    try:
        payload = switch_map_payload(md, "campaign.w3n", prepare=prepare)
        _discard_loader_payload(payload)

        assert not source.is_closed
    finally:
        md.close()


def test_failed_view_preparation_closes_freshly_loaded_source() -> None:
    source = BytesArchiveSource("fresh.w3x", b"retained")
    md = MapData(path="fresh.w3x", name="fresh", archive_source=source)

    def load(path, **_kwargs):
        return md

    def prepare(active, campaign_path, views, *, load_options):
        raise ValueError("view preparation failed")

    with pytest.raises(ValueError, match="view preparation failed"):
        load_path_payload("fresh.w3x", load=load, prepare=prepare)

    assert source.is_closed
