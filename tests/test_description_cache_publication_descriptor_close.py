"""Independent descriptor-close evidence for publication transactions."""

from __future__ import annotations

from pathlib import Path

import pytest

from w3xtool import description_cache_publication_errors as errors
from w3xtool import description_cache_publication_stage as stage
from w3xtool.description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
)


def test_nominal_success_attempts_both_closes_and_reports_both_faults(
    tmp_path: Path,
) -> None:
    stage_fault = OSError("stage close failed")
    parent_fault = OSError("parent close failed")
    calls: list[int] = []

    def fail_both(descriptor: int) -> None:
        calls.append(descriptor)
        raise stage_fault if descriptor == 11 else parent_fault

    ledger = stage.DescriptorCloseLedger()
    with pytest.raises(PublicationCommitContextError) as raised:
        stage.close_publication_descriptors(
            (("stage", 11), ("parent", 12)),
            None,
            ledger,
            fail_both,
        )

    assert calls == [11, 12]
    assert raised.value.__cause__ is stage_fault
    assert raised.value.failures == (stage_fault, parent_fault)


def test_in_flight_typed_error_keeps_subtype_cause_and_evidence(
    tmp_path: Path,
) -> None:
    del tmp_path
    initial = RuntimeError("initial")
    stage_fault = OSError("stage close failed")
    parent_fault = OSError("parent close failed")
    error = PublicationCommitContextError("already failed")
    error.__cause__ = initial
    before_retained = getattr(error, "retained", ())
    before_transient = getattr(error, "transient", ())

    def fail_both(descriptor: int) -> None:
        raise stage_fault if descriptor == 21 else parent_fault

    stage.close_publication_descriptors(
        (("stage", 21), ("parent", 22)),
        error,
        stage.DescriptorCloseLedger(),
        fail_both,
    )

    assert type(error) is PublicationCommitContextError
    assert error.__cause__ is initial
    assert error.retained == before_retained
    assert error.transient == before_transient
    assert error.failures[-2:] == (stage_fault, parent_fault)


def test_installed_target_subtype_is_not_collapsed_by_close_faults(
    tmp_path: Path,
) -> None:
    installed_type = getattr(errors, "RetainedObjectInstalledContextError")
    record_type = getattr(errors, "RetainedCacheRecord")
    role_type = getattr(errors, "RetainedCacheRole")
    path = tmp_path / "retained"
    record = record_type(path, role_type.PREVIOUS, 1, 2)
    error = installed_type(record, "installed")
    first = OSError("stage close")
    second = OSError("parent close")

    def fail_both(descriptor: int) -> None:
        raise first if descriptor == 31 else second

    stage.close_publication_descriptors(
        (("stage", 31), ("parent", 32)),
        error,
        stage.DescriptorCloseLedger(),
        fail_both,
    )

    assert type(error) is installed_type
    assert error.installed is record
    assert error.failures == (first, second)


def test_close_boundary_is_silent_when_every_descriptor_closes() -> None:
    calls: list[int] = []

    stage.close_publication_descriptors(
        (("stage", 41), ("parent", 42)),
        None,
        stage.DescriptorCloseLedger(),
        calls.append,
    )

    assert calls == [41, 42]
    assert DescriptionCachePublicationError is not None
