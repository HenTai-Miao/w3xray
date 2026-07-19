"""Pre-exchange identity races for immutable integrity-report history."""

from __future__ import annotations

from pathlib import Path

import pytest

from w3xtool import integrity_report_publication as publication_api
from w3xtool.integrity_cli import run_integrity_cli
from w3xtool.integrity_report_history_directory import BoundIntegrityHistoryStage


def _snapshot(root: Path, output: Path) -> int:
    return run_integrity_cli(
        ("snapshot", "--root", f"root={root}", "--output", str(output))
    )


def test_staged_report_replacement_before_exchange_never_reaches_public_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an existing report and a replacement of the proved new-report stage.
    root = tmp_path / "maps"
    root.mkdir()
    source = root / "a.w3x"
    source.write_bytes(b"first")
    output = tmp_path / "snapshot.json"
    assert _snapshot(root, output) == 0
    previous_payload = output.read_bytes()
    retained_new_report = tmp_path / "retained-new-report"
    attacker_payload = b"concurrent stage replacement"
    original = publication_api.prepare_integrity_history_stage

    def replace_new_report_stage(
        parent_descriptor: int,
        destination: Path,
        forbidden_identities: frozenset[tuple[int, int]],
    ) -> BoundIntegrityHistoryStage:
        history = original(parent_descriptor, destination, forbidden_identities)
        (stage,) = tmp_path.glob(".w3xray-stage-*.tmp")
        stage.rename(retained_new_report)
        stage.write_bytes(attacker_payload)
        return history

    monkeypatch.setattr(
        publication_api,
        "prepare_integrity_history_stage",
        replace_new_report_stage,
    )

    # When: publication reaches the final identity proof before exchange.
    source.write_bytes(b"second")
    code = _snapshot(root, output)

    # Then: the old public report and both concurrent evidence files remain.
    assert code == 2
    assert output.read_bytes() == previous_payload
    assert retained_new_report.read_bytes() != attacker_payload
    (replacement,) = tmp_path.glob(".w3xray-stage-*.tmp")
    assert replacement.read_bytes() == attacker_payload


def test_public_report_replacement_before_exchange_is_never_overwritten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an existing report and a concurrent replacement of its public name.
    root = tmp_path / "maps"
    root.mkdir()
    source = root / "a.w3x"
    source.write_bytes(b"first")
    output = tmp_path / "snapshot.json"
    assert _snapshot(root, output) == 0
    previous_payload = output.read_bytes()
    retained_previous = tmp_path / "retained-previous-report"
    concurrent_payload = b"concurrent public replacement"
    original = publication_api.prepare_integrity_history_stage

    def replace_public_report(
        parent_descriptor: int,
        destination: Path,
        forbidden_identities: frozenset[tuple[int, int]],
    ) -> BoundIntegrityHistoryStage:
        history = original(parent_descriptor, destination, forbidden_identities)
        output.rename(retained_previous)
        output.write_bytes(concurrent_payload)
        return history

    monkeypatch.setattr(
        publication_api,
        "prepare_integrity_history_stage",
        replace_public_report,
    )

    # When: publication reaches the final identity proof before exchange.
    source.write_bytes(b"second")
    code = _snapshot(root, output)

    # Then: the concurrent public name wins and the owned stage is consumed.
    assert code == 2
    assert output.read_bytes() == concurrent_payload
    assert retained_previous.read_bytes() == previous_payload
    assert not tuple(tmp_path.glob(".w3xray-stage-*.tmp"))
