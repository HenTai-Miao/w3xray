"""Exact-map historical icon resolution and object backfill tests."""

from __future__ import annotations

from dataclasses import replace

from w3xtool.extraction_ledger import build_extraction_ledger
from w3xtool.icon_evidence_builder import build_icon_evidence_index
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
    path: str = "logical-map.w3x"

    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = {name.casefold(): payload for name, payload in files.items()}

    def has_file(self, name: str) -> bool:
        return name.casefold() in self._files

    def read_file(self, name: str) -> bytes:
        return self._files[name.casefold()]


class _TrustedSource:
    def __init__(self, history: HistoricalIconEvidenceSet) -> None:
        self._history = history
        self.history_calls = 0

    def historical_icons_for(self, source_digest: str) -> HistoricalIconEvidenceSet:
        assert source_digest == _DIGEST
        self.history_calls += 1
        return self._history

    def has_exact_file(self, name: str) -> bool:
        _ = name
        return False

    def read_exact_file(self, name: str) -> bytes:
        raise FileNotFoundError(name)

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


def test_current_map_hit_does_not_load_unusable_history() -> None:
    source = _FailingHistorySource(
        HistoricalIconEvidenceSet(available=False, resources=())
    )
    archives = (
        IconArchiveLayer(
            IconResolutionLayer.CURRENT_MAP,
            _Archive({_PATH: _PAYLOAD}),
            "logical-map.w3x",
        ),
    )

    row = build_icon_evidence_index(_map_data(_PATH), archives, source).resolved[0]

    assert row.layer is IconResolutionLayer.CURRENT_MAP
    assert source.history_calls == 0


def test_history_is_loaded_once_for_multiple_references_in_one_build() -> None:
    md = _map_data(_PATH)
    md.objects["技能"].append(replace(md.objects["技能"][0], obj_id="A002"))
    source = _TrustedSource(HistoricalIconEvidenceSet(available=True, resources=()))

    index = build_icon_evidence_index(md, (), source)

    assert len(index.unresolved) == 2
    assert source.history_calls == 1


def test_same_map_history_replaces_old_object_labels_on_exact_path_match() -> None:
    historical = _historical_resource(_PATH, object_name="旧标签")
    source = _TrustedSource(
        HistoricalIconEvidenceSet(available=True, resources=(historical,))
    )

    index = build_icon_evidence_index(_map_data(_PATH), (), source)

    row = index.resolved[0]
    assert row.layer is IconResolutionLayer.SAME_MAP_HISTORY
    assert row.reference.object_name == "当前对象"
    assert row.attempts[-1].source_path == "可信图标缓存:war3.mpq"


def test_same_map_history_backfills_an_object_without_icon_evidence() -> None:
    historical = replace(
        _historical_resource(_PATH),
        objects=(IconObjectReference("技能", "A001", "历史标签"),),
    )
    source = _TrustedSource(
        HistoricalIconEvidenceSet(available=True, resources=(historical,))
    )
    md = _map_without_icon_evidence()

    index = build_icon_evidence_index(md, (), source)

    assert len(index.resolved) == 1
    row = index.resolved[0]
    assert row.layer is IconResolutionLayer.SAME_MAP_HISTORY
    assert row.reference.field_key == "history:object-icon"
    assert row.reference.requested_path == _PATH
    assert row.reference.object_name == "当前对象"
    assert md.objects["技能"][0].icon == _PATH


def test_same_map_history_does_not_guess_between_conflicting_object_paths() -> None:
    object_reference = IconObjectReference("技能", "A001", "历史标签")
    history = HistoricalIconEvidenceSet(
        available=True,
        resources=(
            replace(_historical_resource(_PATH), objects=(object_reference,)),
            replace(
                _historical_resource(r"Icons\Other.blp"),
                objects=(object_reference,),
            ),
        ),
    )
    source = _TrustedSource(history)
    md = _map_without_icon_evidence()

    index = build_icon_evidence_index(md, (), source)

    assert not index.resolved
    assert not index.unresolved
    assert md.objects["技能"][0].icon == ""


def test_same_map_history_does_not_override_an_explicit_empty_icon_field() -> None:
    historical = replace(
        _historical_resource(_PATH),
        objects=(IconObjectReference("技能", "A001", "历史标签"),),
    )
    source = _TrustedSource(
        HistoricalIconEvidenceSet(available=True, resources=(historical,))
    )
    md = _map_data("")

    index = build_icon_evidence_index(md, (), source)

    assert not index.resolved
    assert index.unresolved[0].reason is IconGapReason.INVALID_REFERENCE
    assert md.objects["技能"][0].icon == ""
    assert source.history_calls == 0


def test_same_map_history_must_match_current_requested_path() -> None:
    source = _TrustedSource(
        HistoricalIconEvidenceSet(
            available=True,
            resources=(_historical_resource(r"Other\BTNHero.blp"),),
        )
    )

    index = build_icon_evidence_index(_map_data(_PATH), (), source)

    assert not index.resolved
    assert index.unresolved[0].reason is IconGapReason.HISTORICAL_CLIENT_MISS


def _map_data(icon: str) -> MapData:
    evidence = GameObjectFieldEvidence(
        key="aart",
        label="图标 - 普通",
        value=icon,
        source="war3map.w3a",
        source_priority=40,
        value_type="icon",
    )
    obj = GameObject(
        category="技能",
        ext="w3a",
        obj_id="A001",
        base_id="AHbz",
        name="当前对象",
        is_custom=True,
        icon=icon,
        field_evidence=(evidence,),
        icon_field_evidence=evidence,
    )
    md = MapData("logical-map.w3x", "fixture", objects={"技能": [obj]})
    md.extraction_ledger = build_extraction_ledger(md.path, _DIGEST, ())
    return md


def _map_without_icon_evidence() -> MapData:
    obj = GameObject(
        category="技能",
        ext="txt",
        obj_id="A001",
        base_id="AHbz",
        name="当前对象",
        is_custom=False,
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
