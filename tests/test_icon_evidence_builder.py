"""Strict layered icon evidence-index tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from w3xtool.extraction_ledger import build_extraction_ledger
from w3xtool.game_data_source import DirectoryDataSource
from w3xtool.icon_evidence_builder import (
    IconEvidenceBuildError,
    build_icon_evidence_index,
)
from w3xtool.icon_evidence_index import merge_icon_evidence_indexes
from w3xtool.icon_evidence_models import (
    IconArchiveLayer,
    IconDiagnosticFlag,
    IconGapReason,
    IconResolutionLayer,
)
from w3xtool.icon_resources import IconObjectReference
from w3xtool.map_data import GameObject, GameObjectFieldEvidence, MapData

_DIGEST = "a" * 64
_PATH = r"ReplaceableTextures\CommandButtons\BTNHero.blp"
_PAYLOAD = b"BLP1map"


class _Archive:
    def __init__(self, path: str, files: dict[str, bytes]) -> None:
        self.path = path
        self._files = {name.casefold(): payload for name, payload in files.items()}

    def has_file(self, name: str) -> bool:
        return name.casefold() in self._files

    def read_file(self, name: str) -> bytes:
        return self._files[name.casefold()]


def test_resolution_uses_current_map_before_later_layers(tmp_path: Path) -> None:
    # Given
    md = _map_data(_PATH)
    archives = (
        IconArchiveLayer(
            IconResolutionLayer.CURRENT_MAP,
            _Archive("temporary-reader", {_PATH: _PAYLOAD}),
            "logical-map.w3x",
        ),
    )
    cached = tmp_path / _PATH.replace("\\", "/")
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"BLP1cache")
    client = DirectoryDataSource(str(tmp_path))

    # When
    index = build_icon_evidence_index(md, archives, client)

    # Then
    row = index.resolved[0]
    assert row.layer is IconResolutionLayer.CURRENT_MAP
    assert tuple(attempt.layer for attempt in row.attempts) == (
        IconResolutionLayer.CURRENT_MAP,
    )
    assert row.source_path == "logical-map.w3x"


def test_resolution_layer_order_is_independent_of_archive_input_order() -> None:
    # Given
    archives = (
        IconArchiveLayer(
            IconResolutionLayer.CAMPAIGN_ROOT,
            _Archive("campaign", {_PATH: b"BLP1campaign"}),
            "campaign.w3n",
        ),
        IconArchiveLayer(
            IconResolutionLayer.CURRENT_MAP,
            _Archive("current", {_PATH: _PAYLOAD}),
            "logical-map.w3x",
        ),
    )

    # When
    row = build_icon_evidence_index(_map_data(_PATH), archives, None).resolved[0]

    # Then
    assert row.layer is IconResolutionLayer.CURRENT_MAP
    assert row.payload == _PAYLOAD


def test_basename_candidate_never_resolves_from_a_real_client(tmp_path: Path) -> None:
    # Given
    icon = tmp_path / "deep" / "BTNHero.blp"
    icon.parent.mkdir()
    icon.write_bytes(_PAYLOAD)

    # When
    index = build_icon_evidence_index(
        _map_data(r"Custom\BTNHero.blp"),
        (),
        DirectoryDataSource(str(tmp_path)),
    )

    # Then
    assert not index.resolved
    assert index.unresolved[0].reference.normalized_path == r"Custom\BTNHero.blp"
    assert index.unresolved[0].reason is IconGapReason.NAMED_RESOURCE_MISSING


def test_selected_icon_reference_retains_field_wts_and_logical_map_identity() -> None:
    # Given / When
    row = build_icon_evidence_index(_map_data(_PATH), (), None).unresolved[0]

    # Then
    assert row.reference == IconObjectReference(
        "技能",
        "A001",
        "当前对象",
        "AHbz",
        "logical-map.w3x",
        _DIGEST,
        "logical-map.w3x",
        "aart",
        "图标 - 普通",
        "icon",
        "war3map.w3a",
        "war3map.wts#STRING 7",
        _PATH,
        _PATH,
    )


def test_invalid_reference_does_not_claim_that_client_data_was_needed() -> None:
    # Given / When: an author-defined empty icon cannot be looked up anywhere.
    row = build_icon_evidence_index(_map_data(""), (), None).unresolved[0]

    # Then: preserve the invalid field without inventing a client dependency.
    assert row.reason is IconGapReason.INVALID_REFERENCE
    assert IconDiagnosticFlag.CLIENT_NOT_PROVIDED not in row.diagnostics
    assert row.attempts == ()


def test_technology_art_list_is_split_into_lossless_level_references() -> None:
    # Given: optimized UpgradeData text stores every level icon in one Art cell.
    value = "Icons\\One.blp, Icons\\Two.blp,Icons\\Two.blp"
    evidence = GameObjectFieldEvidence(
        key="Art",
        label="图标",
        value=value,
        source="war3map UpgradeData.txt",
        source_priority=15,
        value_type="string",
    )
    obj = GameObject(
        category="科技",
        ext="txt",
        obj_id="R001",
        base_id="R001",
        name="测试升级",
        is_custom=True,
        icon="Icons\\One.blp",
        field_evidence=(evidence,),
        icon_field_evidence=evidence,
    )
    md = MapData("logical-map.w3x", "fixture", objects={"科技": [obj]})
    md.extraction_ledger = build_extraction_ledger(md.path, _DIGEST, ())

    # When: strict icon references are built.
    index = build_icon_evidence_index(md, (), None)

    # Then: all levels survive, including two levels sharing the same image.
    assert tuple(row.reference.requested_path for row in index.unresolved) == (
        r"Icons\One.blp",
        r"Icons\Two.blp",
        r"Icons\Two.blp",
    )
    assert tuple(row.reference.field_key for row in index.unresolved) == (
        "Art:1",
        "Art:2",
        "Art:3",
    )


def test_ability_art_list_is_split_into_lossless_level_references() -> None:
    # Given: ability string data stores multiple level icons in one Art cell.
    md = _ability_art_map_data(r"Icons\One.blp, Icons\Two.blp")

    # When: strict icon references are built.
    index = build_icon_evidence_index(md, (), None)

    # Then: every level retains its own field identity and requested path.
    assert tuple(row.reference.requested_path for row in index.unresolved) == (
        r"Icons\One.blp",
        r"Icons\Two.blp",
    )
    assert tuple(row.reference.field_key for row in index.unresolved) == (
        "Art:1",
        "Art:2",
    )


def test_empty_ability_art_levels_are_not_a_named_comma_path() -> None:
    # Given: two author-empty ability icon levels are serialized as one comma.
    md = _ability_art_map_data(",")

    # When: strict icon references are built.
    index = build_icon_evidence_index(md, (), None)

    # Then: preserve both empty levels without inventing an archive named comma.
    assert tuple(row.reference.field_key for row in index.unresolved) == (
        "Art:1",
        "Art:2",
    )
    assert tuple(row.reference.requested_path for row in index.unresolved) == ("", "")
    assert all(
        row.reason is IconGapReason.INVALID_REFERENCE for row in index.unresolved
    )
    assert all(row.reference.normalized_path == "" for row in index.unresolved)


def test_filtered_non_icon_field_is_not_an_unresolved_gap() -> None:
    # Given
    md = _map_data("", filtered=True)

    # When
    index = build_icon_evidence_index(md, (), None)

    # Then
    assert not index.unresolved
    assert index.filtered[0].reference.field_key == "bgsc"


def test_merged_indexes_are_stably_sorted_and_map_data_defaults_empty() -> None:
    # Given
    second = build_icon_evidence_index(_map_data(r"Icons\Z.blp", "B001"), (), None)
    first = build_icon_evidence_index(_map_data(r"Icons\A.blp", "A001"), (), None)

    # When
    merged = merge_icon_evidence_indexes((second, first))

    # Then
    assert tuple(row.reference.object_id for row in merged.unresolved) == (
        "A001",
        "B001",
    )
    assert MapData("empty.w3x", "empty").icon_evidence.unresolved == ()


@pytest.mark.parametrize("filtered", (False, True), ids=("eligible", "filtered"))
def test_build_rejects_evidence_rows_without_ledger_identity(filtered: bool) -> None:
    # Given
    md = _map_data("" if filtered else _PATH, filtered=filtered)
    md.extraction_ledger = None

    # When / Then
    with pytest.raises(IconEvidenceBuildError, match="logical-map.w3x"):
        build_icon_evidence_index(md, (), None)


def test_build_allows_an_empty_map_without_a_ledger() -> None:
    # Given
    md = MapData("empty.w3x", "empty")

    # When
    index = build_icon_evidence_index(md, (), None)

    # Then
    assert not index.resolved
    assert not index.unresolved
    assert not index.filtered


def _map_data(
    icon: str,
    object_id: str = "A001",
    *,
    filtered: bool = False,
) -> MapData:
    evidence = GameObjectFieldEvidence(
        key="bgsc" if filtered else "aart",
        label="图标 - 普通",
        value=r"Models\Tree.mdx" if filtered else icon,
        source="war3map.w3a",
        source_priority=40,
        value_type="real" if filtered else "icon",
        raw_value="TRIGSTR_7" if not filtered else None,
        value_source="war3map.wts#STRING 7" if not filtered else "",
    )
    obj = GameObject(
        category="技能",
        ext="w3a",
        obj_id=object_id,
        base_id="AHbz",
        name="当前对象",
        is_custom=True,
        icon="" if filtered else icon,
        field_evidence=(evidence,),
        icon_field_evidence=None if filtered else evidence,
    )
    md = MapData("logical-map.w3x", "fixture", objects={"技能": [obj]})
    md.extraction_ledger = build_extraction_ledger(md.path, _DIGEST, ())
    return md


def _ability_art_map_data(value: str) -> MapData:
    evidence = GameObjectFieldEvidence(
        key="Art",
        label="图标",
        value=value,
        source=r"units\campaignabilitystrings.txt",
        source_priority=15,
        value_type="string",
    )
    obj = GameObject(
        category="技能",
        ext="txt",
        obj_id="A001",
        base_id="A001",
        name="测试技能",
        is_custom=True,
        icon=value,
        field_evidence=(evidence,),
        icon_field_evidence=evidence,
    )
    md = MapData("logical-map.w3x", "fixture", objects={"技能": [obj]})
    md.extraction_ledger = build_extraction_ledger(md.path, _DIGEST, ())
    return md
