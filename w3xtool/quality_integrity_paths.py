"""Maintained quality paths for integrity-report and snapshot boundaries."""

from __future__ import annotations

from typing import Final


INTEGRITY_STRICT_PATHS: Final = tuple(
    """tests/test_integrity_cli.py
tests/test_integrity_cli_retained_cache.py
tests/test_integrity_output_identity_races.py
tests/test_integrity_output_safety.py
tests/test_integrity_physical_aliases.py
tests/test_integrity_platform_boundaries.py
tests/test_integrity_report_history.py
tests/test_integrity_report_history_preexchange_races.py
tests/test_integrity_report_history_races.py
tests/test_integrity_snapshot.py
tests/test_integrity_snapshot_races.py
tests/test_integrity_utf8_boundaries.py
w3xtool/integrity_cli.py
w3xtool/integrity_cli_options.py
w3xtool/integrity_output.py
w3xtool/integrity_output_naming.py
w3xtool/integrity_output_path.py
w3xtool/integrity_path_binding.py
w3xtool/integrity_report_history.py
w3xtool/integrity_report_history_directory.py
w3xtool/integrity_report_history_generation.py
w3xtool/integrity_report_publication.py
w3xtool/integrity_report_publication_errors.py
w3xtool/integrity_report_publication_models.py
w3xtool/integrity_report_replacement.py
w3xtool/integrity_snapshot.py
w3xtool/integrity_snapshot_binding.py
w3xtool/integrity_snapshot_file.py
w3xtool/integrity_snapshot_io.py
w3xtool/integrity_snapshot_models.py
w3xtool/integrity_snapshot_tree.py
w3xtool/integrity_utf8.py
w3xtool/quality_integrity_paths.py""".split()
)


__all__ = ("INTEGRITY_STRICT_PATHS",)
