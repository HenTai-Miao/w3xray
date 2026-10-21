"""Focused strict-path authority for safe-output publication and races."""

from __future__ import annotations

from typing import Final


SAFE_OUTPUT_STRICT_PATHS: Final = tuple(
    """tests/test_integrity_output_naming_probe.py
tests/test_safe_output_cleanup_recovery.py
tests/test_safe_output_publication_atomicity.py
tests/test_safe_output_publication_cleanup_races.py
tests/test_safe_output_races.py
gametool/quality_safe_output_paths.py
gametool/safe_output.py
gametool/safe_output_anchored.py
gametool/safe_output_chunk_writer.py
gametool/safe_output_cleanup.py
gametool/safe_output_cleanup_recovery.py
gametool/safe_output_models.py
gametool/safe_output_path_publication.py
gametool/safe_output_publication.py
gametool/safe_output_publication_displaced.py
gametool/safe_output_publication_exchange_rollback.py
gametool/safe_output_publication_existing.py
gametool/safe_output_publication_existing_finish.py
gametool/safe_output_publication_identity.py
gametool/safe_output_publication_rollback.py
gametool/safe_output_publication_states.py
gametool/safe_output_staging.py""".splitlines()
)

__all__ = ("SAFE_OUTPUT_STRICT_PATHS",)
