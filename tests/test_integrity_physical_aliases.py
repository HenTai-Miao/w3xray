"""Physical filesystem aliases cannot bypass integrity path boundaries."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.retained_integrity_fixture import active_cache, retained
from w3xtool import integrity_output as output_api
from w3xtool.integrity_cli import run_integrity_cli


def _require_same_directory(actual: Path, alias: Path, reason: str) -> None:
    try:
        same = os.path.samefile(actual, alias)
    except FileNotFoundError:
        same = False
    if not same:
        pytest.skip(reason)


def _snapshot_argv(
    roots: tuple[tuple[str, Path], ...],
    output: Path,
) -> tuple[str, ...]:
    values: list[str] = ["snapshot"]
    for label, root in roots:
        values.extend(("--root", f"{label}={root}"))
    values.extend(("--output", str(output)))
    return tuple(values)


def _retained_argv(active: Path, output: Path) -> tuple[str, ...]:
    return (
        "retained-cache",
        "--active-root",
        str(active),
        "--output",
        str(output),
    )


def test_snapshot_rejects_case_insensitive_physical_root_aliases(
    tmp_path: Path,
) -> None:
    actual = tmp_path / "CaseRoot"
    actual.mkdir()
    alias = tmp_path / "caseroot"
    _require_same_directory(actual, alias, "filesystem is case-sensitive")
    (actual / "payload").write_bytes(b"evidence")
    output = tmp_path / "snapshot.json"

    code = run_integrity_cli(
        _snapshot_argv((("actual", actual), ("alias", alias)), output)
    )

    assert code == 2
    assert not output.exists()


def test_snapshot_rejects_unicode_normalization_physical_root_aliases(
    tmp_path: Path,
) -> None:
    actual = tmp_path / "\u00e9"
    actual.mkdir()
    alias = tmp_path / "e\u0301"
    _require_same_directory(
        actual,
        alias,
        "filesystem does not normalize Unicode names",
    )
    (actual / "payload").write_bytes(b"evidence")
    output = tmp_path / "snapshot.json"

    code = run_integrity_cli(
        _snapshot_argv((("actual", actual), ("alias", alias)), output)
    )

    assert code == 2
    assert not output.exists()


def test_snapshot_rejects_case_aliased_output_inside_a_root(
    tmp_path: Path,
) -> None:
    actual = tmp_path / "ProtectedRoot"
    actual.mkdir()
    alias = tmp_path / "protectedroot"
    _require_same_directory(actual, alias, "filesystem is case-sensitive")
    (actual / "payload").write_bytes(b"evidence")
    output = alias / "report.json"

    code = run_integrity_cli(_snapshot_argv((("root", actual),), output))

    assert code == 2
    assert not output.exists()


def test_retained_cache_rejects_case_aliased_output_inside_active_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder = tmp_path / "CacheHolder"
    active = active_cache(holder)
    alias_holder = tmp_path / "cacheholder"
    _require_same_directory(holder, alias_holder, "filesystem is case-sensitive")
    output = alias_holder / active.relative_to(holder) / "report.json"
    original_stage = output_api.open_staged_file
    stage_calls = 0

    def observe_stage(parent_descriptor: int) -> tuple[int, str]:
        nonlocal stage_calls
        stage_calls += 1
        return original_stage(parent_descriptor)

    monkeypatch.setattr(output_api, "open_staged_file", observe_stage)

    code = run_integrity_cli(_retained_argv(active, output))

    assert code == 2
    assert stage_calls == 0
    assert not output.exists()


def test_retained_cache_rejects_case_aliased_reserved_sibling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = active_cache(tmp_path)
    reserved = retained(active, "a", "recovery")
    reserved.mkdir()
    alias = reserved.with_name(reserved.name.upper())
    _require_same_directory(reserved, alias, "filesystem is case-sensitive")
    output = alias / "report.json"
    original_stage = output_api.open_staged_file
    stage_calls = 0

    def observe_stage(parent_descriptor: int) -> tuple[int, str]:
        nonlocal stage_calls
        stage_calls += 1
        return original_stage(parent_descriptor)

    monkeypatch.setattr(output_api, "open_staged_file", observe_stage)

    code = run_integrity_cli(_retained_argv(active, output))

    assert code == 2
    assert stage_calls == 0
    assert not output.exists()
