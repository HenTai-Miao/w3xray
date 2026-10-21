"""Immutable sorted path authority for the maintained quality gate."""

from __future__ import annotations

from typing import Final

from .quality_integrity_paths import INTEGRITY_STRICT_PATHS
from .quality_safe_output_paths import SAFE_OUTPUT_STRICT_PATHS
from .quality_test_paths import TEST_STRICT_PATHS
from .quality_tool_paths import TOOL_STRICT_PATHS


STRICT_PATHS: Final = tuple(
    sorted(
        (
            *TEST_STRICT_PATHS,
            *TOOL_STRICT_PATHS,
            *INTEGRITY_STRICT_PATHS,
            *SAFE_OUTPUT_STRICT_PATHS,
        )
    )
)


__all__ = ("STRICT_PATHS",)
