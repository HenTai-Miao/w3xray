"""Compatibility identity checks for the split map-loading facade."""

from __future__ import annotations

import w3xtool.api as api
import w3xtool.map_components as map_components
import w3xtool.map_loader as map_loader


def test_api_reexports_split_map_loading_symbols_by_identity() -> None:
    """Keep established imports bound to the implementation owners."""
    loader_symbols = (
        "load_map",
        "_load_map_impl",
        "_campaign_inner_maps",
    )
    component_symbols = (
        "_best_script_text",
        "_add_script_refs",
        "_map_name",
        "_add_w3i",
        "_add_w3f",
        "_add_wct",
        "_add_preplaced",
    )

    for name in loader_symbols:
        assert getattr(api, name) is getattr(map_loader, name)
    for name in component_symbols:
        assert getattr(api, name) is getattr(map_components, name)
