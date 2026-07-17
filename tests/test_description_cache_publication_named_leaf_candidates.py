"""Named-leaf classification for rollback and recovery candidates."""

from __future__ import annotations

from pathlib import Path
from typing import Never

import pytest

from tests.description_cache_publication_fixture import (
    assert_failure_order,
    assert_live_retained_records,
    open_parent,
)
from w3xtool import description_cache_publication_named_leaf as named_leaf
from w3xtool.description_cache_publication_errors import (
    PublicationCommitContextError,
)
from w3xtool.description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRole,
)
from w3xtool.description_cache_publication_recovery_state import (
    normalize_recovery_failure,
)
from w3xtool.description_cache_publication_retention_names import RetainedCacheNames
from w3xtool.description_cache_publication_rollback_selection import (
    select_live_identity_path,
)


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def _inject_fault(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    fault: OSError,
) -> None:
    real_object_identity = named_leaf.object_identity

    def classify(parent_descriptor: int, current_name: str) -> tuple[int, int]:
        if current_name == name:
            raise fault
        return real_object_identity(parent_descriptor, current_name)

    monkeypatch.setattr(named_leaf, "object_identity", classify)


@pytest.mark.parametrize(
    ("fault_type", "records_failure"),
    ((FileNotFoundError, False), (OSError, True)),
)
def test_rollback_candidate_named_read_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault_type: type[OSError],
    records_failure: bool,
) -> None:
    candidate = tmp_path / "rollback-candidate"
    parent_identity = _identity(tmp_path)
    fault = fault_type("injected rollback candidate read")
    _inject_fault(monkeypatch, candidate.name, fault)

    with open_parent(tmp_path) as descriptor:
        with pytest.raises(PublicationCommitContextError) as raised:
            _ = select_live_identity_path(
                descriptor,
                tmp_path,
                parent_identity,
                (candidate,),
                (7, 8),
                (),
                (),
            )

    expected_transient = (
        (PublicationTransientRecord(tmp_path, candidate.name, parent_identity, None),)
        if records_failure
        else ()
    )
    assert raised.value.retained == ()
    assert raised.value.transient == expected_transient
    assert_failure_order(raised.value, (fault,) if records_failure else ())
    assert_live_retained_records(raised.value.retained)


@pytest.mark.parametrize(
    ("fault_type", "records_failure"),
    ((FileNotFoundError, False), (OSError, True)),
)
def test_recovery_candidate_named_read_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault_type: type[OSError],
    records_failure: bool,
) -> None:
    candidate = tmp_path / "recovery-candidate"
    parent_identity = _identity(tmp_path)
    names = RetainedCacheNames(tmp_path, "2" * 32)
    fault = fault_type("injected recovery candidate read")
    _inject_fault(monkeypatch, candidate.name, fault)

    def reject_retain(
        _path: Path,
        _identity_value: tuple[int, int],
        _role: RetainedCacheRole,
    ) -> Never:
        raise AssertionError("an unreadable candidate must not be retained")

    def sync_parent(_descriptor: int) -> None:
        return

    if records_failure:
        with open_parent(tmp_path) as descriptor:
            with pytest.raises(PublicationCommitContextError) as raised:
                _ = normalize_recovery_failure(
                    descriptor,
                    tmp_path,
                    parent_identity,
                    (candidate,),
                    (9, 10),
                    (),
                    (),
                    (),
                    names,
                    reject_retain,
                    sync_parent,
                )
        assert raised.value.retained == ()
        assert raised.value.transient == (
            PublicationTransientRecord(tmp_path, candidate.name, parent_identity, None),
        )
        assert_failure_order(raised.value, (fault,))
        assert_live_retained_records(raised.value.retained)
        return

    with open_parent(tmp_path) as descriptor:
        result = normalize_recovery_failure(
            descriptor,
            tmp_path,
            parent_identity,
            (candidate,),
            (9, 10),
            (),
            (),
            (),
            names,
            reject_retain,
            sync_parent,
        )

    assert result == ()
    assert_live_retained_records(result)


__all__: tuple[str, ...] = ()
