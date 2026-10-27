"""Typed CLI tests for explicit historical description-cache migration."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.description_cache_migration_fixture import (
    write_mutated_inputs,
)
from gametool import description_cache_cli as cli
from gametool.trusted_description_cache import (
    load_trusted_description_cache,
)


@pytest.mark.skipif(
    os.name == "nt",
    reason="trusted-cache migration requires POSIX provenance primitives",
)
def test_description_cache_cli_returns_zero_for_structurally_valid_partial_migration(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: one structurally valid candidate lacks semantic proof.
    legacy_output, legacy_cache = write_mutated_inputs(tmp_path, "readable")
    output = tmp_path / "trusted"

    # When
    code = cli.run_description_cache_cli(
        (
            "migrate",
            "--legacy-output",
            str(legacy_output),
            "--legacy-cache",
            str(legacy_cache),
            "--output",
            str(output),
        )
    )

    # Then
    captured = capsys.readouterr()
    assert code == 0
    assert "接受 0" in captured.out
    assert "拒绝 1" in captured.out
    assert captured.err == ""
    assert not load_trusted_description_cache(output).cache.entries
