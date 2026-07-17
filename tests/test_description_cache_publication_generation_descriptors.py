"""Descriptor ownership during final trusted-generation proof."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

import pytest

from tests.description_cache_publication_generation_descriptor_fixture import (
    install_generation_descriptor_fakes,
    stable_generation_round,
)
from tests.trusted_description_cache_fixture import published_cache
from w3xtool import description_cache_publication_generation_evidence as evidence
from w3xtool.description_cache_publication_errors import (
    PublicationCommitContextError,
)
from w3xtool.trusted_description_cache import load_trusted_description_cache


_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def _generation_fixture(
    tmp_path: Path,
) -> tuple[
    int,
    tuple[evidence.ExpectedPublishedGeneration, ...],
    tuple[Path, Path],
]:
    active = published_cache(tmp_path / "active-source")
    previous = published_cache(tmp_path / "previous-source", raw="新版说明")
    active = active.rename(tmp_path / "active")
    previous = previous.rename(tmp_path / "previous")
    expected = tuple(
        evidence.ExpectedPublishedGeneration(
            path,
            _identity(path),
            load_trusted_description_cache(path),
        )
        for path in (active, previous)
    )
    return (
        os.open(tmp_path, _DIRECTORY_FLAGS),
        expected,
        (tmp_path / "stage", tmp_path / "backup"),
    )


def _prove(
    parent_descriptor: int,
    expected: tuple[evidence.ExpectedPublishedGeneration, ...],
    private_paths: tuple[Path, Path],
) -> None:
    evidence.require_stable_generation_set(
        parent_descriptor,
        expected[0].path.parent,
        _identity(expected[0].path.parent),
        expected,
        private_paths,
    )


def test_generation_fstat_failure_closes_every_successful_open_once_in_open_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: two opens succeed before the second descriptor proof faults.
    parent_descriptor, expected, private_paths = _generation_fixture(tmp_path)
    fstat_fault = OSError("generation fstat")
    namespace_fault = OSError("namespace proof")
    close_faults = (OSError("active close"), OSError("previous close"))
    opened, close_attempts = install_generation_descriptor_fakes(
        monkeypatch,
        parent_descriptor,
        expected,
        (expected[0].path.stat(), fstat_fault),
        close_faults,
        namespace_fault,
        stable_generation_round,
    )

    # When: the final generation set acquires and proves both descriptors.
    try:
        with pytest.raises(PublicationCommitContextError) as raised:
            _prove(parent_descriptor, expected, private_paths)
    finally:
        os.close(parent_descriptor)

    # Then: every acquired fd is attempted once after ordered primary evidence.
    assert opened == [101, 102]
    assert close_attempts == opened
    assert type(raised.value) is PublicationCommitContextError
    assert raised.value.__cause__ is fstat_fault
    assert raised.value.failures == (fstat_fault, namespace_fault, *close_faults)


def test_generation_identity_mismatch_preserves_typed_error_when_closes_fault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the second opened generation has a different descriptor identity.
    parent_descriptor, expected, private_paths = _generation_fixture(tmp_path)
    namespace_fault = OSError("namespace proof")
    close_faults = (OSError("active close"), OSError("previous close"))
    opened, close_attempts = install_generation_descriptor_fakes(
        monkeypatch,
        parent_descriptor,
        expected,
        (expected[0].path.stat(), tmp_path.stat()),
        close_faults,
        namespace_fault,
        stable_generation_round,
    )

    # When: descriptor identity validation rejects the second generation.
    try:
        with pytest.raises(PublicationCommitContextError) as raised:
            _prove(parent_descriptor, expected, private_paths)
    finally:
        os.close(parent_descriptor)

    # Then: cleanup cannot replace the typed mismatch or reverse close order.
    assert opened == [101, 102]
    assert close_attempts == opened
    assert type(raised.value) is PublicationCommitContextError
    assert raised.value.__cause__ is None
    assert raised.value.detail.startswith(
        "published generation changed during final open; NEEDS_CONTEXT"
    )
    assert raised.value.failures == (namespace_fault, *close_faults)


def test_nominal_generation_proof_uses_shared_close_boundary_for_every_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: both proof rounds are stable but both close callbacks raise RuntimeError.
    parent_descriptor, expected, private_paths = _generation_fixture(tmp_path)
    close_faults = (RuntimeError("active close"), RuntimeError("previous close"))
    opened, close_attempts = install_generation_descriptor_fakes(
        monkeypatch,
        parent_descriptor,
        expected,
        tuple(item.path.stat() for item in expected),
        close_faults,
        None,
        stable_generation_round,
    )

    # When: the nominal generation proof leaves its unified ownership boundary.
    try:
        with pytest.raises(PublicationCommitContextError) as raised:
            _prove(parent_descriptor, expected, private_paths)
    finally:
        os.close(parent_descriptor)

    # Then: the boundary attempts both closes and reports their exact order.
    assert opened == [101, 102]
    assert close_attempts == opened
    assert raised.value.__cause__ is close_faults[0]
    assert raised.value.failures == close_faults


def test_generation_round_runtime_error_still_closes_every_owned_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: both descriptors are owned before an ordinary proof-round failure.
    parent_descriptor, expected, private_paths = _generation_fixture(tmp_path)
    round_fault = RuntimeError("generation round")

    def fail_round(
        descriptor: int,
        descriptors: tuple[int, ...],
        generations: tuple[evidence.ExpectedPublishedGeneration, ...],
        paths: tuple[Path, Path],
    ) -> evidence._GenerationRound:
        del descriptor, descriptors, generations, paths
        raise round_fault

    opened, close_attempts = install_generation_descriptor_fakes(
        monkeypatch,
        parent_descriptor,
        expected,
        tuple(item.path.stat() for item in expected),
        (None, None),
        None,
        fail_round,
    )

    # When: an ordinary exception exits the first generation round.
    try:
        with pytest.raises(RuntimeError) as raised:
            _prove(parent_descriptor, expected, private_paths)
    finally:
        os.close(parent_descriptor)

    # Then: the same exception escapes only after every fd close is attempted.
    assert raised.value is round_fault
    assert opened == [101, 102]
    assert close_attempts == opened


__all__: tuple[str, ...] = ()
