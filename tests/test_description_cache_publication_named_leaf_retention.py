"""Named-leaf absence and unreadability during raw retention."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, assert_never

import pytest

from tests.description_cache_publication_fixture import (
    assert_failure_order,
    assert_live_retained_records,
    open_parent,
    rename_in_parent,
)
from w3xtool import description_cache_publication_named_leaf as named_leaf
from w3xtool.description_cache_publication_errors import (
    PublicationCommitContextError,
)
from w3xtool.description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRole,
)
from w3xtool.description_cache_publication_named_leaf import read_named_leaf
from w3xtool.description_cache_publication_retention import retain_object
from w3xtool.description_cache_publication_retention_names import RetainedCacheNames


type RetentionSide = Literal["source", "target"]


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


@pytest.mark.parametrize(
    ("fault_type", "readable", "records_failure"),
    (
        (FileNotFoundError, True, False),
        (OSError, False, True),
    ),
)
def test_read_named_leaf_classifies_exact_exception(
    monkeypatch: pytest.MonkeyPatch,
    fault_type: type[OSError],
    readable: bool,
    records_failure: bool,
) -> None:
    fault = fault_type("injected named-leaf classification")

    def fail_identity(_parent_descriptor: int, _name: str) -> tuple[int, int]:
        raise fault

    monkeypatch.setattr(named_leaf, "object_identity", fail_identity)

    proof = read_named_leaf(101, "candidate")

    assert proof.readable is readable
    assert proof.identity is None
    assert proof.failure is (fault if records_failure else None)


@pytest.mark.parametrize(
    ("side", "fault_type", "records_failure", "moved"),
    (
        ("source", FileNotFoundError, False, False),
        ("source", OSError, True, False),
        ("target", FileNotFoundError, False, True),
        ("target", OSError, True, True),
    ),
)
def test_raw_retention_named_read_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    side: RetentionSide,
    fault_type: type[OSError],
    records_failure: bool,
    moved: bool,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    expected = _identity(source)
    parent_identity = _identity(tmp_path)
    names = RetainedCacheNames(tmp_path, "1" * 32)
    target = names.path(RetainedCacheRole.PREVIOUS)
    match side:
        case "source":
            probed = source
        case "target":
            probed = target
        case unreachable:
            assert_never(unreachable)
    fault = fault_type(f"injected {side} named read")
    real_object_identity = named_leaf.object_identity

    def inject_fault(parent_descriptor: int, name: str) -> tuple[int, int]:
        if name == probed.name:
            raise fault
        return real_object_identity(parent_descriptor, name)

    monkeypatch.setattr(named_leaf, "object_identity", inject_fault)

    with open_parent(tmp_path) as descriptor:
        with pytest.raises(PublicationCommitContextError) as raised:
            _ = retain_object(
                descriptor,
                parent_identity,
                source,
                expected,
                names,
                RetainedCacheRole.PREVIOUS,
                rename_in_parent,
            )

    expected_transient = (
        (PublicationTransientRecord(tmp_path, probed.name, parent_identity, None),)
        if records_failure
        else ()
    )
    assert raised.value.retained == ()
    assert raised.value.transient == expected_transient
    assert_failure_order(raised.value, (fault,) if records_failure else ())
    assert target.exists() is moved
    assert_live_retained_records(raised.value.retained)


__all__: tuple[str, ...] = ()
