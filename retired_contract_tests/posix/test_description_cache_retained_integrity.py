"""Core retained-cache classification and report-codec contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Never

import pytest

from tests.retained_integrity_fixture import (
    active_cache,
    install_previous,
    make_fifo,
    retained,
    stage,
)
from tests.trusted_description_cache_fixture import published_cache
from gametool import description_cache_retained_integrity as snapshot_api
from gametool import trusted_description_cache as trusted_api
from gametool.trusted_description_cache import load_trusted_description_cache


def test_retained_integrity_separates_valid_partial_and_transient_objects(
    tmp_path: Path,
) -> None:
    inspect = getattr(snapshot_api, "inspect_retained_description_caches")
    format_report = getattr(snapshot_api, "format_description_cache_retention_report")
    parse_report = getattr(snapshot_api, "parse_description_cache_retention_report")
    active = published_cache(tmp_path / "active-source", raw="active")
    previous = install_previous(active, tmp_path)
    failed = retained(active, "2", "failed-stage")
    failed.mkdir()
    (failed / "partial.bin").write_bytes(b"partial")
    transient = stage(active, "3")
    transient.write_bytes(b"transient")
    unsafe = retained(active, "4", "recovery")
    unsafe.symlink_to(tmp_path / "outside", target_is_directory=True)

    report = inspect(active)

    by_role = {item.role.value: item for item in report.retained}
    assert by_role["previous"].validation.value == "valid-cache"
    assert by_role["previous"].kind.value == "directory"
    assert by_role["previous"].path == previous
    assert by_role["failed-stage"].size == len(b"partial")
    assert len(by_role["failed-stage"].sha256) == 64
    assert by_role["recovery"].kind.value == "symlink"
    assert by_role["recovery"].validation.value == "unsafe-object"
    assert report.transient[0].path == transient
    assert report.transient[0].kind.value == "regular-file"
    assert (
        load_trusted_description_cache(active)
        .cache.lookup("物品", "ratf", "扩展提示", None)[0]
        .raw_value
        == "active"
    )
    assert parse_report(format_report(report)) == report


@pytest.mark.parametrize("damage", ["missing", "extra", "nested"])
def test_previous_inventory_mismatch_is_invalid(tmp_path: Path, damage: str) -> None:
    inspect = getattr(snapshot_api, "inspect_retained_description_caches")
    active = active_cache(tmp_path)
    previous = install_previous(active, tmp_path)
    if damage == "missing":
        (previous / "来源清单.tsv").unlink()
    elif damage == "extra":
        (previous / "extra").write_bytes(b"x")
    else:
        nested = previous / "nested"
        nested.mkdir()
        (nested / "leaf").write_bytes(b"x")

    report = inspect(active)

    assert report.retained[0].validation.value == "invalid-previous"


@pytest.mark.parametrize("kind", ["regular", "symlink", "special"])
def test_previous_non_directory_is_unsafe(tmp_path: Path, kind: str) -> None:
    inspect = getattr(snapshot_api, "inspect_retained_description_caches")
    active = active_cache(tmp_path)
    previous = retained(active, "1", "previous")
    if kind == "regular":
        previous.write_bytes(b"x")
    elif kind == "symlink":
        previous.symlink_to(tmp_path / "outside")
    else:
        make_fifo(previous)

    report = inspect(active)

    assert report.retained[0].validation.value == "unsafe-object"
    assert report.retained[0].validation.value != "partial-evidence"


def test_previous_validation_never_calls_pathname_loaders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = active_cache(tmp_path)
    install_previous(active, tmp_path)

    def forbid_public_pathname_load(_root: Path) -> Never:
        raise AssertionError("retained validation used a pathname loader")

    def forbid_parent_pathname_load(
        _parent_descriptor: int,
        _root_name: str,
        _display_root: Path,
    ) -> Never:
        raise AssertionError("retained validation used a held-parent pathname loader")

    monkeypatch.setattr(
        trusted_api,
        "load_trusted_description_cache",
        forbid_public_pathname_load,
    )
    monkeypatch.setattr(
        trusted_api,
        "load_trusted_description_cache_from_parent",
        forbid_parent_pathname_load,
    )

    report = snapshot_api.inspect_retained_description_caches(active)

    assert report.retained[0].validation.value == "valid-cache"
