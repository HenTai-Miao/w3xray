"""Reversible and strict icon virtual-path planning tests."""

from __future__ import annotations

import pytest

from w3xtool.icon_path_evidence import plan_icon_path


def test_path_plan_preserves_original_normalized_and_attempt_order() -> None:
    # Given
    raw = '  "ReplaceableTextures/CommandButtons/BTNHero"  '

    # When
    plan = plan_icon_path(raw)

    # Then
    assert plan.original == raw
    assert plan.normalized == r"ReplaceableTextures\CommandButtons\BTNHero"
    assert plan.candidates == (
        r"ReplaceableTextures\CommandButtons\BTNHero",
        r"ReplaceableTextures\CommandButtons\BTNHero.blp",
        r"ReplaceableTextures\CommandButtons\BTNHero.tga",
        r"ReplaceableTextures\CommandButtons\BTNHero.dds",
    )


def test_path_plan_canonicalizes_only_known_namespace_segments() -> None:
    # Given / When
    plan = plan_icon_path(r"replaceabletextures\commandbuttons\CustomCase")

    # Then
    assert plan.normalized == r"ReplaceableTextures\CommandButtons\CustomCase"


@pytest.mark.parametrize(
    "raw",
    (
        r"C:\Icons\BTNHero.blp",
        r"..\Icons\BTNHero.blp",
        "Icons\\..\\BTNHero.blp",
        "Icons\\BTN\x00Hero.blp",
        "Icons\\BTNHero.mdx",
    ),
)
def test_path_plan_rejects_unsafe_or_unsupported_references(raw: str) -> None:
    # Given / When
    plan = plan_icon_path(raw)

    # Then
    assert plan.candidates == ()


def test_path_plan_keeps_supported_extension_first_without_duplicates() -> None:
    # Given / When
    plan = plan_icon_path(r"Icons\BTNHero.TGA")

    # Then
    assert plan.candidates == (
        r"Icons\BTNHero.TGA",
        r"Icons\BTNHero.blp",
        r"Icons\BTNHero.dds",
    )
