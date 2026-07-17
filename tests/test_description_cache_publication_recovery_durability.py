"""Durable evidence after every reverse-exchange boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.description_cache_publication_fixture import (
    exchange_in_parent,
    replacement_inputs,
)
from tests.trusted_description_cache_fixture import published_cache
from w3xtool import description_cache_publication as publication
from w3xtool.description_cache_migration import (
    DescriptionCacheMigrationOptions,
    migrate_description_cache,
)
from w3xtool.description_cache_publication_errors import (
    DescriptionCachePublicationError,
)
from w3xtool.trusted_description_cache import (
    VerifiedDescriptionCache,
    load_trusted_description_cache,
)


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def _failed_stage(output: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for path in output.parent.glob(".w3xray-description-cache-retained-*-*")
        if path.name.endswith("-failed-stage")
    )


def _assert_restored_with_failed_stage(
    output: Path,
    raised: pytest.ExceptionInfo[DescriptionCachePublicationError],
    previous_identity: tuple[int, int],
) -> None:
    assert _identity(output) == previous_identity
    assert (
        load_trusted_description_cache(output)
        .cache.lookup("物品", "ratf", "扩展提示", None)[0]
        .raw_value
        == "first"
    )
    failed = _failed_stage(output)
    assert len(failed) == 1
    assert (
        load_trusted_description_cache(failed[0])
        .cache.lookup("物品", "ratf", "扩展提示", None)[0]
        .raw_value
        == "second"
    )
    assert len(raised.value.retained) == 1
    assert raised.value.retained[0].identity == _identity(failed[0])


def test_atomic_exchange_completes_then_raises_and_is_recovered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = published_cache(tmp_path / "first", raw="first")
    previous_identity = _identity(output)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    fault = OSError("exchange completed before failure")
    calls = 0

    def exchange_then_raise(descriptor: int, source: str, target: str) -> None:
        nonlocal calls
        calls += 1
        exchange_in_parent(descriptor, source, target)
        if calls == 1:
            raise fault

    monkeypatch.setattr(publication, "_rename_exchange", exchange_then_raise)
    with pytest.raises(DescriptionCachePublicationError) as raised:
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    _assert_restored_with_failed_stage(output, raised, previous_identity)
    assert any(item is fault for item in raised.value.failures)


def test_reverse_exchange_completes_then_raises_preserves_both_generations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = published_cache(tmp_path / "first", raw="first")
    previous_identity = _identity(output)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    original_validate = getattr(publication, "_require_valid_at")
    rollback_fault = RuntimeError("reverse exchange completed before failure")
    exchanges = 0
    output_validations = 0

    def reject_new_output(descriptor: int, path: Path) -> VerifiedDescriptionCache:
        nonlocal output_validations
        if path == output:
            output_validations += 1
            if output_validations == 2:
                raise OSError("force rollback")
        return original_validate(descriptor, path)

    def reverse_then_raise(descriptor: int, source: str, target: str) -> None:
        nonlocal exchanges
        exchanges += 1
        exchange_in_parent(descriptor, source, target)
        if exchanges == 2:
            raise rollback_fault

    monkeypatch.setattr(publication, "_require_valid_at", reject_new_output)
    monkeypatch.setattr(publication, "_rename_exchange", reverse_then_raise)
    with pytest.raises(DescriptionCachePublicationError) as raised:
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    _assert_restored_with_failed_stage(output, raised, previous_identity)
    assert any(item is rollback_fault for item in raised.value.failures)


def test_post_exchange_validation_fault_retains_exact_new_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = published_cache(tmp_path / "first", raw="first")
    previous_identity = _identity(output)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    original = getattr(publication, "_require_valid_at")
    fault = OSError("post-exchange proof failed")
    output_reads = 0

    def reject_second_output(descriptor: int, path: Path) -> VerifiedDescriptionCache:
        nonlocal output_reads
        if path == output:
            output_reads += 1
            if output_reads == 2:
                raise fault
        return original(descriptor, path)

    monkeypatch.setattr(publication, "_require_valid_at", reject_second_output)
    with pytest.raises(DescriptionCachePublicationError) as raised:
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    _assert_restored_with_failed_stage(output, raised, previous_identity)
    assert any(item is fault for item in raised.value.failures)
