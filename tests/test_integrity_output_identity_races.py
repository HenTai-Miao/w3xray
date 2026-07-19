"""Final-name identity races for integrity report publication."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.retained_integrity_fixture import active_cache
from w3xtool import integrity_output as output_api
from w3xtool import integrity_report_replacement as history_replacement_api
from w3xtool import safe_output_publication as publication_api
from w3xtool.integrity_cli import run_integrity_cli


_ATTACKER_PAYLOAD = b"concurrent replacement"


def _argv(active: Path, output: Path) -> tuple[str, ...]:
    return (
        "retained-cache",
        "--active-root",
        str(active),
        "--output",
        str(output),
    )


@pytest.mark.parametrize("existing", (False, True))
def test_final_name_replacement_is_not_accepted_as_the_published_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing: bool,
) -> None:
    active = active_cache(tmp_path)
    output = tmp_path / "report.json"
    if existing:
        output.write_bytes(b"prior report")
    original = output_api.BoundIntegrityOutput._publication_error
    checks = 0

    def replace_after_publish(
        bound: output_api.BoundIntegrityOutput,
        require_protected: Callable[[], None] | None,
    ) -> str | None:
        nonlocal checks
        checks += 1
        if checks == 2:
            output.unlink()
            output.write_bytes(_ATTACKER_PAYLOAD)
        return original(bound, require_protected)

    monkeypatch.setattr(
        output_api.BoundIntegrityOutput,
        "_publication_error",
        replace_after_publish,
    )

    code = run_integrity_cli(_argv(active, output))

    assert code == 2
    assert output.read_bytes() == _ATTACKER_PAYLOAD


@pytest.mark.parametrize("existing", (False, True))
def test_rollback_never_removes_or_overwrites_a_final_name_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing: bool,
) -> None:
    active = active_cache(tmp_path)
    output = tmp_path / "report.json"
    if existing:
        output.write_bytes(b"prior report")
    checks = 0

    def replace_and_reject(
        _bound: output_api.BoundIntegrityOutput,
        _require_protected: Callable[[], None] | None,
    ) -> str | None:
        nonlocal checks
        checks += 1
        if checks == 2:
            output.unlink()
            output.write_bytes(_ATTACKER_PAYLOAD)
            return "simulated protected boundary change"
        return None

    monkeypatch.setattr(
        output_api.BoundIntegrityOutput,
        "_publication_error",
        replace_and_reject,
    )

    code = run_integrity_cli(_argv(active, output))

    assert code == 2
    assert output.read_bytes() == _ATTACKER_PAYLOAD


@pytest.mark.parametrize(
    "sync_boundary",
    ("new", "history-stage", "history-bucket", "history-parent"),
)
def test_final_name_replacement_during_directory_sync_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sync_boundary: str,
) -> None:
    active = active_cache(tmp_path)
    output = tmp_path / "report.json"
    if sync_boundary != "new":
        output.write_bytes(b"prior report")
    target_call = {
        "new": 1,
        "history-stage": 1,
        "history-bucket": 2,
        "history-parent": 3,
    }[sync_boundary]
    original = (
        publication_api.sync_directory_descriptor
        if sync_boundary == "new"
        else history_replacement_api.sync_directory_descriptor
    )
    syncs = 0

    def replace_during_sync(descriptor: int) -> None:
        nonlocal syncs
        syncs += 1
        original(descriptor)
        if syncs == target_call:
            output.unlink()
            output.write_bytes(_ATTACKER_PAYLOAD)

    target = publication_api if sync_boundary == "new" else history_replacement_api
    monkeypatch.setattr(target, "sync_directory_descriptor", replace_during_sync)

    code = run_integrity_cli(_argv(active, output))

    assert syncs >= target_call
    assert code == 2
    assert output.read_bytes() == _ATTACKER_PAYLOAD


@pytest.mark.parametrize("existing", (False, True))
def test_rollback_preserves_a_concurrent_symlink_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing: bool,
) -> None:
    active = active_cache(tmp_path)
    output = tmp_path / "report.json"
    if existing:
        output.write_bytes(b"prior report")
    outside = tmp_path / "outside"
    outside.write_bytes(_ATTACKER_PAYLOAD)
    checks = 0

    def replace_with_symlink(
        _bound: output_api.BoundIntegrityOutput,
        _require_protected: Callable[[], None] | None,
    ) -> str | None:
        nonlocal checks
        checks += 1
        if checks == 2:
            output.unlink()
            output.symlink_to(outside)
            return "simulated protected boundary change"
        return None

    monkeypatch.setattr(
        output_api.BoundIntegrityOutput,
        "_publication_error",
        replace_with_symlink,
    )

    code = run_integrity_cli(_argv(active, output))

    assert code == 2
    assert output.is_symlink()
    assert output.readlink() == outside
    assert outside.read_bytes() == _ATTACKER_PAYLOAD
