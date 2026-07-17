"""Named-read classification in both complete stage-location scans."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.description_cache_publication_fixture import (
    assert_failure_order,
    bound_stage,
)
from w3xtool import description_cache_publication_named_leaf as named_leaf
from w3xtool.description_cache_publication_errors import (
    PublicationCommitContextError,
)
from w3xtool.description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRole,
)
from w3xtool.description_cache_publication_retention_names import RetainedCacheNames
from w3xtool.description_cache_publication_stage_location import locate_consumed_stage


@pytest.mark.parametrize("start_ordinal", (1, 2))
@pytest.mark.parametrize(
    ("fault_type", "records_failure"),
    ((FileNotFoundError, False), (OSError, True)),
)
def test_locator_scan_named_read_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    start_ordinal: int,
    fault_type: type[OSError],
    records_failure: bool,
) -> None:
    stage = tmp_path / ".w3xray-description-cache-stage-a"
    output = tmp_path / "trusted"
    stage.mkdir()
    names = RetainedCacheNames(tmp_path, "3" * 32)
    recovery = names.path(RetainedCacheRole.RECOVERY)
    fault = fault_type(f"injected locator scan {start_ordinal} read")
    real_object_identity = named_leaf.object_identity
    recovery_reads = 0

    def inject_from_selected_scan(
        parent_descriptor: int,
        name: str,
    ) -> tuple[int, int]:
        nonlocal recovery_reads
        if name == recovery.name:
            recovery_reads += 1
            if recovery_reads >= start_ordinal:
                raise fault
        return real_object_identity(parent_descriptor, name)

    monkeypatch.setattr(named_leaf, "object_identity", inject_from_selected_scan)

    with bound_stage(stage) as bound:
        _ = stage.rename(output)
        output_identity = bound.stage_identity
        parent_identity = bound.parent_identity
        with pytest.raises(PublicationCommitContextError) as raised:
            _ = locate_consumed_stage(
                bound,
                output,
                names,
                detail="forced named-read audit",
            )

    output_probe = PublicationTransientRecord(
        tmp_path,
        output.name,
        parent_identity,
        output_identity,
        output_identity,
    )
    expected_transient = (
        (
            PublicationTransientRecord(
                tmp_path,
                recovery.name,
                parent_identity,
                None,
            ),
            output_probe,
        )
        if records_failure
        else (output_probe,)
    )
    assert raised.value.transient == expected_transient
    assert_failure_order(raised.value, (fault,) if records_failure else ())


__all__: tuple[str, ...] = ()
