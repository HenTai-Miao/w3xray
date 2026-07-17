"""Typed descriptor fault harness for final generation-evidence tests."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
from typing import assert_never

import pytest

from w3xtool import description_cache_publication_generation_evidence as evidence
from w3xtool.description_cache_publication_models import RetainedEvidenceReproof


type GenerationRoundAction = Callable[
    [
        int,
        tuple[int, ...],
        tuple[evidence.ExpectedPublishedGeneration, ...],
        tuple[Path, Path],
    ],
    evidence._GenerationRound,
]


def install_generation_descriptor_fakes(
    monkeypatch: pytest.MonkeyPatch,
    parent_descriptor: int,
    expected: tuple[evidence.ExpectedPublishedGeneration, ...],
    fstat_outcomes: tuple[os.stat_result | OSError, ...],
    close_outcomes: tuple[Exception | None, ...],
    namespace_fault: OSError | None,
    round_action: GenerationRoundAction,
) -> tuple[list[int], list[int]]:
    """Install typed open/proof/close outcomes and return their event ledgers."""
    fake_descriptors = tuple(range(101, 101 + len(expected)))
    descriptor_by_name = dict(
        zip((item.path.name for item in expected), fake_descriptors, strict=True)
    )
    outcome_by_descriptor = dict(zip(fake_descriptors, fstat_outcomes, strict=True))
    close_by_descriptor = dict(zip(fake_descriptors, close_outcomes, strict=True))
    opened: list[int] = []
    close_attempts: list[int] = []
    real_open = os.open
    real_fstat = os.fstat
    real_close = os.close

    def fake_open(
        path: str | bytes | Path,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        descriptor = descriptor_by_name.get(os.fsdecode(path))
        if descriptor is None or dir_fd != parent_descriptor:
            return real_open(path, flags, mode, dir_fd=dir_fd)
        opened.append(descriptor)
        return descriptor

    def fake_fstat(descriptor: int) -> os.stat_result:
        outcome = outcome_by_descriptor.get(descriptor)
        match outcome:
            case None:
                return real_fstat(descriptor)
            case OSError() as fault:
                raise fault
            case os.stat_result() as result:
                return result
            case unreachable:
                assert_never(unreachable)

    def fake_close(descriptor: int) -> None:
        outcome = close_by_descriptor.get(descriptor)
        if descriptor not in close_by_descriptor:
            real_close(descriptor)
            return
        close_attempts.append(descriptor)
        if outcome is not None:
            raise outcome

    def namespace_evidence(
        descriptor: int,
        parent: Path,
        parent_identity: tuple[int, int],
        generations: tuple[evidence.ExpectedPublishedGeneration, ...],
        private_paths: tuple[Path, Path],
    ) -> RetainedEvidenceReproof:
        del descriptor, parent, parent_identity, generations, private_paths
        failures = () if namespace_fault is None else (namespace_fault,)
        return RetainedEvidenceReproof(failures=failures)

    monkeypatch.setattr(os, "open", fake_open)
    monkeypatch.setattr(os, "fstat", fake_fstat)
    monkeypatch.setattr(os, "close", fake_close)
    monkeypatch.setattr(evidence, "_read_generation_round", round_action)
    monkeypatch.setattr(evidence, "_namespace_evidence", namespace_evidence)
    return opened, close_attempts


def stable_generation_round(
    parent_descriptor: int,
    descriptors: tuple[int, ...],
    generations: tuple[evidence.ExpectedPublishedGeneration, ...],
    private_paths: tuple[Path, Path],
) -> evidence._GenerationRound:
    """Return a stable empty proof round for descriptor ownership tests."""
    del parent_descriptor, descriptors, generations, private_paths
    return evidence._GenerationRound((), (None, None), (None, None))


__all__ = (
    "install_generation_descriptor_fakes",
    "stable_generation_round",
)
