"""Descriptor-anchored trusted-cache inventory and byte proof."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

import pytest

from tests.trusted_description_cache_fixture import published_cache
from gametool import anchored_source
from gametool import trusted_description_cache_io as anchored_io
from gametool.trusted_description_cache import (
    TrustedDescriptionCacheError,
    load_trusted_description_cache,
    load_trusted_description_cache_from_parent,
)


_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_REQUIRES_ANCHORED_CACHE = pytest.mark.skipif(
    not anchored_io._ANCHORED_CACHE_AVAILABLE,
    reason="requires descriptor-relative no-follow cache reads",
)


def test_public_loader_does_not_require_anchored_host_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a host where dir-fd cache traversal is unavailable.
    root = published_cache(tmp_path)
    parent_descriptor = (
        os.open(root.parent, _DIRECTORY_FLAGS)
        if anchored_io._ANCHORED_CACHE_AVAILABLE
        else -1
    )
    monkeypatch.setattr(anchored_source, "_ANCHORED_OPEN_AVAILABLE", False)
    monkeypatch.setattr(anchored_io, "_ANCHORED_CACHE_AVAILABLE", False)

    # When / Then: public loading remains compatible; publication fails closed.
    try:
        assert load_trusted_description_cache(root).cache.entries
        with pytest.raises(TrustedDescriptionCacheError, match="unavailable"):
            _ = load_trusted_description_cache_from_parent(
                parent_descriptor,
                root.name,
                root,
            )
    finally:
        if parent_descriptor >= 0:
            os.close(parent_descriptor)


__all__: tuple[str, ...] = ()
