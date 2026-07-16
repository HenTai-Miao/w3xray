"""Fail-closed platform tests for anchored source reads."""

from __future__ import annotations

from pathlib import Path

import pytest

from w3xtool.anchored_source import (
    AnchoredSourceRoot,
    AnchoredSourceUnavailableError,
)


def test_anchored_source_has_no_pathname_fallback_when_platform_is_unsupported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    monkeypatch.setattr(
        "w3xtool.anchored_source._ANCHORED_OPEN_AVAILABLE",
        False,
    )

    # When / Then
    with pytest.raises(
        AnchoredSourceUnavailableError,
        match="component no-follow open is unavailable",
    ):
        _ = AnchoredSourceRoot.open(tmp_path)
