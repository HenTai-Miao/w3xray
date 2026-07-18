"""Pure map loading and preparation payloads for the Tk GUI."""

from __future__ import annotations

import traceback
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Final, Protocol

from .api import MapData, commands_from_map, load_map, recipes_from_map
from .gui_icon_evidence_loader import (
    build_strict_icon_resolver,
    close_icon_resolver,
    PreparedIconResolver,
    safe_default_icon_resolver,
    safe_custom_icon_resolver,
)
from .icons import IconResolver
from .load_context import MapLoadContext, build_map_load_context
from .load_options import (
    COMMANDS_KEY,
    OBJECT_BROWSER_KEY,
    RECIPES_KEY,
    default_load_options,
    normalize_load_options,
)
from .script_scan import ChatCommand, Recipe

PREP_WORKERS: Final = 3


class LoadMapFunc(Protocol):
    def __call__(
        self,
        path: str,
        *,
        load_context: MapLoadContext | None = None,
    ) -> MapData: ...


class PrepareMapFunc(Protocol):
    def __call__(
        self,
        active: MapData,
        campaign_path: str | None,
        views: list[tuple[str, MapData]] | None,
        *,
        load_options: dict[str, bool] | None,
    ) -> LoadedMap: ...


@dataclass(frozen=True, slots=True)
class LoadedMap:
    active: MapData
    commands: list[ChatCommand]
    recipes: list[Recipe]
    resolver: PreparedIconResolver | None
    views: list[tuple[str, MapData]] | None
    campaign_path: str | None


@dataclass(frozen=True, slots=True)
class LoadedCampaign:
    index: int
    path: str
    views: list[tuple[str, MapData]]
    sub_map_count: int


@dataclass(frozen=True, slots=True)
class LoaderError:
    title: str
    message: str
    status: str


type LoaderPayload = LoadedMap | LoadedCampaign | LoaderError


def load_path_payload(
    path: str,
    *,
    load: LoadMapFunc = load_map,
    prepare: PrepareMapFunc | None = None,
    load_options: dict[str, bool] | None = None,
    game_data_path: str | None = None,
    external_names: Sequence[str] = (),
    author_bundle_path: str | None = None,
    description_cache_path: str | None = None,
) -> LoadedMap:
    """Load a map path and prepare the initial visible view."""
    context = build_map_load_context(
        external_names=external_names,
        game_data_path=game_data_path,
        author_bundle_path=author_bundle_path,
        description_cache_path=description_cache_path,
    )
    md = _load_with_context(load, path, context)
    if md.sub_maps:
        views = [("★ 战役共享对象", md)] + [(sub.name, sub) for sub in md.sub_maps]
        campaign_path = path
    else:
        views = None
        campaign_path = None
    active = views[0][1] if views else md
    if prepare is not None:
        return prepare(active, campaign_path, views, load_options=load_options)
    return prepare_map_view(
        active,
        campaign_path,
        views,
        load_options=load_options,
        game_data_path=game_data_path,
    )


def switch_map_payload(
    md: MapData,
    campaign_path: str | None,
    *,
    prepare: PrepareMapFunc | None = None,
    load_options: dict[str, bool] | None = None,
    game_data_path: str | None = None,
) -> LoadedMap:
    """Prepare an already-loaded campaign sub-map."""
    if prepare is not None:
        return prepare(md, campaign_path, None, load_options=load_options)
    return prepare_map_view(
        md,
        campaign_path,
        None,
        load_options=load_options,
        game_data_path=game_data_path,
    )


def load_campaign_payload(
    index: int,
    path: str,
    *,
    load: LoadMapFunc = load_map,
    game_data_path: str | None = None,
    external_names: Sequence[str] = (),
    author_bundle_path: str | None = None,
    description_cache_path: str | None = None,
) -> LoadedCampaign:
    """Load a campaign node enough to populate its child maps."""
    context = build_map_load_context(
        external_names=external_names,
        game_data_path=game_data_path,
        author_bundle_path=author_bundle_path,
        description_cache_path=description_cache_path,
    )
    md = _load_with_context(load, path, context)
    views = [("★ 战役共享对象", md)] + [(sub.name, sub) for sub in md.sub_maps]
    return LoadedCampaign(
        index=index, path=path, views=views, sub_map_count=len(md.sub_maps)
    )


def _load_with_context(
    load: LoadMapFunc,
    path: str,
    context: MapLoadContext,
) -> MapData:
    if (
        not context.external_names
        and context.trigger_schema is None
        and context.author_bundle_path is None
        and not context.client_base_objects
        and context.compat_bundle_path is None
        and not context.client_text_available
        and not context.description_cache.entries
        and not context.description_cache.diagnostics
    ):
        return load(path)
    return load(path, load_context=context)


def prepare_map_view(
    md: MapData,
    campaign_path: str | None = None,
    views: list[tuple[str, MapData]] | None = None,
    *,
    load_options: dict[str, bool] | None = None,
    command_loader: Callable[[MapData], list[ChatCommand]] = commands_from_map,
    recipe_loader: Callable[[MapData], list[Recipe]] = recipes_from_map,
    resolver_loader: Callable[[MapData, str | None], PreparedIconResolver | None]
    | None = None,
    max_workers: int = PREP_WORKERS,
    game_data_path: str | None = None,
) -> LoadedMap:
    """Prepare independent reports and icon resolver in parallel."""
    options = normalize_load_options(load_options or default_load_options())
    with ThreadPoolExecutor(
        max_workers=max_workers, thread_name_prefix="w3xray-prep"
    ) as pool:
        command_future = (
            pool.submit(_safe_list_loader, command_loader, md)
            if options[COMMANDS_KEY]
            else None
        )
        recipe_future = (
            pool.submit(_safe_list_loader, recipe_loader, md)
            if options[RECIPES_KEY]
            else None
        )
        if resolver_loader is None:
            resolver_future = pool.submit(
                safe_default_icon_resolver,
                md,
                campaign_path,
                game_data_path,
                IconResolver,
            )
        else:
            resolver_future = pool.submit(
                safe_custom_icon_resolver,
                resolver_loader,
                md,
                campaign_path,
            )
        commands = command_future.result() if command_future is not None else []
        recipes = recipe_future.result() if recipe_future is not None else []
        resolver = resolver_future.result() if resolver_future is not None else None
    if not options[OBJECT_BROWSER_KEY] and resolver is not None:
        close_icon_resolver(resolver)
        resolver = None
    return LoadedMap(md, commands, recipes, resolver, views, campaign_path)


def build_icon_resolver(
    md: MapData,
    campaign_path: str | None,
    game_data_path: str | None = None,
) -> PreparedIconResolver | None:
    """Create the resolver lazily; images decode on demand in the main view."""
    return build_strict_icon_resolver(md, campaign_path, game_data_path, IconResolver)


def _safe_list_loader[T](
    loader: Callable[[MapData], list[T]],
    md: MapData,
) -> list[T]:
    try:
        return loader(md)
    except Exception:  # noqa: BLE001 - GUI preparation boundary isolates optional report failure.
        traceback.print_exc()
        return []
