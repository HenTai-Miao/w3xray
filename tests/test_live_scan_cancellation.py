"""Cancellation is a delivery boundary even for tiny synthetic snapshots."""

from __future__ import annotations

import struct

import pytest

from gametool import live_handle_chain as live


def _candidate_reader(monkeypatch: pytest.MonkeyPatch) -> live.MemoryReader:
    blob = bytearray(0x1000)
    struct.pack_into("<I", blob, 0x100, 0x10000000)
    monkeypatch.setattr(
        live, "_looks_like_handle_manager", lambda *args, **kwargs: True
    )
    monkeypatch.setattr(live, "_selection_chain_valid", lambda *args: True)

    class System:
        valid = True

        def __init__(self, *args: object) -> None:
            pass

    monkeypatch.setattr(live, "HandleSystem", System)
    return live.MemoryReader([(0x20000000, bytes(blob))])


def test_already_cancelled_scan_never_reads_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _candidate_reader(monkeypatch)

    def unexpected(*args: object, **kwargs: object) -> bool:
        raise AssertionError("cancelled scan must not inspect memory")

    monkeypatch.setattr(live, "_looks_like_handle_manager", unexpected)
    assert (
        live.derive_offsets(
            reader, 0x20000000, 0x20001000, budget=live.ScanBudget(cancelled=True)
        )
        is None
    )


@pytest.mark.parametrize(
    "cancel_stage", ("candidates", "build-systems", "strict-verify", "loose-verify")
)
def test_stage_callback_cancellation_prevents_result(
    monkeypatch: pytest.MonkeyPatch, cancel_stage: str
) -> None:
    reader = _candidate_reader(monkeypatch)
    budget = live.ScanBudget()
    stages: list[str] = []
    if cancel_stage == "loose-verify":
        monkeypatch.setattr(live, "_selection_chain_valid", lambda *args: not args[-1])

    def on_stage(stage: live.DiscoveryStage) -> None:
        stages.append(stage.name)
        if stage.name == cancel_stage:
            budget.cancelled = True

    result = live.derive_offsets(
        reader, 0x20000000, 0x20001000, budget=budget, on_stage=on_stage
    )
    assert result is None
    assert stages[-1] == cancel_stage
    assert "complete" not in stages
    assert not budget.timed_out


@pytest.mark.parametrize("strict", (True, False))
def test_cancellation_during_successful_validation_prevents_delivery(
    monkeypatch: pytest.MonkeyPatch, strict: bool
) -> None:
    reader = _candidate_reader(monkeypatch)
    budget = live.ScanBudget()
    stages: list[str] = []

    def validate(*args: object) -> bool:
        if args[-1] != strict:
            return False
        budget.cancelled = True
        return True

    monkeypatch.setattr(live, "_selection_chain_valid", validate)
    result = live.derive_offsets(
        reader,
        0x20000000,
        0x20001000,
        budget=budget,
        on_stage=lambda stage: stages.append(stage.name),
    )
    assert result is None
    assert "complete" not in stages


def test_expired_budget_is_reported_before_small_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _candidate_reader(monkeypatch)
    monkeypatch.setattr(live.time, "monotonic", lambda: 100.0)
    budget = live.ScanBudget(deadline_s=1.0)
    monkeypatch.setattr(live.time, "monotonic", lambda: 102.0)
    assert live.derive_offsets(reader, 0x20000000, 0x20001000, budget=budget) is None
    assert budget.timed_out
