"""Deterministic binding and identity races for integrity-report history."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from w3xtool import integrity_report_publication as publication_api
from w3xtool import integrity_report_replacement as replacement_api
from w3xtool.atomic_rename import rename_exchange as real_rename_exchange
from w3xtool.integrity_cli import run_integrity_cli
from w3xtool.integrity_report_history_directory import BoundIntegrityHistoryStage


_HISTORY_ROOT = ".w3xray-integrity-history"
_MANIFEST_NAME = "历史清单.json"
_REPORT_NAME = "report.json"


def _snapshot(root: Path, output: Path) -> int:
    return run_integrity_cli(
        ("snapshot", "--root", f"root={root}", "--output", str(output))
    )


def _generations(output: Path) -> tuple[Path, ...]:
    key = hashlib.sha256(output.name.encode("utf-8")).hexdigest()
    bucket = output.parent / _HISTORY_ROOT / key
    return tuple(path for path in bucket.iterdir() if not path.name.startswith("."))


def test_untrusted_history_root_stops_overwrite_without_losing_public_report(
    tmp_path: Path,
) -> None:
    # Given: an existing report and a history-root symlink to an outside directory.
    root = tmp_path / "maps"
    root.mkdir()
    source = root / "a.w3x"
    source.write_bytes(b"first")
    output = tmp_path / "snapshot.json"
    assert _snapshot(root, output) == 0
    previous_payload = output.read_bytes()
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / _HISTORY_ROOT).symlink_to(outside, target_is_directory=True)

    # When: publication attempts to archive the current report.
    source.write_bytes(b"second")
    code = _snapshot(root, output)

    # Then: publication fails closed before replacing or writing outside.
    assert code == 2
    assert output.read_bytes() == previous_payload
    assert tuple(outside.iterdir()) == ()
    assert not tuple(tmp_path.glob(".w3xray-stage-*.tmp"))


def test_history_root_replacement_before_exchange_preserves_public_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a valid current report and a seam that replaces the new history root.
    root = tmp_path / "maps"
    root.mkdir()
    source = root / "a.w3x"
    source.write_bytes(b"first")
    output = tmp_path / "snapshot.json"
    assert _snapshot(root, output) == 0
    previous_payload = output.read_bytes()
    moved = tmp_path / "moved-history"
    outside = tmp_path / "outside"
    outside.mkdir()
    original = publication_api.prepare_integrity_history_stage

    def replace_history_root(
        parent_descriptor: int,
        destination: Path,
        forbidden_identities: frozenset[tuple[int, int]],
    ) -> BoundIntegrityHistoryStage:
        stage = original(parent_descriptor, destination, forbidden_identities)
        history_root = output.parent / _HISTORY_ROOT
        history_root.rename(moved)
        history_root.symlink_to(outside, target_is_directory=True)
        return stage

    monkeypatch.setattr(
        publication_api,
        "prepare_integrity_history_stage",
        replace_history_root,
    )

    # When: overwrite reaches the final pre-exchange history binding proof.
    source.write_bytes(b"second")
    code = _snapshot(root, output)

    # Then: the old public report remains and the replacement is never entered.
    assert code == 2
    assert output.read_bytes() == previous_payload
    assert tuple(outside.iterdir()) == ()
    assert not tuple(tmp_path.glob(".w3xray-stage-*.tmp"))


def test_history_root_replacement_at_exchange_reports_retained_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a current report and a race immediately after the last root proof.
    root = tmp_path / "maps"
    root.mkdir()
    source = root / "a.w3x"
    source.write_bytes(b"first")
    output = tmp_path / "snapshot.json"
    assert _snapshot(root, output) == 0
    previous_payload = output.read_bytes()
    moved = tmp_path / "moved-history"
    outside = tmp_path / "outside"
    outside.mkdir()

    def replace_then_exchange(
        source_descriptor: int,
        source_name: str,
        destination_descriptor: int,
        destination_name: str,
    ) -> None:
        history_root = output.parent / _HISTORY_ROOT
        history_root.rename(moved)
        history_root.symlink_to(outside, target_is_directory=True)
        real_rename_exchange(
            source_descriptor,
            source_name,
            destination_descriptor,
            destination_name,
        )

    monkeypatch.setattr(replacement_api, "rename_exchange", replace_then_exchange)

    # When: exchange commits before the replaced history binding is re-proved.
    source.write_bytes(b"second")
    code = _snapshot(root, output)

    # Then: success is refused and the displaced old report remains recoverable.
    assert code == 2
    assert output.read_bytes() != previous_payload
    assert previous_payload in {
        path.read_bytes() for path in moved.rglob("*") if path.is_file()
    }
    assert tuple(outside.iterdir()) == ()


def test_archived_report_mutation_after_final_rename_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one current report and a mutation at the finalized-history sync.
    root = tmp_path / "maps"
    root.mkdir()
    source = root / "a.w3x"
    source.write_bytes(b"first")
    output = tmp_path / "snapshot.json"
    assert _snapshot(root, output) == 0
    original_sync = replacement_api.sync_directory_descriptor
    syncs = 0

    def mutate_finalized_report(descriptor: int) -> None:
        nonlocal syncs
        syncs += 1
        original_sync(descriptor)
        if syncs == 2:
            (generation,) = _generations(output)
            with (generation / _REPORT_NAME).open("ab") as stream:
                _ = stream.write(b"tamper")

    monkeypatch.setattr(
        replacement_api,
        "sync_directory_descriptor",
        mutate_finalized_report,
    )

    # When: the replacement archives the prior report and reaches final sync.
    source.write_bytes(b"second")
    code = _snapshot(root, output)

    # Then: the manifest/payload mismatch prevents a successful publication claim.
    assert code == 2
    (generation,) = _generations(output)
    manifest = json.loads((generation / _MANIFEST_NAME).read_text(encoding="utf-8"))
    archived = (generation / _REPORT_NAME).read_bytes()
    assert hashlib.sha256(archived).hexdigest() != manifest["artifacts"][0]["sha256"]


def test_unproved_exchange_never_deletes_the_staged_new_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an exchange race that preserves old, new, and concurrent reports.
    root = tmp_path / "maps"
    root.mkdir()
    source = root / "a.w3x"
    source.write_bytes(b"first")
    output = tmp_path / "snapshot.json"
    assert _snapshot(root, output) == 0
    previous_payload = output.read_bytes()
    old_recovery = tmp_path / "old-report-recovery"
    staged_path: Path | None = None
    staged_payload = b""

    def displace_every_result(
        source_descriptor: int,
        source_name: str,
        destination_descriptor: int,
        destination_name: str,
    ) -> None:
        nonlocal staged_path, staged_payload
        real_rename_exchange(
            source_descriptor,
            source_name,
            destination_descriptor,
            destination_name,
        )
        staged_path = tmp_path / source_name
        staged_path.rename(old_recovery)
        staged_payload = output.read_bytes()
        output.rename(staged_path)
        output.write_bytes(b"concurrent")

    monkeypatch.setattr(replacement_api, "rename_exchange", displace_every_result)

    # When: post-exchange identity proof rejects the concurrent public result.
    source.write_bytes(b"second")
    code = _snapshot(root, output)

    # Then: none of the three distinct evidence payloads is automatically deleted.
    assert code == 2
    assert output.read_bytes() == b"concurrent"
    assert old_recovery.read_bytes() == previous_payload
    assert staged_path is not None
    assert staged_path.read_bytes() == staged_payload
