"""Strict layered icon evidence-index tests."""

from __future__ import annotations

from dataclasses import replace
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
    IconGapReason,
    IconResolutionLayer,
)
from w3xtool.icon_resources import (
    HistoricalIconEvidenceSet,
    IconObjectReference,
    NamedIconResource,
)
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


class _TrustedSource:
    def __init__(
        self,
        history: HistoricalIconEvidenceSet,
        files: dict[str, bytes] | None = None,
    ) -> None:
        self._history = history
        self.history_calls = 0
        self._files = {
            name.casefold(): payload for name, payload in (files or {}).items()
        }

    def historical_icons_for(self, source_digest: str) -> HistoricalIconEvidenceSet:
        assert source_digest == _DIGEST
        self.history_calls += 1
        return self._history

    def has_exact_file(self, name: str) -> bool:
        return name.casefold() in self._files

    def read_exact_file(self, name: str) -> bytes:
        return self._files[name.casefold()]

    def has_file(self, name: str) -> bool:
        return self.has_exact_file(name)

    def read_file(self, name: str) -> bytes:
        return self.read_exact_file(name)

    def close(self) -> None:
        """The fake owns no resources."""


class _FailingHistorySource(_TrustedSource):
    def historical_icons_for(self, source_digest: str) -> HistoricalIconEvidenceSet:
        assert source_digest == _DIGEST
        self.history_calls += 1
        raise AssertionError("history must not load before an archive hit")


def test_resolution_uses_current_map_before_later_layers() -> None:
    # Given
    md = _map_data(_PATH)
    archives = (
        IconArchiveLayer(
            IconResolutionLayer.CURRENT_MAP,
            _Archive("temporary-reader", {_PATH: _PAYLOAD}),
            "logical-map.w3x",
        ),
    )
    trusted = _TrustedSource(
        HistoricalIconEvidenceSet(available=True, resources=()),
        {_PATH: b"BLP1cache"},
    )

    # When
    index = build_icon_evidence_index(md, archives, trusted)

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


def test_current_map_hit_does_not_load_unusable_history() -> None:
    # Given
    source = _FailingHistorySource(
        HistoricalIconEvidenceSet(available=False, resources=())
    )
    archives = (
        IconArchiveLayer(
            IconResolutionLayer.CURRENT_MAP,
            _Archive("current", {_PATH: _PAYLOAD}),
            "logical-map.w3x",
        ),
    )

    # When
    row = build_icon_evidence_index(_map_data(_PATH), archives, source).resolved[0]

    # Then
    assert row.layer is IconResolutionLayer.CURRENT_MAP
    assert source.history_calls == 0


def test_history_is_loaded_once_for_multiple_references_in_one_build() -> None:
    # Given
    md = _map_data(_PATH)
    md.objects["技能"].append(replace(md.objects["技能"][0], obj_id="A002"))
    source = _TrustedSource(HistoricalIconEvidenceSet(available=True, resources=()))

    # When
    index = build_icon_evidence_index(md, (), source)

    # Then
    assert len(index.unresolved) == 2
    assert source.history_calls == 1


def test_same_map_history_replaces_old_object_labels_on_exact_path_match() -> None:
    # Given
    historical = _historical_resource(_PATH, object_name="旧标签")
    source = _TrustedSource(
        HistoricalIconEvidenceSet(available=True, resources=(historical,))
    )

    # When
    index = build_icon_evidence_index(_map_data(_PATH), (), source)

    # Then
    row = index.resolved[0]
    assert row.layer is IconResolutionLayer.SAME_MAP_HISTORY
    assert row.reference.object_name == "当前对象"
    assert row.attempts[-1].source_path == "可信图标缓存:war3.mpq"


def test_same_map_history_must_match_current_requested_path() -> None:
    # Given
    source = _TrustedSource(
        HistoricalIconEvidenceSet(
            available=True,
            resources=(_historical_resource(r"Other\BTNHero.blp"),),
        )
    )

    # When
    index = build_icon_evidence_index(_map_data(_PATH), (), source)

    # Then
    assert not index.resolved
    assert index.unresolved[0].reason is IconGapReason.HISTORICAL_CLIENT_MISS


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


def _historical_resource(
    path: str,
    *,
    object_name: str = "历史对象",
) -> NamedIconResource:
    return NamedIconResource(
        requested_path=path,
        normalized_path=path,
        resolved_path=path,
        source_path="可信图标缓存:war3.mpq",
        payload=b"BLP1history",
        sha256="f" * 64,
        objects=(IconObjectReference("技能", "OLD1", object_name),),
    )
