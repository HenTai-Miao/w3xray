"""Authority and race safety for superseded map retirement."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.batch_publication_fixture import empty_result, write_empty_publication
import w3xtool.batch_map_retirement as retirement
import w3xtool.batch_retirement_quarantine as quarantine
from w3xtool.batch_global_publication import publish_global_generation
from w3xtool.batch_global_models import GlobalGeneration
from w3xtool.batch_map_retirement import retire_superseded_map_publications
from w3xtool.batch_models import BATCH_SCHEMA_VERSION, BatchState, SourceFingerprint
from w3xtool.description_cache import format_description_cache_tsv
from w3xtool.description_cache_models import EMPTY_DESCRIPTION_CACHE


@dataclass(frozen=True, slots=True)
class _RetirementFixture:
    output: Path
    current: Path
    predecessor: Path
    state: BatchState


def test_retirement_preserves_predecessor_when_current_publication_is_invalid(
    tmp_path: Path,
) -> None:
    # Given: the selected current map directory was damaged after publication.
    fixture = _retirement_fixture(tmp_path)
    (fixture.current / "地图摘要.txt").write_text("tampered", encoding="utf-8")

    # When: superseded-publication retirement evaluates the authority.
    retired = retire_superseded_map_publications(
        str(fixture.output),
        fixture.state,
    )

    # Then: the last independently valid predecessor is retained.
    assert retired == ()
    assert fixture.predecessor.is_dir()


def test_retirement_restores_candidate_when_current_generation_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the authoritative pointer changes immediately after isolation.
    fixture = _retirement_fixture(tmp_path)
    initial = retirement.load_current_generation(fixture.output)
    assert initial is not None
    calls = 0

    def drifting_generation(_output_root: str | Path) -> GlobalGeneration | None:
        nonlocal calls
        calls += 1
        return initial if calls == 1 else None

    monkeypatch.setattr(retirement, "load_current_generation", drifting_generation)
    monkeypatch.setattr(quarantine, "load_current_generation", drifting_generation)

    # When: retirement reaches its final authority check.
    retired = retire_superseded_map_publications(
        str(fixture.output),
        fixture.state,
    )

    # Then: no evidence is deleted after the authority snapshot becomes stale.
    assert retired == ()
    assert fixture.predecessor.is_dir()
    assert calls >= 2


def test_retirement_never_deletes_through_the_original_candidate_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: another directory replaces the validated candidate at deletion time.
    fixture = _retirement_fixture(tmp_path)
    attacker = tmp_path / "attacker"
    attacker.mkdir()
    sentinel = attacker / "must-survive.txt"
    sentinel.write_text("external", encoding="utf-8")
    displaced = fixture.predecessor.with_name("displaced-valid-publication")
    real_rmtree = quarantine.shutil.rmtree

    def swap_original_path(
        path: str | Path,
        *,
        dir_fd: int | None = None,
    ) -> None:
        target = Path(path)
        if dir_fd is None and target == fixture.predecessor:
            fixture.predecessor.rename(displaced)
            attacker.rename(fixture.predecessor)
        real_rmtree(target, dir_fd=dir_fd)

    monkeypatch.setattr(quarantine.shutil, "rmtree", swap_original_path)

    # When: the predecessor is retired.
    _ = retire_superseded_map_publications(str(fixture.output), fixture.state)

    # Then: deletion was anchored to an isolated private name, not the old path.
    assert sentinel.is_file()
    assert not fixture.predecessor.exists()


def _retirement_fixture(tmp_path: Path) -> _RetirementFixture:
    output = tmp_path / "output"
    maps_root = output / "地图"
    maps_root.mkdir(parents=True)
    fingerprint = SourceFingerprint(
        "/maps/sample.w3x",
        3,
        4,
        "a" * 64,
    )
    predecessor_relative = "地图/001_old-name_aaaaaaaa"
    current_relative = "地图/001_current-name_aaaaaaaa"
    predecessor = maps_root / Path(predecessor_relative).name
    current = maps_root / Path(current_relative).name
    predecessor.mkdir()
    current.mkdir()
    _ = write_empty_publication(
        predecessor,
        empty_result(fingerprint, predecessor_relative),
        "1" * 32,
    )
    current_result = write_empty_publication(
        current,
        empty_result(fingerprint, current_relative),
        "2" * 32,
    )
    state = BatchState(BATCH_SCHEMA_VERSION, (current_result,))
    _ = publish_global_generation(
        output,
        state,
        format_description_cache_tsv(EMPTY_DESCRIPTION_CACHE),
        "",
    )
    return _RetirementFixture(output, current, predecessor, state)
