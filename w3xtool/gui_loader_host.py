"""Static host contract for the background GUI loader mixin."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, NotRequired, Protocol, TypedDict

if TYPE_CHECKING:
    import queue

    from .gui_loader import LoaderPayload, PreparedIconResolver
    from .map_data import MapData
    from .script_scan import ChatCommand, Recipe


class LoaderStatus(Protocol):
    def configure(self, *, text: str) -> None: ...


class Joinable(Protocol):
    def join(self) -> None: ...


class CampaignEntry(TypedDict):
    name: str
    path: str
    loaded: NotRequired[bool]
    views: NotRequired[list[tuple[str, MapData]]]


if TYPE_CHECKING:

    class _TypingStatus:
        def configure(self, *, text: str) -> None:
            _ = text

    class BackgroundLoaderHost:
        load_options: dict[str, bool] = {}
        game_data_path: str | None = None
        author_bundle_path: str | None = None
        description_cache_path: str | None = None
        external_listfile_path: str | None = None
        status: LoaderStatus = _TypingStatus()
        _dir_campaigns: list[CampaignEntry] = []
        _load_results: queue.Queue[tuple[int, LoaderPayload]] = queue.Queue()
        _load_token: int = 0
        _load_pending: set[int] = set()
        _load_poll_id: str | None = None
        _load_workers: dict[int, Joinable] = {}

        def after(self, delay_ms: int, callback: Callable[[], None]) -> str: ...

        def after_cancel(self, poll_id: str) -> None: ...

        def _on_loaded(
            self,
            md: MapData,
            commands: list[ChatCommand],
            recipes: list[Recipe],
            resolver: PreparedIconResolver | None,
            views: list[tuple[str, MapData]] | None,
            campaign_path: str | None,
        ) -> None: ...

        def _refresh_campaign_tree(self) -> None: ...

else:
    BackgroundLoaderHost = object
