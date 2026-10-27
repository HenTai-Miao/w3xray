"""Named-leaf absence and unreadability during raw retention."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from gametool import description_cache_publication_named_leaf as named_leaf
from gametool.description_cache_publication_named_leaf import read_named_leaf


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


__all__: tuple[str, ...] = ()
