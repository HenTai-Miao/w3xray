"""Static host contract for the background GUI loader mixin."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, NotRequired, TypedDict

if TYPE_CHECKING:
    import customtkinter as ctk

    from .gui_loader import PreparedIconResolver
    from .gui_worker_registry import GuiWorkerTarget, GuiWorkerTicket
    from .map_data import MapData
    from .script_scan import ChatCommand, Recipe


class CampaignEntry(TypedDict):
    name: str
    path: str
    loaded: NotRequired[bool]
    views: NotRequired[list[tuple[str, MapData]]]


if TYPE_CHECKING:

    class BackgroundLoaderHost:
        load_options: dict[str, bool] = {}
        game_data_path: str | None = None
        author_bundle_path: str | None = None
        description_cache_path: str | None = None
        external_listfile_path: str | None = None
        status: ctk.CTkLabel  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        _dir_campaigns: list[CampaignEntry] = []

        def _start_gui_worker(
            self,
            group: str,
            target: GuiWorkerTarget,
            *,
            replace: bool,
        ) -> GuiWorkerTicket: ...

        def _post_gui_worker(
            self,
            ticket: GuiWorkerTicket,
            callback: Callable[[], None],
            *,
            cleanup: Callable[[], None] | None = None,
        ) -> bool: ...

        def _cancel_gui_worker_group(self, group: str) -> None: ...

        def _on_loaded(
            self,
            md: MapData,
            commands: list[ChatCommand],
            recipes: list[Recipe] | None = None,
            resolver: PreparedIconResolver | None = None,
            views: list[tuple[str, MapData]] | None = None,
            campaign_path: str | None = None,
        ) -> None: ...

        def _refresh_campaign_tree(self) -> None: ...

else:
    BackgroundLoaderHost = object
