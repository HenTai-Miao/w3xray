"""Display-icon precedence contracts for primary and auxiliary fields."""

from __future__ import annotations

from w3xtool.object_candidates import (
    ObjectCandidate,
    ObjectFieldValue,
    ObjectSourceKind,
)
from w3xtool.object_pipeline import merge_object_candidates


def test_auxiliary_metadata_icon_does_not_evict_an_inherited_primary_icon() -> None:
    # Given: the map clears an auxiliary caster-upgrade icon while the unit still
    # inherits its ordinary game-interface icon.
    candidate = ObjectCandidate(
        category="单位",
        obj_id="u001",
        base_id="hfoo",
        is_custom=True,
        ext="w3u",
        fields=(
            ObjectFieldValue(
                key="ucua",
                label="魔法施放者升级技巧",
                value="",
                source="war3map.w3u",
                source_kind=ObjectSourceKind.BINARY,
                value_type="icon",
            ),
        ),
        refs=(),
    )

    # When: display fields are selected from both sources.
    merged = merge_object_candidates(
        (candidate,),
        {"hfoo": ("单位", (("图标", "ReplaceableTextures\\BTNFootman.blp"),))},
    )[0]

    # Then: an auxiliary empty field cannot blank the object's main thumbnail.
    assert merged.icon == r"ReplaceableTextures\BTNFootman.blp"
    assert merged.icon_field_evidence is not None
    assert merged.icon_field_evidence.key == "base:图标"


def test_primary_icon_key_beats_an_auxiliary_icon_from_the_same_source() -> None:
    # Given: one unit defines both its ordinary and score-screen icon fields.
    candidate = ObjectCandidate(
        category="单位",
        obj_id="u001",
        base_id="hfoo",
        is_custom=True,
        ext="w3u",
        fields=(
            ObjectFieldValue(
                "uico",
                "图标 - 游戏界面",
                "main.blp",
                "war3map.w3u",
                ObjectSourceKind.BINARY,
                value_type="icon",
            ),
            ObjectFieldValue(
                "ussi",
                "图标 - 计分屏",
                "score.blp",
                "war3map.w3u",
                ObjectSourceKind.BINARY,
                value_type="icon",
            ),
        ),
        refs=(),
    )

    # When / Then: the compatibility display icon is the ordinary object icon.
    merged = merge_object_candidates((candidate,), {})[0]
    assert merged.icon == "main.blp"
    assert merged.icon_field_evidence is not None
    assert merged.icon_field_evidence.key == "uico"
    assert tuple(field.key for field in merged.icon_fields_evidence) == (
        "uico",
        "ussi",
    )
