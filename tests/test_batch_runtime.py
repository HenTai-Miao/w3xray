"""Disk, progress, RSS, ETA, and structured batch diagnostic contracts."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

import w3xtool.batch_runtime as batch_runtime
from w3xtool.batch_runtime import (
    BatchAction,
    BatchDiagnostic,
    DiskPreflightInsufficient,
    DiskPreflightReady,
    build_batch_progress,
    check_disk_preflight,
    format_batch_diagnostics_jsonl,
)


def test_disk_preflight_rejects_free_space_below_reserve_and_expansion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    monkeypatch.setattr(
        batch_runtime.shutil,
        "disk_usage",
        lambda _path: shutil._ntuple_diskusage(10_000, 9_000, 1_000),
    )

    # When
    result = check_disk_preflight(
        str(tmp_path / "new-output"),
        source_size=400,
        minimum_free_bytes=900,
    )

    # Then
    assert isinstance(result, DiskPreflightInsufficient)
    assert result.available_bytes == 1_000
    assert result.required_bytes > result.available_bytes


def test_disk_preflight_accepts_space_above_exact_requirement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    monkeypatch.setattr(
        batch_runtime.shutil,
        "disk_usage",
        lambda _path: shutil._ntuple_diskusage(10**10, 1, 10**10 - 1),
    )

    # When
    result = check_disk_preflight(
        str(tmp_path),
        source_size=400,
        minimum_free_bytes=900,
    )

    # Then
    assert isinstance(result, DiskPreflightReady)
    assert result.available_bytes >= result.required_bytes


def test_progress_uses_deterministic_nonnegative_eta() -> None:
    # When
    progress = build_batch_progress(
        completed=2,
        total=5,
        source_path="/maps/a.w3x",
        action=BatchAction.PROCESSED,
        started_ns=1_000_000_000,
        now_ns=5_000_000_000,
        peak_rss_bytes=123,
        published_bytes=456,
        diagnostic_code="processed",
    )

    # Then
    assert progress.elapsed_ms == 4_000
    assert progress.eta_seconds == 6.0
    assert progress.eta_seconds >= 0


def test_progress_has_no_eta_before_first_completion() -> None:
    # When
    progress = build_batch_progress(
        completed=0,
        total=3,
        source_path="",
        action=BatchAction.STARTING,
        started_ns=5,
        now_ns=1,
        peak_rss_bytes=0,
        published_bytes=0,
        diagnostic_code="started",
    )

    # Then
    assert progress.elapsed_ms == 0
    assert progress.eta_seconds is None


def test_diagnostics_are_lossless_json_lines() -> None:
    # Given
    diagnostic = BatchDiagnostic(
        sequence=1,
        code="artifact_hash_mismatch",
        detail="hash\tmismatch\r\n",
        source_path="/maps/a.w3x",
        action=BatchAction.FAILED,
        completed=1,
        total=2,
        elapsed_ms=10,
        peak_rss_bytes=20,
        published_bytes=30,
    )

    # When
    text = format_batch_diagnostics_jsonl((diagnostic,))

    # Then
    assert text.endswith("\n")
    assert json.loads(text) == {
        "action": "failed",
        "code": "artifact_hash_mismatch",
        "completed": 1,
        "detail": "hash\tmismatch\r\n",
        "elapsed_ms": 10,
        "peak_rss_bytes": 20,
        "published_bytes": 30,
        "sequence": 1,
        "source_path": "/maps/a.w3x",
        "total": 2,
    }
