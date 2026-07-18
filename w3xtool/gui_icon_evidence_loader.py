"""Strict icon-evidence resolver lifecycle used by GUI map preparation."""

from __future__ import annotations

from collections.abc import Callable
import traceback
from typing import Protocol

from PIL import Image

from .icon_evidence_index import IconEvidenceIndex
from .icons import IconResolver
from .map_data import MapData


class PreparedIconResolver(Protocol):
    """Resolver capability retained only while object icon browsing is enabled."""

    def build_evidence_index(self, md: MapData) -> IconEvidenceIndex: ...

    def get_image(self, path: str) -> Image.Image | None: ...

    def close(self) -> None: ...


def build_strict_icon_resolver(
    md: MapData,
    campaign_path: str | None,
    game_data_path: str | None,
    resolver_factory: Callable[..., IconResolver] = IconResolver,
) -> IconResolver:
    """Create a browsing resolver and populate map evidence from strict layers."""
    extra = [campaign_path] if campaign_path and campaign_path != md.path else None
    resolver = resolver_factory(
        md.path,
        extra_paths=extra,
        game_data_path=game_data_path,
    )
    md.icon_evidence = resolver.build_evidence_index(md)
    return resolver


def build_resolver_evidence(md: MapData, resolver) -> IconEvidenceIndex:
    """Assign one custom resolver's immutable strict evidence index."""
    index = resolver.build_evidence_index(md)
    md.icon_evidence = index
    return index


def safe_default_icon_resolver(
    md: MapData,
    campaign_path: str | None,
    game_data_path: str | None,
    resolver_factory: Callable[..., IconResolver],
) -> IconResolver | None:
    """Isolate optional strict evidence setup at the GUI preparation boundary."""
    try:
        return build_strict_icon_resolver(
            md, campaign_path, game_data_path, resolver_factory
        )
    except Exception:  # noqa: BROAD_EXCEPT_OK - optional GUI resolver isolation.
        traceback.print_exc()
        return None


def safe_custom_icon_resolver(
    loader: Callable[[MapData, str | None], PreparedIconResolver | None],
    md: MapData,
    campaign_path: str | None,
) -> PreparedIconResolver | None:
    """Run one caller-provided resolver with the same strict evidence lifecycle."""
    try:
        resolver = loader(md, campaign_path)
        if resolver is not None:
            build_resolver_evidence(md, resolver)
        return resolver
    except Exception:  # noqa: BROAD_EXCEPT_OK - optional GUI resolver isolation.
        traceback.print_exc()
        return None
