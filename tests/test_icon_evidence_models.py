"""Icon evidence model invariant tests."""

from __future__ import annotations

from inspect import signature

import pytest

from w3xtool.icon_evidence_models import (
    IconArchiveLayer,
    IconArchiveLayerError,
    IconCandidateEvidence,
    IconCandidateKind,
    IconResolutionLayer,
)

_DIGEST = "a" * 64
_PATH = r"ReplaceableTextures\CommandButtons\BTNHero.blp"


class _Archive:
    path = "map.w3x"

    def has_file(self, name: str) -> bool:
        return False

    def read_file(self, name: str) -> bytes:
        raise FileNotFoundError(name)


def test_candidate_evidence_constructor_rejects_adopted_true() -> None:
    # Given
    constructor = signature(IconCandidateEvidence)

    # When / Then
    with pytest.raises(TypeError):
        constructor.bind(
            kind=IconCandidateKind.EXACT_OTHER_MAP_PATH,
            requested_map_sha256=_DIGEST,
            requested_path=_PATH,
            anonymous_map_sha256="",
            anonymous_block_index=None,
            candidate_map_sha256="b" * 64,
            candidate_path=_PATH,
            content_sha256="c" * 64,
            adopted=True,
        )


@pytest.mark.parametrize(
    "layer",
    (
        IconResolutionLayer.CLIENT,
        IconResolutionLayer.SAME_MAP_HISTORY,
        IconResolutionLayer.TRUSTED_CACHE,
    ),
)
def test_archive_layer_rejects_non_archive_resolution_layers(
    layer: IconResolutionLayer,
) -> None:
    # Given / When / Then
    with pytest.raises(IconArchiveLayerError, match=layer.value):
        IconArchiveLayer(layer, _Archive(), "invalid-source")
