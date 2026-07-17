"""Byte mutations at the final public result boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, assert_never

import pytest

from tests.description_cache_publication_fixture import (
    assert_live_retained_records,
    replacement_inputs,
)
from tests.trusted_description_cache_fixture import published_cache
from w3xtool import description_cache_publication as publication
from w3xtool import (
    description_cache_publication_generation_evidence as generation_evidence,
)
from w3xtool.description_cache_migration import (
    DescriptionCacheMigrationOptions,
    migrate_description_cache,
)
from w3xtool.description_cache_owned_schema import (
    TRUSTED_DESCRIPTION_CACHE_MARKER,
)
from w3xtool.description_cache_publication_errors import (
    PublicationCommitContextError,
)
from w3xtool.description_cache_publication_models import (
    DescriptionCachePublicationProof,
    DescriptionCachePublicationResult,
)
from w3xtool.trusted_description_cache_generation_io import (
    TrustedCacheGenerationState,
)
from w3xtool.trusted_description_cache_models import TrustedDescriptionCachePayloads


type Generation = Literal["active", "retained"]


def _mutate_same_size(path: Path) -> tuple[tuple[int, int], int, bytes]:
    details = path.stat(follow_symlinks=False)
    before = path.read_bytes()
    replacement = (b"0" if before[:1] != b"0" else b"1") + before[1:]
    _ = path.write_bytes(replacement)
    after = path.stat(follow_symlinks=False)
    assert (after.st_dev, after.st_ino) == (details.st_dev, details.st_ino)
    assert after.st_size == details.st_size
    return (details.st_dev, details.st_ino), details.st_size, replacement


@pytest.mark.parametrize("generation", ("active", "retained"))
def test_generation_bytes_mutated_immediately_before_public_result_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    generation: Generation,
) -> None:
    # Given: replacement has committed both active and previous generations.
    output = published_cache(tmp_path / "first", raw="first")
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    original = publication.require_live_result_evidence
    mutated: list[tuple[Path, tuple[int, int], int, bytes]] = []

    def mutate_before_result(
        parent_descriptor: int,
        parent: Path,
        parent_identity: tuple[int, int],
        active: Path,
        active_identity: tuple[int, int],
        proof: DescriptionCachePublicationProof,
        private_paths: tuple[Path, Path],
    ) -> DescriptionCachePublicationResult:
        match generation:
            case "active":
                target = active
            case "retained":
                target = proof.retained_expectations[0].record.path
            case unreachable:
                assert_never(unreachable)
        marker = target / TRUSTED_DESCRIPTION_CACHE_MARKER
        identity, size, payload = _mutate_same_size(marker)
        mutated.append((marker, identity, size, payload))
        return original(
            parent_descriptor,
            parent,
            parent_identity,
            active,
            active_identity,
            proof,
            private_paths,
        )

    monkeypatch.setattr(
        publication, "require_live_result_evidence", mutate_before_result
    )

    # When: caller-visible result evidence hashes the committed generation set.
    with pytest.raises(PublicationCommitContextError) as raised:
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    # Then: the mutation kept inode/size but could not cross the result boundary.
    assert len(mutated) == 1
    marker, identity, size, payload = mutated[0]
    current = marker.stat(follow_symlinks=False)
    assert (current.st_dev, current.st_ino) == identity
    assert current.st_size == size
    assert marker.read_bytes() == payload
    assert_live_retained_records(raised.value.retained)


def test_early_active_same_size_mutation_while_retained_generation_reads_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: active payload is read before the later retained generation payload.
    output = published_cache(tmp_path / "first", raw="first")
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    original = generation_evidence.read_snapshot_payloads
    active_reads = 0
    mutation: list[tuple[tuple[int, int], int, bytes]] = []

    def mutate_active_before_retained_read(
        descriptor: int,
        display_root: Path,
        snapshot: TrustedCacheGenerationState,
    ) -> TrustedDescriptionCachePayloads:
        nonlocal active_reads
        if display_root == output:
            active_reads += 1
        elif active_reads == 1 and not mutation:
            mutation.append(
                _mutate_same_size(output / TRUSTED_DESCRIPTION_CACHE_MARKER)
            )
        return original(descriptor, display_root, snapshot)

    monkeypatch.setattr(
        generation_evidence,
        "read_snapshot_payloads",
        mutate_active_before_retained_read,
    )

    # When: whole-set proof continues reading the retained generation.
    with pytest.raises(PublicationCommitContextError) as raised:
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    # Then: same-inode/same-size mutation was observed and rejected.
    assert active_reads == 1
    assert len(mutation) == 1
    identity, size, payload = mutation[0]
    marker = output / TRUSTED_DESCRIPTION_CACHE_MARKER
    details = marker.stat(follow_symlinks=False)
    assert (details.st_dev, details.st_ino) == identity
    assert details.st_size == size
    assert marker.read_bytes() == payload
    assert_live_retained_records(raised.value.retained)


__all__: tuple[str, ...] = ()
