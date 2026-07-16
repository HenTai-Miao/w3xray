"""Descriptor-anchored trusted-cache inventory and byte proof."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

import pytest

from tests.trusted_description_cache_fixture import published_cache
from w3xtool import trusted_description_cache_io as anchored_io
from w3xtool.trusted_description_cache import (
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


def test_anchored_loader_proves_the_same_bytes_as_public_loader(
    tmp_path: Path,
) -> None:
    # Given: one complete generation and a held descriptor for its parent.
    root = published_cache(tmp_path)
    expected = load_trusted_description_cache(root)
    parent_descriptor = os.open(root.parent, _DIRECTORY_FLAGS)

    # When: the same leaf is loaded relative to the held parent.
    try:
        actual = load_trusted_description_cache_from_parent(
            parent_descriptor,
            root.name,
            root,
        )
    finally:
        os.close(parent_descriptor)

    # Then: both boundaries return the same semantic byte proof.
    assert actual == expected


def test_public_loader_does_not_require_anchored_host_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a host where dir-fd cache traversal is unavailable.
    root = published_cache(tmp_path)
    parent_descriptor = os.open(root.parent, _DIRECTORY_FLAGS)
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
        os.close(parent_descriptor)


@pytest.mark.parametrize("mutation", ("symlink", "directory"))
def test_anchored_loader_rejects_unsafe_owned_inventory_entry(
    tmp_path: Path,
    mutation: str,
) -> None:
    # Given: one exact owned filename resolves to a non-regular inventory entry.
    root = published_cache(tmp_path)
    target = root / "可信描述缓存.tsv"
    if mutation == "symlink":
        moved = tmp_path / "cache.real.tsv"
        target.rename(moved)
        target.symlink_to(moved)
    else:
        target.unlink()
        target.mkdir()
    parent_descriptor = os.open(root.parent, _DIRECTORY_FLAGS)

    # When / Then: fd-relative inventory stat rejects it before semantic proof.
    try:
        with pytest.raises(TrustedDescriptionCacheError, match="partial|unsafe"):
            _ = load_trusted_description_cache_from_parent(
                parent_descriptor,
                root.name,
                root,
            )
    finally:
        os.close(parent_descriptor)


def test_anchored_loader_rejects_owned_name_identity_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the first owned file's name is replaced after its held-fd first read.
    root = published_cache(tmp_path)
    target = root / ".w3xray-trusted-description-cache"
    displaced = tmp_path / "marker.original"
    replacement = tmp_path / "marker.replacement"
    replacement.write_bytes(target.read_bytes())
    real_lseek = os.lseek
    rewinds = 0

    def replace_name_before_second_read(
        descriptor: int,
        position: int,
        how: int,
    ) -> int:
        nonlocal rewinds
        if position == 0 and how == os.SEEK_SET:
            rewinds += 1
            if rewinds == 2:
                target.rename(displaced)
                replacement.rename(target)
        return real_lseek(descriptor, position, how)

    monkeypatch.setattr(os, "lseek", replace_name_before_second_read)
    parent_descriptor = os.open(root.parent, _DIRECTORY_FLAGS)

    # When / Then: identical bytes at a different inode cannot satisfy stability.
    try:
        with pytest.raises(
            TrustedDescriptionCacheError,
            match="identity|metadata changed",
        ):
            _ = load_trusted_description_cache_from_parent(
                parent_descriptor,
                root.name,
                root,
            )
    finally:
        os.close(parent_descriptor)


__all__: tuple[str, ...] = ()
