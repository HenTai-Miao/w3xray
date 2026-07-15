"""Exact icon-field eligibility and selected-evidence contracts."""

from __future__ import annotations

import pytest

from w3xtool.icon_field_evidence import (
    IconFieldDecision,
    IconFieldDisposition,
    classify_icon_field,
)
from w3xtool.map_data import GameObject, GameObjectFieldEvidence
from w3xtool.object_candidates import (
    ObjectCandidate,
    ObjectFieldValue,
    ObjectSourceKind,
)
from w3xtool.object_pipeline import merge_object_candidates


@pytest.mark.parametrize(
    ("category", "key", "value_type", "expected"),
    (
        ("单位", "uico", "icon", IconFieldDisposition.ELIGIBLE),
        ("物品", "iico", "icon", IconFieldDisposition.ELIGIBLE),
        ("技能", "aart", "icon", IconFieldDisposition.ELIGIBLE),
        ("技能", "Art", "string", IconFieldDisposition.ELIGIBLE),
        ("科技", "gar1", "icon", IconFieldDisposition.ELIGIBLE),
        ("增益", "fart", "icon", IconFieldDisposition.ELIGIBLE),
        ("可破坏物", "bgsc", "real", IconFieldDisposition.FILTERED_NON_ICON),
        ("装饰物", "dfil", "model", IconFieldDisposition.FILTERED_NON_ICON),
        (
            "技能",
            "ResearchArt",
            "string",
            IconFieldDisposition.FILTERED_NON_ICON,
        ),
    ),
)
def test_icon_field_classification_is_exact(
    category: str,
    key: str,
    value_type: str,
    expected: IconFieldDisposition,
) -> None:
    # Given / When: one binary field is classified without label inference.
    decision = classify_icon_field(
        category,
        key,
        key,
        value_type,
        ObjectSourceKind.BINARY,
    )

    # Then: only the closed field/type contract determines its disposition.
    assert decision.disposition is expected


def test_icon_field_classification_normalizes_prefix_and_numeric_level() -> None:
    # Given / When: a known key carries both transport syntax and a level.
    decision = classify_icon_field(
        "技能",
        "binary:AArt:12",
        "untrusted icon-like label",
        "string",
        ObjectSourceKind.BINARY,
    )

    # Then: the evidence reports the exact canonical raw field identity.
    assert decision == IconFieldDecision(
        IconFieldDisposition.ELIGIBLE,
        "aart",
    )


@pytest.mark.parametrize(
    ("source_kind", "expected"),
    (
        (ObjectSourceKind.BASE, IconFieldDisposition.ELIGIBLE),
        (ObjectSourceKind.BINARY, IconFieldDisposition.NOT_AN_ICON_FIELD),
    ),
)
def test_base_icon_classification_requires_bundled_source(
    source_kind: ObjectSourceKind,
    expected: IconFieldDisposition,
) -> None:
    # Given / When: the exact base icon identity is classified by source kind.
    decision = classify_icon_field("单位", "base:图标", "图标", "", source_kind)

    # Then: map-provided fields cannot impersonate bundled base evidence.
    assert decision.disposition is expected


def test_icon_like_label_and_unknown_string_key_do_not_grant_eligibility() -> None:
    # Given / When: only the label suggests that an unknown string field is an icon.
    decision = classify_icon_field(
        "技能",
        "custom-art",
        "图标 - 普通",
        "string",
        ObjectSourceKind.BINARY,
    )

    # Then: presentation text cannot extend the closed eligibility model.
    assert decision.disposition is IconFieldDisposition.NOT_AN_ICON_FIELD


@pytest.mark.parametrize(
    ("category", "key", "value_type"),
    (
        ("可破坏物", "bgsc", "real"),
        ("装饰物", "dfil", "model"),
        ("技能", "aical", "icon"),
        ("科技", "gico", "icon"),
        ("技能", "ResearchArt", "string"),
    ),
)
def test_false_icon_fields_do_not_become_the_display_icon(
    category: str,
    key: str,
    value_type: str,
) -> None:
    # Given: a legacy false alias or explicitly non-icon metadata field.
    merged = _merged_field(category, key, "图标候选", value_type)

    # When / Then: materialization does not expose it as the object icon.
    assert merged.icon == ""


@pytest.mark.parametrize(
    "key",
    ("binary:aart:2", "field:aart:3"),
)
def test_prefixed_leveled_known_icon_field_becomes_the_display_icon(key: str) -> None:
    # Given: an exact ability icon key with a transport prefix and numeric level.
    merged = _merged_field("技能", key, "普通图标", "string")

    # When / Then: normalization preserves its exact icon eligibility.
    assert merged.icon == "candidate.blp"


def test_trusted_icon_metadata_can_qualify_an_unknown_key_in_a_known_category() -> None:
    # Given: trusted metadata identifies an otherwise unknown unit field as an icon.
    merged = _merged_field("单位", "custom-art", "普通图标", "icon")

    # When / Then: metadata eligibility selects the display icon.
    assert merged.icon == "candidate.blp"


@pytest.mark.parametrize(
    ("source_kind", "expected"),
    (
        (ObjectSourceKind.BASE, "candidate.blp"),
        (ObjectSourceKind.BINARY, ""),
    ),
)
def test_base_icon_identity_is_reserved_for_bundled_base_fields(
    source_kind: ObjectSourceKind,
    expected: str,
) -> None:
    # Given: the base icon identity arrives from a bundled or map source.
    merged = _merged_field(
        "单位",
        "base:图标",
        "图标",
        "",
        source_kind=source_kind,
    )

    # When / Then: only bundled base evidence may supply the display icon.
    assert merged.icon == expected


def test_materialization_retains_selected_icon_and_wts_location() -> None:
    # Given: one binary ability icon resolved through a WTS string.
    candidate = ObjectCandidate(
        category="技能",
        obj_id="A001",
        base_id="AHbz",
        is_custom=True,
        ext="w3a",
        fields=(
            ObjectFieldValue(
                key="aart",
                label="图标 - 普通",
                value=r"ReplaceableTextures\CommandButtons\BTNStorm.blp",
                source="war3map.w3a",
                source_kind=ObjectSourceKind.BINARY,
                value_source="war3map.wts#STRING 7",
                value_type="icon",
                raw_value="TRIGSTR_7",
            ),
        ),
        refs=(),
    )

    # When: the candidate is materialized into its public object.
    merged = merge_object_candidates((candidate,), {})[0]

    # Then: the selected icon retains its exact field and resolved-value source.
    assert merged.icon == r"ReplaceableTextures\CommandButtons\BTNStorm.blp"
    assert merged.icon_field_evidence == GameObjectFieldEvidence(
        key="aart",
        label="图标 - 普通",
        value=r"ReplaceableTextures\CommandButtons\BTNStorm.blp",
        source="war3map.w3a",
        source_priority=40,
        value_type="icon",
        raw_value="TRIGSTR_7",
        value_source="war3map.wts#STRING 7",
    )


def _merged_field(
    category: str,
    key: str,
    label: str,
    value_type: str,
    *,
    source_kind: ObjectSourceKind = ObjectSourceKind.BINARY,
) -> GameObject:
    candidate = ObjectCandidate(
        category=category,
        obj_id="A001",
        base_id="A001",
        is_custom=True,
        ext="base" if source_kind is ObjectSourceKind.BASE else "w3a",
        fields=(
            ObjectFieldValue(
                key=key,
                label=label,
                value="candidate.blp",
                source="fixture",
                source_kind=source_kind,
                value_type=value_type,
            ),
        ),
        refs=(),
    )
    return merge_object_candidates((candidate,), {})[0]
