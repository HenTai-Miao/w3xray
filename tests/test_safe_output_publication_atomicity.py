"""Continuous-name and crash-state guarantees for atomic replacement."""

from __future__ import annotations

from pathlib import Path

import pytest

from w3xtool.safe_output import write_bytes_safely
from w3xtool.safe_output_models import SafeWriteStatus
from w3xtool import safe_output_publication as publication_api


class _SimulatedCrash(BaseException):
    """Stop the transaction without running an ordinary error rollback."""


def test_existing_public_name_is_present_at_every_directory_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "report.json"
    destination.write_bytes(b"previous")
    observations: list[bytes] = []
    original_sync = publication_api.sync_directory_descriptor

    def observe_public_name(parent_descriptor: int) -> None:
        assert destination.exists()
        observations.append(destination.read_bytes())
        original_sync(parent_descriptor)

    monkeypatch.setattr(
        publication_api,
        "sync_directory_descriptor",
        observe_public_name,
    )

    result = write_bytes_safely(str(tmp_path), destination.name, b"replacement")

    assert result.status is SafeWriteStatus.WRITTEN
    assert observations
    assert destination.read_bytes() == b"replacement"


def test_crash_at_first_directory_sync_never_leaves_public_name_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "report.json"
    destination.write_bytes(b"previous")

    def crash(_parent_descriptor: int) -> None:
        raise _SimulatedCrash

    monkeypatch.setattr(publication_api, "sync_directory_descriptor", crash)

    with pytest.raises(_SimulatedCrash):
        _ = write_bytes_safely(str(tmp_path), destination.name, b"replacement")

    assert destination.exists()
    assert destination.read_bytes() in {b"previous", b"replacement"}
