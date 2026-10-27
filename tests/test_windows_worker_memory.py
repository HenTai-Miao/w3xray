"""Windows worker budgets and truthful, failure-tolerant RSS telemetry."""

from __future__ import annotations

import ctypes
from dataclasses import replace
import json
from pathlib import Path

import pytest

from gametool import batch_execution, batch_runtime
from gametool.batch_execution import MapExecutionFailure, MapExecutionSuccess
from gametool.batch_execution_messages import (
    ChildFailure,
    decode_child_message,
    encode_child_failure,
)
from gametool import windows_worker_memory as memory


class _MemoryApi:
    def __init__(self, failure: str = "", *, close_failure: bool = False) -> None:
        self.failure = failure
        self.close_failure = close_failure
        self.calls: list[tuple[str, int]] = []
        self.limit = 0

    def _record(self, operation: str, value: int = 0) -> None:
        self.calls.append((operation, value))
        if self.failure == operation:
            raise OSError(f"{operation}: [WinError 5] Access is denied")

    def read_memory(self) -> memory.ProcessMemoryUsage:
        self._record("GetProcessMemoryInfo")
        return memory.ProcessMemoryUsage(8192, 4096, 16384)

    def create_job(self) -> int:
        self._record("CreateJobObjectW")
        return 123

    def set_memory_limit(self, job: int, limit: int) -> None:
        assert job == 123
        self._record("SetInformationJobObject", limit)
        self.limit = limit

    def query_memory_limit(self, job: int) -> int:
        assert job == 123
        self._record("QueryInformationJobObject")
        return self.limit

    def assign_current_process(self, job: int) -> None:
        assert job == 123
        self._record("AssignProcessToJobObject")

    def verify_current_process(self, job: int) -> None:
        assert job == 123
        self._record("IsProcessInJob")

    def close_job(self, job: int) -> None:
        assert job == 123
        self._record("CloseHandle")
        if self.close_failure:
            raise OSError("CloseHandle: [WinError 6] The handle is invalid")


def test_absent_budget_does_not_load_windows_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_api() -> None:
        raise AssertionError("the default must not create a memory Job")

    monkeypatch.setattr(memory, "_native_api", unexpected_api)
    assert memory.apply_worker_memory_limit(None) is None


def test_budget_is_verified_and_owned_handle_is_closed_once() -> None:
    api = _MemoryApi()
    guard = memory.apply_worker_memory_limit(65536, api=api)
    assert guard is not None
    assert api.calls == [
        ("GetProcessMemoryInfo", 0),
        ("CreateJobObjectW", 0),
        ("SetInformationJobObject", 65536),
        ("QueryInformationJobObject", 0),
        ("AssignProcessToJobObject", 0),
        ("IsProcessInJob", 0),
    ]
    guard.close()
    guard.close()
    assert api.calls.count(("CloseHandle", 0)) == 1


@pytest.mark.parametrize(
    "operation",
    [
        "GetProcessMemoryInfo",
        "CreateJobObjectW",
        "SetInformationJobObject",
        "QueryInformationJobObject",
        "AssignProcessToJobObject",
        "IsProcessInJob",
    ],
)
def test_failed_setup_retains_api_error_and_closes_created_job(operation: str) -> None:
    api = _MemoryApi(operation)
    with pytest.raises(OSError, match=f"{operation}.*WinError 5"):
        memory.apply_worker_memory_limit(65536, api=api)
    closed = ("CloseHandle", 0) in api.calls
    assert closed is (operation not in {"GetProcessMemoryInfo", "CreateJobObjectW"})


def test_setup_cleanup_error_does_not_replace_original_assignment_error() -> None:
    api = _MemoryApi("AssignProcessToJobObject", close_failure=True)
    with pytest.raises(OSError) as caught:
        memory.apply_worker_memory_limit(65536, api=api)
    assert "AssignProcessToJobObject" in str(caught.value)
    assert "WinError 5" in str(caught.value)
    assert "CloseHandle" in str(caught.value)
    assert "WinError 6" in str(caught.value)


@pytest.mark.parametrize(
    "limit", [True, 0, -1, 1 << (8 * ctypes.sizeof(ctypes.c_size_t))]
)
def test_invalid_native_budget_is_rejected_before_any_api_call(limit: int) -> None:
    api = _MemoryApi()
    with pytest.raises(ValueError):
        memory.apply_worker_memory_limit(limit, api=api)
    assert api.calls == []


def test_budget_below_existing_commit_is_not_claimed_as_enforced() -> None:
    api = _MemoryApi()
    with pytest.raises(ValueError, match="committed"):
        memory.apply_worker_memory_limit(8192, api=api)
    assert api.calls == [("GetProcessMemoryInfo", 0)]


def test_mismatched_limit_readback_fails_before_assigning_worker() -> None:
    class MismatchedApi(_MemoryApi):
        def query_memory_limit(self, job: int) -> int:
            return super().query_memory_limit(job) + 4096

    api = MismatchedApi()
    with pytest.raises(OSError, match="readback"):
        memory.apply_worker_memory_limit(65536, api=api)
    assert ("AssignProcessToJobObject", 0) not in api.calls
    assert api.calls[-1] == ("CloseHandle", 0)


def test_native_rss_is_bytes_without_posix_unit_conversion() -> None:
    reading = memory.read_peak_rss(api=_MemoryApi())
    assert reading.peak_rss_bytes == 8192
    assert reading.diagnostics == ()


def test_rss_failure_is_unknown_with_complete_native_error() -> None:
    reading = memory.read_peak_rss(api=_MemoryApi("GetProcessMemoryInfo"))
    assert reading.peak_rss_bytes is None
    assert len(reading.diagnostics) == 1
    assert "GetProcessMemoryInfo" in reading.diagnostics[0]
    assert "WinError 5" in reading.diagnostics[0]


@pytest.mark.parametrize("failure", [MemoryError, AttributeError, OverflowError])
def test_telemetry_allocation_and_api_failures_remain_unknown(
    failure: type[Exception],
) -> None:
    class FailedApi(_MemoryApi):
        def read_memory(self) -> memory.ProcessMemoryUsage:
            raise failure("fixture telemetry failure")

    reading = memory.read_peak_rss(api=FailedApi())
    assert reading.peak_rss_bytes is None
    assert failure.__name__ in reading.diagnostics[0]
    assert "fixture telemetry failure" in reading.diagnostics[0]


@pytest.mark.parametrize("peak", [0, (1 << (8 * ctypes.sizeof(ctypes.c_size_t))) - 1])
def test_invalid_native_rss_is_never_presented_as_a_measurement(peak: int) -> None:
    class InvalidApi(_MemoryApi):
        def read_memory(self) -> memory.ProcessMemoryUsage:
            return memory.ProcessMemoryUsage(peak, 4096, 16384)

    reading = memory.read_peak_rss(api=InvalidApi())
    assert reading.peak_rss_bytes is None
    assert "invalid peak RSS" in reading.diagnostics[0]


def test_non_windows_requests_are_explicitly_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(memory.sys, "platform", "linux")
    with pytest.raises(OSError, match="Windows"):
        memory.apply_worker_memory_limit(65536)
    reading = memory.read_peak_rss()
    assert reading.peak_rss_bytes is None
    assert "Windows" in reading.diagnostics[0]


def test_unknown_peak_and_diagnostics_round_trip_failure_wire() -> None:
    diagnostics = ("GetProcessMemoryInfo: [WinError 5] denied\t\r\n完整",)
    outcome = decode_child_message(
        encode_child_failure("map_memory_error", "fixture", None, diagnostics)
    )
    assert isinstance(outcome, ChildFailure)
    assert outcome.peak_rss_bytes is None
    assert outcome.resource_diagnostics == diagnostics


def test_old_failure_wire_zero_is_unknown() -> None:
    payload = b"F" + bytes(8) + (3).to_bytes(4, "little") + b"old" + b"detail"
    outcome = decode_child_message(payload)
    assert isinstance(outcome, ChildFailure)
    assert outcome.peak_rss_bytes is None
    assert outcome.detail == "detail"


def test_telemetry_error_never_changes_successful_worker_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool.batch_configuration import BatchOptions
    from gametool.batch_execution_request import build_execution_request
    from gametool.batch_models import SourceFingerprint
    from gametool.load_context import MapLoadContext

    diagnostics = ("GetProcessMemoryInfo: [WinError 5] fixture",)
    monkeypatch.setattr(
        batch_execution,
        "read_peak_rss",
        lambda: memory.PeakRssReading(None, diagnostics),
    )

    class Sender:
        payload = b""
        closed = False

        def send_bytes(self, buffer: bytes) -> None:
            self.payload = buffer

        def close(self) -> None:
            self.closed = True

    sender = Sender()
    request = build_execution_request(
        1,
        SourceFingerprint(str(tmp_path / "sample.w3x"), 3, 4, "a" * 64),
        BatchOptions(str(tmp_path), str(tmp_path / "output")),
        MapLoadContext(),
    )
    batch_execution._child_entry(request, sender, _successful_worker, None)
    outcome = batch_execution._execution_outcome(sender.payload)
    assert isinstance(outcome, MapExecutionSuccess)
    assert outcome.peak_rss_bytes is None
    assert outcome.result.resource_diagnostics == diagnostics
    assert sender.closed


def test_native_limit_setup_failure_stops_worker_with_typed_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied(_limit: int | None) -> None:
        raise OSError("AssignProcessToJobObject: [WinError 5] denied")

    monkeypatch.setattr(batch_execution, "apply_worker_memory_limit", denied)
    result = batch_execution._apply_memory_limit(65536)
    assert isinstance(result, MapExecutionFailure)
    assert result.code == "memory_limit_setup_failed"
    assert "WinError 5" in result.detail


def test_legacy_zero_progress_is_displayed_as_unknown() -> None:
    progress = batch_runtime.build_batch_progress(
        completed=1,
        total=1,
        source_path="fixture.w3x",
        action=batch_runtime.BatchAction.PROCESSED,
        started_ns=0,
        now_ns=1,
        peak_rss_bytes=0,
        published_bytes=1,
        diagnostic_code="processed",
    )
    assert progress.peak_rss_bytes is None


def test_state_legacy_bytes_and_nullable_peak_are_both_supported() -> None:
    from tests.test_batch_state_reports import _map_result
    from gametool.batch_models import BATCH_SCHEMA_VERSION, BatchState
    from gametool.batch_state_io import format_batch_state_json, parse_batch_state_json

    legacy = BatchState(
        BATCH_SCHEMA_VERSION, (replace(_map_result(), peak_rss_bytes=0),)
    )
    legacy_text = format_batch_state_json(legacy)
    assert "resource_diagnostics" not in json.loads(legacy_text)["results"][0]
    assert format_batch_state_json(parse_batch_state_json(legacy_text)) == legacy_text
    result = replace(
        _map_result(),
        peak_rss_bytes=None,
        resource_diagnostics=("GetProcessMemoryInfo: [WinError 5] denied",),
    )
    state = BatchState(BATCH_SCHEMA_VERSION, (result,))
    payload = format_batch_state_json(state)
    assert json.loads(payload)["results"][0]["peak_rss_bytes"] is None
    assert parse_batch_state_json(payload) == state


@pytest.mark.parametrize("value", [None, 0, "diagnostic", [1], [None], [True]])
def test_state_resource_diagnostics_are_strict(value: object) -> None:
    from tests.test_batch_state_reports import _map_result
    from gametool.batch_models import (
        BATCH_SCHEMA_VERSION,
        BatchState,
        BatchStateFormatError,
    )
    from gametool.batch_state_io import format_batch_state_json, parse_batch_state_json

    payload = json.loads(
        format_batch_state_json(BatchState(BATCH_SCHEMA_VERSION, (_map_result(),)))
    )
    payload["results"][0]["resource_diagnostics"] = value
    with pytest.raises(BatchStateFormatError):
        parse_batch_state_json(json.dumps(payload))


def test_successful_worker_retains_owned_job_cleanup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool.batch_configuration import BatchOptions
    from gametool.batch_execution_request import build_execution_request
    from gametool.batch_models import SourceFingerprint
    from gametool.load_context import MapLoadContext

    api = _MemoryApi(close_failure=True)
    guard = memory.apply_worker_memory_limit(65536, api=api)
    monkeypatch.setattr(batch_execution, "_apply_memory_limit", lambda _limit: guard)

    class Sender:
        payload = b""

        def send_bytes(self, buffer: bytes) -> None:
            self.payload = buffer

        def close(self) -> None:
            pass

    sender = Sender()
    request = build_execution_request(
        1,
        SourceFingerprint(str(tmp_path / "sample.w3x"), 3, 4, "a" * 64),
        BatchOptions(str(tmp_path), str(tmp_path / "output")),
        MapLoadContext(),
    )
    batch_execution._child_entry(request, sender, _successful_worker, 65536)
    outcome = batch_execution._execution_outcome(sender.payload)
    assert isinstance(outcome, MapExecutionSuccess)
    assert "CloseHandle" in outcome.result.resource_diagnostics[0]
    assert "WinError 6" in outcome.result.resource_diagnostics[0]


def test_explicit_api_budget_forces_isolation_even_without_isolate_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool import batch_map_attempt
    from gametool.batch_configuration import BatchOptions
    from gametool.batch_models import SourceFingerprint
    from gametool.batch_resume import PreviousBatchState
    from gametool.load_context import MapLoadContext

    fingerprint = SourceFingerprint(str(tmp_path / "sample.w3x"), 3, 4, "a" * 64)
    options = BatchOptions(
        str(tmp_path), str(tmp_path / "output"), max_memory_bytes=65536
    )
    calls: list[int | None] = []

    def isolated(*_args: object, **kwargs: object) -> MapExecutionSuccess:
        budget = kwargs["max_memory_bytes"]
        assert budget is None or isinstance(budget, int)
        calls.append(budget)
        return MapExecutionSuccess(
            _successful_worker(1, fingerprint, options, MapLoadContext()), 8192
        )

    def unexpected_direct(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("an explicit budget must not run in the parent process")

    monkeypatch.setattr(
        batch_map_attempt, "fingerprint_dependencies", lambda *_a: "b" * 64
    )
    monkeypatch.setattr(batch_map_attempt, "execute_map_isolated", isolated)
    monkeypatch.setattr(batch_map_attempt, "_execute_direct", unexpected_direct)
    attempt = batch_map_attempt.attempt_map(
        1,
        fingerprint,
        options,
        MapLoadContext(),
        PreviousBatchState(None, ()),
        "",
        None,
        _successful_worker,
    )
    assert calls == [65536]
    assert attempt.code == "processed"


def test_rss_diagnostic_reaches_progress_json_and_cli_without_false_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from gametool.batch_cli import _print_batch_progress

    diagnostics = ("peak_rss_unavailable: [WinError 5] denied\t\r\nfull",)
    progress = batch_runtime.build_batch_progress(
        completed=1,
        total=1,
        source_path="fixture.w3x",
        action=batch_runtime.BatchAction.PROCESSED,
        started_ns=0,
        now_ns=1,
        peak_rss_bytes=None,
        published_bytes=1,
        diagnostic_code="processed",
        resource_diagnostics=diagnostics,
    )
    _print_batch_progress(progress)
    captured = capsys.readouterr()
    assert "RSS 未知" in captured.out
    assert "RSS 0.00" not in captured.out
    assert "WinError 5" in captured.err
    diagnostic = batch_runtime.BatchDiagnostic(
        1,
        "processed",
        "",
        "fixture.w3x",
        batch_runtime.BatchAction.PROCESSED,
        1,
        1,
        1,
        None,
        1,
        diagnostics,
    )
    raw = json.loads(batch_runtime.format_batch_diagnostics_jsonl((diagnostic,)))
    assert raw["peak_rss_bytes"] is None
    assert raw["resource_diagnostics"] == list(diagnostics)
    assert raw["action"] == "processed"


@pytest.mark.parametrize("budget", [None, 128 * 1024 * 1024, 1])
def test_real_spawn_child_enforces_budget_and_reports_native_rss(
    tmp_path: Path,
    budget: int | None,
) -> None:
    import multiprocessing
    from dataclasses import asdict
    from gametool.batch_configuration import BatchOptions
    from gametool.batch_models import SourceFingerprint
    from gametool.load_context import MapLoadContext

    before = frozenset(p.pid for p in multiprocessing.active_children())
    outcome = batch_execution.execute_map_isolated(
        1,
        SourceFingerprint(str(tmp_path / "sample.w3x"), 3, 4, "a" * 64),
        BatchOptions(str(tmp_path), str(tmp_path / "output")),
        MapLoadContext(),
        worker=_allocating_worker,
        timeout_seconds=15,
        max_memory_bytes=budget,
        cancellation=None,
    )
    assert outcome.peak_rss_bytes is not None and outcome.peak_rss_bytes > 0
    if budget is None:
        assert isinstance(outcome, MapExecutionSuccess)
        assert outcome.peak_rss_bytes >= 192 * 1024 * 1024
    else:
        assert isinstance(outcome, MapExecutionFailure)
        assert outcome.code == (
            "memory_limit_setup_failed" if budget == 1 else "map_memory_error"
        )
        assert outcome.child_alive is False
        assert str(budget) in outcome.detail
    assert frozenset(p.pid for p in multiprocessing.active_children()) == before
    evidence = tmp_path / "native-worker-memory.json"
    evidence.write_text(
        json.dumps(
            {"budget": budget, "outcome": asdict(outcome)}, default=str, indent=2
        ),
        encoding="utf-8",
    )


def _successful_worker(index, fingerprint, options, context, **_kwargs):
    from tests.test_batch_execution import _success_worker

    return _success_worker(index, fingerprint, options, context)


def _allocating_worker(index, fingerprint, options, context, **_kwargs):

    allocation = bytearray(192 * 1024 * 1024)
    allocation[0] = 1
    allocation[-1] = 2
    assert allocation[0] + allocation[-1] == 3
    return _successful_worker(index, fingerprint, options, context)
