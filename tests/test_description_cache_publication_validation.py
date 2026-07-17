"""Validation-fault behavior during trusted-cache publication."""

from __future__ import annotations

from pathlib import Path
from typing import Never

import pytest

from tests.description_cache_publication_fixture import (
    assert_live_retained_records,
    replacement_inputs,
    transient_publication_paths,
)
from tests.trusted_description_cache_fixture import published_cache
from w3xtool import description_cache_publication as publication
from w3xtool.description_cache_migration import (
    DescriptionCacheMigrationOptions,
    migrate_description_cache,
)
from w3xtool.description_cache_publication import DescriptionCachePublicationError
from w3xtool.description_cache_publication_errors import PublicationCommitContextError
from w3xtool.trusted_description_cache import (
    VerifiedDescriptionCache,
    load_trusted_description_cache,
    load_trusted_description_cache_from_parent,
)
from w3xtool.trusted_description_cache_models import TrustedCacheLeafProof


def test_stage_self_validation_failure_keeps_destination_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a valid destination and a staged generation that fails validation.
    root = published_cache(tmp_path / "first", raw="first")
    before = load_trusted_description_cache(root)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")

    def reject_stage(
        _stage_descriptor: int,
        _path: Path,
        _leaves: tuple[TrustedCacheLeafProof, ...],
    ) -> Never:
        raise DescriptionCachePublicationError("stage validation failed")

    monkeypatch.setattr(
        publication,
        "load_trusted_description_cache_from_descriptor",
        reject_stage,
    )

    # When / Then
    with pytest.raises(
        DescriptionCachePublicationError, match="stage validation"
    ) as raised:
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )
    assert load_trusted_description_cache(root) == before
    assert raised.value.retained[0].role.value == "failed-stage"
    assert_live_retained_records(raised.value.retained)
    assert not transient_publication_paths(root)


def test_failed_replacement_validation_restores_previous_owned_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: stage validation passes, but validation after replacement fails.
    root = published_cache(tmp_path / "first", raw="first")
    before = load_trusted_description_cache(root)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    destination_validations = 0
    validation_fault = DescriptionCachePublicationError("replacement validation failed")

    def reject_replaced_destination(
        parent_descriptor: int,
        path: Path,
    ) -> VerifiedDescriptionCache:
        nonlocal destination_validations
        if path == root:
            destination_validations += 1
            if destination_validations == 2:
                raise validation_fault
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
    with pytest.raises(PublicationCommitContextError) as raised:
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )
    assert load_trusted_description_cache(root) == before
    assert sum(failure is validation_fault for failure in raised.value.failures) == 1
    wrapper = raised.value.__context__
    assert type(wrapper) is DescriptionCachePublicationError
    assert wrapper.__cause__ is validation_fault
    assert raised.value.retained[0].role.value == "failed-stage"
    assert_live_retained_records(raised.value.retained)
    output_status = root.stat(follow_symlinks=False)
    output_evidence = tuple(
        item for item in raised.value.transient if item.leaf_name == root.name
    )
    assert len(output_evidence) == 1
    assert output_evidence[0].identity == (output_status.st_dev, output_status.st_ino)
    assert output_evidence[0].held_identity is None
    assert not transient_publication_paths(root)


__all__: tuple[str, ...] = ()
