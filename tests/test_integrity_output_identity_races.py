"""Final-name identity races for integrity report publication."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.retained_integrity_fixture import active_cache
from w3xtool import integrity_output as output_api
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
