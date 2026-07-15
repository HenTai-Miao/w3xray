"""Tk-safe background runner for map load payloads."""

from __future__ import annotations

import os
import traceback
from collections.abc import Callable
from typing import assert_never
from tkinter import messagebox

from .api import MapData
from .archive_diagnostics import diagnose_archive_open
from .external_listfile import read_external_listfile
from .gui_loader import (
    LoadedCampaign,
    LoadedMap,
    LoaderError,
    LoaderPayload,
    load_campaign_payload,
    load_path_payload,
    switch_map_payload,
)
from .gui_loader_host import BackgroundLoaderHost, CampaignEntry
from .gui_worker_registry import GuiWorkerTicket


class BackgroundLoaderMixin(BackgroundLoaderHost):
    """Queue worker-thread results so Tk is only touched from the main thread."""

    def _init_background_loader(self) -> None:
        """Retain the explicit subsystem initialization hook."""

    def _shutdown_background_loader(self) -> None:
        self._cancel_gui_worker_group("loader")

    def _start_path_load(self, path: str) -> None:
        options = dict(self.load_options)
        game_data_path = self.game_data_path
        author_bundle_path = self.author_bundle_path
        description_cache_path = getattr(self, "description_cache_path", None)
        external_names = read_external_listfile(self.external_listfile_path)
        self._start_loader_job(
            status=f"正在解析 {os.path.basename(path)} …",
            build_payload=lambda: load_path_payload(
                path,
                load_options=options,
                game_data_path=game_data_path,
                external_names=external_names,
                author_bundle_path=author_bundle_path,
                description_cache_path=description_cache_path,
            ),
            error_status="解析失败",
            source_path=path,
        )

    def _start_map_switch(self, md: MapData, campaign_path: str | None) -> None:
        options = dict(self.load_options)
        game_data_path = self.game_data_path
        self._start_loader_job(
            status="正在切换 …",
            build_payload=lambda: switch_map_payload(
                md, campaign_path, load_options=options, game_data_path=game_data_path
            ),
            error_status="切换失败",
            source_path=None,
        )

    def _start_campaign_load(self, index: int) -> None:
        if index < 0 or index >= len(self._dir_campaigns):
            return
        camp = self._dir_campaigns[index]
        path = camp["path"]
        game_data_path = self.game_data_path
        author_bundle_path = self.author_bundle_path
        description_cache_path = getattr(self, "description_cache_path", None)
        external_names = read_external_listfile(self.external_listfile_path)
        self._start_loader_job(
            status=f"正在解析战役 {camp['name']} …",
            build_payload=lambda: load_campaign_payload(
                index,
                path,
                game_data_path=game_data_path,
                external_names=external_names,
                author_bundle_path=author_bundle_path,
                description_cache_path=description_cache_path,
            ),
            error_status="战役解析失败",
            source_path=path,
        )

    def _start_loader_job(
        self,
        *,
        status: str,
        build_payload: Callable[[], LoaderPayload],
        error_status: str,
        source_path: str | None,
    ) -> None:
        self.status.configure(text=status)
        _ = self._start_gui_worker(
            "loader",
            lambda ticket: self._run_loader_job(
                ticket,
                build_payload,
                error_status,
                source_path,
            ),
            replace=True,
        )

    def _run_loader_job(
        self,
        ticket: GuiWorkerTicket,
        build_payload: Callable[[], LoaderPayload],
        error_status: str,
        source_path: str | None,
    ) -> None:
        try:
            payload = build_payload()
        except Exception as exc:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK - worker boundary returns typed GUI payloads.
            traceback.print_exc()
            message = (
                diagnose_archive_open(source_path, exc).message
                if source_path is not None
                else str(exc)
            )
            payload = LoaderError("解析失败", message, error_status)
        _ = self._post_gui_worker(
            ticket,
            lambda: self._handle_loader_payload(payload),
            cleanup=lambda: _discard_loader_payload(payload),
        )

    def _handle_loader_payload(self, payload: LoaderPayload) -> None:
        match payload:
            case LoadedMap(
                active=active,
                commands=commands,
                recipes=recipes,
                resolver=resolver,
                views=views,
                campaign_path=campaign_path,
            ):
                self._on_loaded(
                    active, commands, recipes, resolver, views, campaign_path
                )
            case LoadedCampaign(
                index=index, path=path, views=views, sub_map_count=count
            ):
                self._apply_campaign_payload(index, path, views, count)
            case LoaderError(title=title, message=message, status=status):
                messagebox.showerror(title, message)
                self.status.configure(text=status)
            case unreachable:
                assert_never(unreachable)

    def _apply_campaign_payload(
        self,
        index: int,
        path: str,
        views: list[tuple[str, MapData]],
        sub_map_count: int,
    ) -> None:
        camp = self._campaign_by_index_or_path(index, path)
        if camp is None:
            return
        camp["loaded"] = True
        camp["views"] = views
        self._refresh_campaign_tree()
        self.status.configure(text=f"战役 {camp['name']}：{sub_map_count} 张子图")

    def _campaign_by_index_or_path(
        self,
        index: int,
        path: str,
    ) -> CampaignEntry | None:
        if (
            0 <= index < len(self._dir_campaigns)
            and self._dir_campaigns[index]["path"] == path
        ):
            return self._dir_campaigns[index]
        return next(
            (camp for camp in self._dir_campaigns if camp["path"] == path), None
        )


def _discard_loader_payload(payload: LoaderPayload) -> None:
    match payload:
        case LoadedMap(resolver=resolver):
            if resolver is not None:
                try:
                    resolver.close()
                except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK - third-party resolver close is best effort.
                    return
        case LoadedCampaign() | LoaderError():
            return
        case unreachable:
            assert_never(unreachable)
