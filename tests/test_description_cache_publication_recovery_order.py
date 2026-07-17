"""Every post-reverse-exchange recovery boundary."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Final

import pytest

from tests.description_cache_publication_fixture import (
    assert_live_retained_records,
    exchange_in_parent,
    open_parent,
    rename_in_parent,
)
from tests.trusted_description_cache_fixture import published_cache
from w3xtool import description_cache_publication_recovery as recovery
from w3xtool.description_cache_publication_errors import (
    DescriptionCachePublicationError,
)
from w3xtool.description_cache_publication_models import (
    RetainedCacheRecord,
    RetainedCacheRole,
)
from w3xtool.description_cache_publication_retention_durability import (
    retain_durably,
)
from w3xtool.description_cache_publication_retention_names import RetainedCacheNames
from w3xtool.trusted_description_cache import (
    VerifiedDescriptionCache,
    load_trusted_description_cache,
)


@dataclass(frozen=True, slots=True)
class _Boundary:
    label: str
    exchange_call: int | None = None
    identity_call: int | None = None
    validation_call: int | None = None
    rename_call: int | None = None
    sync_call: int | None = None


_BOUNDARIES: Final = (
    _Boundary("reverse-exchange-return", exchange_call=1),
    _Boundary("restored-output-identity", identity_call=3),
    _Boundary("recovered-stage-identity", identity_call=4),
    _Boundary("restored-output-validation-identity", identity_call=5),
    _Boundary("recovered-stage-validation-identity", identity_call=6),
    _Boundary("post-rename-stage-identity", identity_call=7),
    _Boundary("final-stage-validation-identity", identity_call=8),
    _Boundary("reverse-exchange-sync", sync_call=1),
    _Boundary("restored-output-validation", validation_call=2),
    _Boundary("recovered-stage-validation", validation_call=3),
    _Boundary("recovery-to-stage-rename", rename_call=1),
    _Boundary("recovery-to-stage-sync", sync_call=2),
    _Boundary("final-stage-proof", validation_call=4),
    _Boundary("failed-stage-retain-move", rename_call=2),
    _Boundary("failed-stage-retain-sync", sync_call=3),
)


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def _raw(path: Path) -> str:
    return (
        load_trusted_description_cache(path)
        .cache.lookup("物品", "ratf", "扩展提示", None)[0]
        .raw_value
    )


@pytest.mark.parametrize("boundary", _BOUNDARIES, ids=lambda item: item.label)
def test_post_reverse_exchange_fault_restores_old_and_retains_new(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: _Boundary,
) -> None:
    # Given: rollback starts with new at output and old at the recovery candidate.
    old_source = published_cache(tmp_path / "old-source", raw="first")
    new_source = published_cache(tmp_path / "new-source", raw="second")
    output = new_source.rename(tmp_path / "trusted")
    names = RetainedCacheNames(tmp_path, "1" * 32)
    recovery_path = old_source.rename(names.path(RetainedCacheRole.RECOVERY))
    stage = tmp_path / ".w3xray-description-cache-stage-1"
    old_identity = _identity(recovery_path)
    new_identity = _identity(output)
    fault = OSError(boundary.label)
    counts = {"exchange": 0, "identity": 0, "validation": 0, "rename": 0, "sync": 0}
    original_identity = recovery.directory_identity

    def exchange(descriptor: int, source: str, target: str) -> None:
        counts["exchange"] += 1
        exchange_in_parent(descriptor, source, target)
        if counts["exchange"] == boundary.exchange_call:
            raise fault

    def named_identity(descriptor: int, name: str) -> tuple[int, int]:
        counts["identity"] += 1
        if counts["identity"] == boundary.identity_call:
            raise fault
        return original_identity(descriptor, name)

    def validate(path: Path) -> VerifiedDescriptionCache:
        counts["validation"] += 1
        if counts["validation"] == boundary.validation_call:
            raise fault
        return load_trusted_description_cache(path)

    def rename(descriptor: int, source: str, target: str) -> None:
        counts["rename"] += 1
        rename_in_parent(descriptor, source, target)
        if counts["rename"] == boundary.rename_call:
            raise fault

    def sync(descriptor: int) -> None:
        counts["sync"] += 1
        if counts["sync"] == boundary.sync_call:
            raise fault
        os.fsync(descriptor)

    monkeypatch.setattr(recovery, "directory_identity", named_identity)

    # When: the selected proof, rename, validation, retain, or sync boundary faults.
    with open_parent(tmp_path) as descriptor:

        def retain(
            path: Path,
            expected: tuple[int, int],
            role: RetainedCacheRole,
        ) -> RetainedCacheRecord:
            return retain_durably(
                descriptor,
                tmp_path,
                _identity(tmp_path),
                path,
                expected,
                names,
                role,
                rename,
                sync,
            )

        with pytest.raises(DescriptionCachePublicationError) as raised:
            _ = recovery.restore_previous_generation(
                descriptor,
                _identity(tmp_path),
                output,
                new_identity,
                recovery_path,
                old_identity,
                stage,
                names,
                exchange,
                rename,
                validate,
                retain,
                sync,
                (),
                (),
                "injected recovery boundary",
            )

    # Then: old is active, new is live failed-stage, and no stale recovery remains.
    assert _identity(output) == old_identity
    assert _raw(output) == "first"
    failed_stage = names.path(RetainedCacheRole.FAILED_STAGE)
    assert _identity(failed_stage) == new_identity
    assert _raw(failed_stage) == "second"
    assert any(item is fault for item in raised.value.failures)
    assert_live_retained_records(raised.value.retained)
    assert any(
        item.path == failed_stage and item.identity == new_identity
        for item in raised.value.retained
    )
    assert all(
        not (item.path == recovery_path and item.identity == old_identity)
        for item in raised.value.retained
    )


__all__: tuple[str, ...] = ()
