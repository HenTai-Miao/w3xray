"""Hands-on Tk workflow used by Windows source and packaged acceptance."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
import json
from pathlib import Path
from time import monotonic, sleep
from typing import override

from .gui import App
from .gui_loader import load_path_payload


@dataclass(frozen=True, slots=True)
class GuiAcceptanceError(RuntimeError):
    tab_label: str

    @override
    def __str__(self) -> str:
        return f"GUI tab did not activate: {self.tab_label}"


def run_gui_acceptance(
    map_path: Path, pack_path: Path | None = None, campaign_path: Path | None = None
) -> str:
    """Create the real workbench, load a map, and visit every primary tab."""
    from .gui_offline_acceptance import _capture_callbacks, exercise_offline_workspaces

    payload = load_path_payload(str(map_path))
    app = App()
    app.withdraw()
    with _capture_callbacks(app) as callback_errors:
        try:
            _exercise_dialog(
                app, getattr(app, "profile_settings_button").invoke, "提取设置"
            )
            offline_detail = exercise_offline_workspaces(app)
            app._on_loaded(
                payload.active,
                payload.commands,
                payload.recipes,
                payload.resolver,
                payload.views,
                payload.campaign_path,
            )
            visited: list[str] = []
            for label in app.editor_tab_labels:
                app.tabs.set(label)
                app.update_idletasks()
                if app.tabs.get() != label:
                    raise GuiAcceptanceError(label)
                visited.append(label)
            app.update()
            query_detail = _exercise_queries(app) if pack_path else ""
            from .gui_topbar import _open_guide_window
            from .guide_report import format_guide_report

            previous = set(app.winfo_children())
            _open_guide_window(app, format_guide_report(payload.active))
            app.update()
            guides = [
                child
                for child in app.winfo_children()
                if child not in previous and child.winfo_toplevel() is child
            ]
            if len(guides) != 1:
                raise RuntimeError("攻略速查窗口没有正常打开")
            if campaign_path:
                campaign = load_path_payload(str(campaign_path))
                app._on_loaded(
                    campaign.active,
                    campaign.commands,
                    campaign.recipes,
                    campaign.resolver,
                    campaign.views,
                    campaign.campaign_path,
                )
                if app.current_map_pack_dir() is not None:
                    raise RuntimeError("切换地图后复用了上一张地图的资料包")
                if not app._campaign_path or not app._campaign_views:
                    raise RuntimeError("GUI 战役载入丢失导航来源")
                query_detail += "; campaign-current-pack" + _exercise_queries(app)
            guides[0].destroy()
            app.update()
            detail = (
                f"loaded={payload.active.name}; tabs={len(visited)}; "
                f"{','.join(visited)}{query_detail}; guide-open-close; "
                f"settings-open-close; {offline_detail}"
            )
        finally:
            try:
                _destroy_without_persisting(app)
                # Keep this interpreter's background-error capture alive through
                # parent teardown; the packaged runner uses this exact path.
                deadline = monotonic() + 0.35
                while monotonic() < deadline:
                    app.tk.call("update", "idletasks")
                    app.tk.call("update")
                    sleep(0.01)
            finally:
                payload.active.close()
                for _name, md in payload.views or ():
                    md.close()
        if callback_errors:
            raise RuntimeError("GUI 回调异常: " + "; ".join(callback_errors))
    return detail


def _exercise_dialog(app: App, opener: Callable[[], object], label: str) -> None:
    previous = set(app.winfo_children())
    opener()
    app.update()
    windows = [
        child
        for child in app.winfo_children()
        if child not in previous and child.winfo_toplevel() is child
    ]
    if len(windows) != 1:
        raise RuntimeError(f"{label} 按钮没有打开对应窗口")
    windows[0].destroy()
    app.update()


def _exercise_queries(app: App) -> str:
    from .gui_pack_query import _PackQueryWindow

    previous = set(app.winfo_children())
    app.on_pack_query(prefill_command="list")
    deadline = monotonic() + 60
    while True:
        app.update()
        windows = [
            child
            for child in app.winfo_children()
            if child not in previous and isinstance(child, _PackQueryWindow)
        ]
        if windows:
            if len(windows) != 1:
                raise RuntimeError("查询入口打开了多个结果窗口")
            window = windows[0]
            break
        if monotonic() >= deadline:
            raise RuntimeError("当前地图自动导包后未打开查询窗口")
        sleep(0.01)
    if app.current_map_pack_dir() != window._pack_dir:
        raise RuntimeError("查询窗口没有绑定当前地图的资料包")
    window.withdraw()
    try:
        window._var_json.set(True)
        for command, keyword, status in (
            ("list", "", 0),
            ("near", "invalid", 2),
            ("again", "", 0),
        ):
            window._keyword.delete(0, "end")
            window._keyword.insert(0, keyword)
            window._run(command)
            deadline = monotonic() + 60
            while window.cget("cursor") == "watch":
                if monotonic() >= deadline:
                    raise RuntimeError(f"GUI 查询 {command} 未能交付结果")
                app.update()
                sleep(0.01)
            text = window._output.get("1.0", "end").lstrip()
            payload, _end = json.JSONDecoder().raw_decode(text)
            if payload["exit_code"] != status:
                raise RuntimeError(
                    f"GUI 查询 {command} 的结果或错误恢复不正确: "
                    f"command={payload.get('command')}; exit_code={payload['exit_code']}; "
                    f"pack={window._pack_dir}; lines={payload.get('lines')!r}"
                )
        return "; query-window=list/invalid-near/again"
    finally:
        window.destroy()


def _destroy_without_persisting(app: App) -> None:
    app._shutdown_background_loader()
    app._shutdown_object_filter_runner()
    app._shutdown_gui_worker_host(timeout_seconds=1.5)
    if app.icons is not None and hasattr(app.icons, "close"):
        app.icons.close()
    app._shutdown_current_map_gui()
    app.destroy()
