"""Pure worker-method regressions; no Tk interpreter or window is created."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

import gametool.gui_save_workspace as workspace
from gametool.gui_map_resources import GuiMapResources
from gametool.gui_worker_host import GuiWorkerHostMixin
from gametool.gui_worker_registry import GuiWorkerRegistry
from gametool.map_data import GameObject, MapData
from gametool.real_save_files import RealSaveReport, analyze_real_save_path
from gametool.save_report_query import select_save_report


class _Var:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class _Widget:
    def __init__(self) -> None:
        self.states: list[dict[str, str]] = []

    def configure(self, **kwargs: str) -> None:
        self.states.append(kwargs)


class _Tree:
    def get_children(self) -> tuple[str, ...]:
        return ()


class _ManualThread:
    all: list[_ManualThread] = []

    def __init__(self, *, target: Callable[[], None], daemon: bool, name: str) -> None:
        self.target, self.name, self.live = target, name, True
        self.all.append(self)

    def start(self) -> None:
        pass

    def join(self, timeout: float | None = None) -> None:
        pass

    def is_alive(self) -> bool:
        return self.live

    def run(self) -> None:
        try:
            self.target()
        finally:
            self.live = False


class _Host(GuiWorkerHostMixin):
    def __init__(
        self,
        source: Path,
        *,
        report: RealSaveReport | None = None,
        initial_map: MapData | None = None,
    ) -> None:
        self.polls: dict[str, Callable[[], None]] = {}
        self._init_gui_worker_host()
        self._gui_workers = GuiWorkerRegistry(thread_factory=_ManualThread)
        self._closed = False
        self._generation = 0
        self._tree_epoch = 0
        self._row_records: dict[str, object] = {}
        self._report = report
        self._selection = select_save_report(report) if report is not None else None
        self._initial_map = initial_map
        self.source_var = _Var(str(source))
        self.map_var = _Var(initial_map.path if initial_map else "")
        self.encoding_var = _Var("auto")
        self.query_var, self.kind_var, self.limit_var = (
            _Var(""),
            _Var("全部"),
            _Var("0"),
        )
        self.status, self.export_button, self.tree = _Widget(), _Widget(), _Tree()
        self.received: list[RealSaveReport] = []
        self.cancelled: list[str] = []

    def after(self, ms: int, func: Callable[[], None]) -> str:  # pyright: ignore[reportIncompatibleMethodOverride] - pure Tk scheduler harness.
        identifier = str(len(self.polls) + 1)
        self.polls[identifier] = func
        return identifier

    def after_cancel(self, id: str) -> None:
        self.polls.pop(id, None)

    def _memo(self) -> None:
        pass

    def title(self, text: str) -> None:
        pass

    def _show_text(self, text: str) -> None:
        pass

    def _receive_report(
        self, report: RealSaveReport, generation: int, elapsed: float
    ) -> None:
        self._report = report
        self.received.append(report)
        self.status.configure(text=f"current report: {report.source}")

    def _cancel_gui_worker_group(self, group: str) -> None:
        self.cancelled.append(group)
        super()._cancel_gui_worker_group(group)

    def deliver_all(self) -> None:
        for key in tuple(self._gui_posts):
            self._deliver_gui_post(key)


def test_refresh_cancels_old_export_and_its_queued_callback_cannot_replace_new_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ManualThread.all.clear()
    source_a, source_b = tmp_path / "a.txt", tmp_path / "b.txt"
    source_a.write_text("source a", encoding="utf-8")
    source_b.write_text("source b", encoding="utf-8")
    host = _Host(source_a, report=analyze_real_save_path(source_a))
    output = tmp_path / "report-a.json"
    monkeypatch.setattr(
        workspace.filedialog, "asksaveasfilename", lambda **_kwargs: str(output)
    )
    workspace.SaveWorkspace.export_report(host)  # pyright: ignore[reportArgumentType] - exercise worker methods without constructing Tk.
    _ManualThread.all[-1].run()
    queued = tuple(post.callback for post in host._gui_posts.values())
    assert output.exists() and queued
    host.source_var.set(str(source_b))
    workspace.SaveWorkspace.refresh(host)  # pyright: ignore[reportArgumentType] - pure view harness.
    _ManualThread.all[-1].run()
    host.deliver_all()
    current_status = host.status.states[-1]
    assert "save-export" in host.cancelled
    assert host._report is not None and host._report.source == str(source_b)
    for old_callback in queued:
        old_callback()
    assert host.status.states[-1] == current_status
    assert output.exists()
    assert host._shutdown_gui_worker_host(0) == ()


def test_same_path_refresh_loads_fresh_owned_map_after_parent_retires_old_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ManualThread.all.clear()
    path = tmp_path / "selected-map.w3x"
    path.write_bytes(b"synthetic identity; native map loader is stubbed")
    source = tmp_path / "profile.txt"
    source.write_text("H001", encoding="utf-8")
    old = MapData(
        str(path),
        "old map",
        objects={"单位": [GameObject("单位", "w3u", "H001", "Hpal", "OLD NAME", True)]},
    )
    fresh = MapData(
        str(path),
        "new map",
        objects={"单位": [GameObject("单位", "w3u", "H001", "Hpal", "NEW NAME", True)]},
    )
    owner = GuiMapResources()
    owner.remember((old,))
    owner.synchronize((fresh,))
    assert old._closed
    host = _Host(source, initial_map=old)
    loaded: list[str] = []

    def load_map(selected: str) -> MapData:
        loaded.append(selected)
        assert not fresh._closed
        return fresh

    monkeypatch.setattr(workspace, "load_map", load_map)
    workspace.SaveWorkspace.refresh(host)  # pyright: ignore[reportArgumentType] - pure view harness.
    _ManualThread.all[-1].run()
    host.deliver_all()
    assert loaded == [str(path)] and fresh._closed
    assert host._report is not None and host._report.map_name == "new map"
    assert [match.name for match in host._report.files[0].object_matches] == [
        "NEW NAME"
    ]
    assert host._shutdown_gui_worker_host(0) == ()


def test_refresh_captures_explicit_encoding_before_background_work(
    tmp_path: Path,
) -> None:
    _ManualThread.all.clear()
    source = tmp_path / "profile.txt"
    text = "存档码: AbCD1234\n-load AbCD1234"
    payload = text.encode("utf-16-le")
    source.write_bytes(payload)
    host = _Host(source)
    host.encoding_var.set("utf-16-le")
    workspace.SaveWorkspace.refresh(host)  # pyright: ignore[reportArgumentType] - pure Tk worker harness.
    host.encoding_var.set("utf-16-be")
    _ManualThread.all[-1].run()
    host.deliver_all()
    assert host._report is not None and host._report.complete
    assert host._report.text_encoding == "utf-16-le"
    assert host._report.files[0].raw_text == text
    assert host._report.files[0].codes[0].code == "-load AbCD1234"
    assert source.read_bytes() == payload
    assert host._shutdown_gui_worker_host(0) == ()


def test_encoding_selection_persists_only_to_isolated_memo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated = tmp_path / "isolated-cache"
    unrelated = tmp_path / "caller-cache" / "gui-query-memo" / "save-workspace.json"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_bytes(b'{"text_encoding":"caller-original"}')
    before = unrelated.read_bytes(), unrelated.stat().st_mtime_ns
    monkeypatch.setattr(workspace, "gamexray_cache_root", lambda: isolated)
    host = _Host(tmp_path / "profile.txt")
    host.encoding_var.set("utf-16-be")
    workspace.SaveWorkspace._memo(host)  # pyright: ignore[reportArgumentType] - pure Tk memo harness.
    assert workspace._load_workspace_memo()["text_encoding"] == "utf-16-be"
    assert (unrelated.read_bytes(), unrelated.stat().st_mtime_ns) == before
    assert host._shutdown_gui_worker_host(0) == ()
