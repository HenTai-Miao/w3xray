"""Named-leaf classification while rebuilding publication evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, assert_never

import pytest

from tests.description_cache_publication_fixture import assert_live_retained_records
from w3xtool import description_cache_publication_named_leaf as named_leaf
from w3xtool.description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRecord,
    RetainedCacheRole,
)
from w3xtool.description_cache_publication_named_leaf import (
    reprove_retained,
    reprove_transient,
)
from w3xtool.description_cache_publication_stage_normalization import (
    capture_transient_record,
)


type EvidenceSite = Literal["retained", "transient", "stage"]


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


@pytest.mark.parametrize("site", ("retained", "transient", "stage"))
@pytest.mark.parametrize(
    ("fault_type", "records_failure"),
    ((FileNotFoundError, False), (OSError, True)),
)
def test_evidence_named_read_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    site: EvidenceSite,
    fault_type: type[OSError],
    records_failure: bool,
) -> None:
    path = tmp_path / f"{site}-candidate"
    parent_identity = _identity(tmp_path)
    fault = fault_type(f"injected {site} evidence read")

    def fail_identity(_parent_descriptor: int, _name: str) -> tuple[int, int]:
        raise fault

    monkeypatch.setattr(named_leaf, "object_identity", fail_identity)

    match site:
        case "retained":
            actual = reprove_retained(
                101,
                tmp_path,
                parent_identity,
                (
                    RetainedCacheRecord(
                        path,
                        RetainedCacheRole.PREVIOUS,
                        7,
                        8,
                    ),
                ),
            )
        case "transient":
            actual = reprove_transient(
                101,
                tmp_path,
                parent_identity,
                (
                    PublicationTransientRecord(
                        tmp_path, path.name, parent_identity, None
                    ),
                ),
            )
        case "stage":
            actual = capture_transient_record(
                101,
                path,
                parent_identity,
                None,
            )
        case unreachable:
            assert_never(unreachable)

    expected_transient = (
        (PublicationTransientRecord(tmp_path, path.name, parent_identity, None),)
        if records_failure
        else ()
    )
    assert actual.retained == ()
    assert_live_retained_records(actual.retained)
    assert actual.transient == expected_transient
    expected_failures = (fault,) if records_failure else ()
    assert len(actual.failures) == len(expected_failures)
    assert all(
        current is expected
        for current, expected in zip(
            actual.failures,
            expected_failures,
            strict=True,
        )
    )


__all__: tuple[str, ...] = ()
