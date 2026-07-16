"""Validation-fault behavior during trusted-cache publication."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.description_cache_publication_fixture import (
    private_publication_paths,
    replacement_inputs,
)
from tests.trusted_description_cache_fixture import published_cache
from w3xtool import description_cache_publication as publication
from w3xtool.description_cache_migration import (
    DescriptionCacheMigrationOptions,
    migrate_description_cache,
)
from w3xtool.description_cache_publication import DescriptionCachePublicationError
from w3xtool.trusted_description_cache import (
    VerifiedDescriptionCache,
    load_trusted_description_cache,
    load_trusted_description_cache_from_parent,
)


def test_stage_self_validation_failure_keeps_destination_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a valid destination and a staged generation that fails validation.
    root = published_cache(tmp_path / "first", raw="first")
    before = load_trusted_description_cache(root)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")

    def reject_stage(
        parent_descriptor: int,
        path: Path,
    ) -> VerifiedDescriptionCache:
        if path.name.startswith(".w3xray-description-cache-stage-"):
            raise DescriptionCachePublicationError("stage validation failed")
        return load_trusted_description_cache_from_parent(
            parent_descriptor,
            path.name,
            path,
        )

    monkeypatch.setattr(publication, "_require_valid_at", reject_stage)

    # When / Then
    with pytest.raises(DescriptionCachePublicationError, match="stage validation"):
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )
    assert load_trusted_description_cache(root) == before
    assert not private_publication_paths(root)


def test_failed_replacement_validation_restores_previous_owned_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: stage validation passes, but validation after replacement fails.
    root = published_cache(tmp_path / "first", raw="first")
    before = load_trusted_description_cache(root)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    destination_validations = 0

    def reject_replaced_destination(
        parent_descriptor: int,
        path: Path,
    ) -> VerifiedDescriptionCache:
        nonlocal destination_validations
        if path == root:
            destination_validations += 1
            if destination_validations == 2:
                raise DescriptionCachePublicationError("replacement validation failed")
        return load_trusted_description_cache_from_parent(
            parent_descriptor,
            path.name,
            path,
        )

    monkeypatch.setattr(
        publication,
        "_require_valid_at",
        reject_replaced_destination,
    )

    # When / Then
    with pytest.raises(
        DescriptionCachePublicationError,
        match="replacement validation",
    ):
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )
    assert load_trusted_description_cache(root) == before
    assert not private_publication_paths(root)


__all__: tuple[str, ...] = ()
