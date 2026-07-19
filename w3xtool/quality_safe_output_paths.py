"""Focused strict-path authority for safe-output publication and races."""

from __future__ import annotations

from typing import Final


SAFE_OUTPUT_STRICT_PATHS: Final = tuple(
    """tests/test_integrity_output_naming_probe.py
tests/test_safe_output_cleanup_recovery.py
tests/test_safe_output_publication_atomicity.py
tests/test_safe_output_publication_cleanup_races.py
tests/test_safe_output_races.py
w3xtool/quality_safe_output_paths.py
w3xtool/safe_output.py
w3xtool/safe_output_anchored.py
w3xtool/safe_output_chunk_writer.py
w3xtool/safe_output_cleanup.py
w3xtool/safe_output_cleanup_recovery.py
w3xtool/safe_output_models.py
w3xtool/safe_output_path_publication.py
w3xtool/safe_output_publication.py
w3xtool/safe_output_publication_displaced.py
w3xtool/safe_output_publication_exchange_rollback.py
w3xtool/safe_output_publication_existing.py
w3xtool/safe_output_publication_existing_finish.py
w3xtool/safe_output_publication_identity.py
w3xtool/safe_output_publication_rollback.py
w3xtool/safe_output_publication_states.py
w3xtool/safe_output_staging.py""".splitlines()
)

__all__ = ("SAFE_OUTPUT_STRICT_PATHS",)
