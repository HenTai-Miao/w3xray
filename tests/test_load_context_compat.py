"""Compatibility bundle paths cross the shared immutable load boundary."""

from __future__ import annotations

from w3xtool.load_context import MapLoadContext, build_map_load_context


def test_build_context_retains_compatibility_bundle_path() -> None:
    # Given/When: the caller selects a compatibility directory.
    context = build_map_load_context(compat_bundle_path="bundle")

    # Then: every loader can consume the same immutable setting.
    assert context.compat_bundle_path == "bundle"


def test_default_context_keeps_new_source_disabled() -> None:
    # Given/When: an existing caller constructs the context without new options.
    context = MapLoadContext()

    # Then: compatibility evidence remains opt-in.
    assert context.compat_bundle_path is None
