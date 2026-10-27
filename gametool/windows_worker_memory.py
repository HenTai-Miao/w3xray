"""Native Windows memory budgets for an isolated worker, plus RSS telemetry.

Job budgets limit committed memory; PeakWorkingSetSize measures resident bytes.
Only the spawned worker calls apply_worker_memory_limit. No parent job is opened,
changed, terminated, or allowed to break away from its existing constraints.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import os
import sys
from typing import Protocol


_PROCESS_MEMORY = 0x00000100
_EXTENDED_LIMIT_INFORMATION = 9
_SIZE_T_MAX = (1 << (8 * ctypes.sizeof(ctypes.c_size_t))) - 1


class _BasicJobLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _ExtendedJobLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicJobLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("PageFaultCount", ctypes.c_uint32),
        *[
            (name, ctypes.c_size_t)
            for name in (
                "PeakWorkingSetSize",
                "WorkingSetSize",
                "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage",
                "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage",
                "PagefileUsage",
                "PeakPagefileUsage",
                "PrivateUsage",
            )
        ],
    ]


@dataclass(frozen=True, slots=True)
class ProcessMemoryUsage:
    peak_rss_bytes: int
    working_set_bytes: int
    committed_bytes: int


@dataclass(frozen=True, slots=True)
class PeakRssReading:
    peak_rss_bytes: int | None
    diagnostics: tuple[str, ...] = ()


class _MemoryApi(Protocol):
    def read_memory(self) -> ProcessMemoryUsage: ...

    def create_job(self) -> int: ...

    def set_memory_limit(self, job: int, limit: int) -> None: ...

    def query_memory_limit(self, job: int) -> int: ...

    def assign_current_process(self, job: int) -> None: ...

    def verify_current_process(self, job: int) -> None: ...

    def close_job(self, job: int) -> None: ...


class _WindowsMemoryApi:
    def __init__(self) -> None:
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel = self._kernel
        kernel.GetCurrentProcess.argtypes = []
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        kernel.CreateJobObjectW.restype = ctypes.c_void_p
        kernel.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        kernel.SetInformationJobObject.restype = ctypes.c_int
        kernel.QueryInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        kernel.QueryInformationJobObject.restype = ctypes.c_int
        kernel.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel.AssignProcessToJobObject.restype = ctypes.c_int
        kernel.IsProcessInJob.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int),
        ]
        kernel.IsProcessInJob.restype = ctypes.c_int
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.restype = ctypes.c_int
        self._psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_ProcessMemoryCounters),
            ctypes.c_uint32,
        ]
        self._psapi.GetProcessMemoryInfo.restype = ctypes.c_int

    def read_memory(self) -> ProcessMemoryUsage:
        counters = _ProcessMemoryCounters(cb=ctypes.sizeof(_ProcessMemoryCounters))
        if not self._psapi.GetProcessMemoryInfo(
            self._kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            _raise_windows_error("GetProcessMemoryInfo")
        return ProcessMemoryUsage(
            counters.PeakWorkingSetSize,
            counters.WorkingSetSize,
            counters.PrivateUsage,
        )

    def create_job(self) -> int:
        # An unnamed job with NULL security attributes has a noninherited handle.
        handle = self._kernel.CreateJobObjectW(None, None)
        if not handle:
            _raise_windows_error("CreateJobObjectW")
        return int(handle)

    def set_memory_limit(self, job: int, limit: int) -> None:
        limits = _ExtendedJobLimits(
            BasicLimitInformation=_BasicJobLimits(LimitFlags=_PROCESS_MEMORY),
            ProcessMemoryLimit=limit,
        )
        if not self._kernel.SetInformationJobObject(
            job,
            _EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            _raise_windows_error("SetInformationJobObject")

    def query_memory_limit(self, job: int) -> int:
        limits = _ExtendedJobLimits()
        if not self._kernel.QueryInformationJobObject(
            job,
            _EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
            None,
        ):
            _raise_windows_error("QueryInformationJobObject")
        if not limits.BasicLimitInformation.LimitFlags & _PROCESS_MEMORY:
            raise OSError("QueryInformationJobObject: process memory limit is absent")
        return limits.ProcessMemoryLimit

    def assign_current_process(self, job: int) -> None:
        if not self._kernel.AssignProcessToJobObject(
            job, self._kernel.GetCurrentProcess()
        ):
            _raise_windows_error(
                "AssignProcessToJobObject (including nested-job policy)"
            )

    def verify_current_process(self, job: int) -> None:
        assigned = ctypes.c_int()
        if not self._kernel.IsProcessInJob(
            self._kernel.GetCurrentProcess(), job, ctypes.byref(assigned)
        ):
            _raise_windows_error("IsProcessInJob")
        if not assigned.value:
            raise OSError("IsProcessInJob: isolated worker is not in its memory job")

    def close_job(self, job: int) -> None:
        if not self._kernel.CloseHandle(job):
            _raise_windows_error("CloseHandle (owned worker memory job)")


class WorkerMemoryLimit:
    """Own one job handle; closing it never kills this or any other process.

    Windows keeps the job and its limits alive while a member process exists,
    even after the last handle closes. KILL_ON_JOB_CLOSE is deliberately absent.
    """

    def __init__(self, api: _MemoryApi, handle: int, committed_bytes: int) -> None:
        self._api = api
        self._handle: int | None = handle
        self._owner_pid = os.getpid()
        self.committed_bytes = committed_bytes

    def close(self) -> None:
        if self._handle is None:
            return
        if self._owner_pid != os.getpid():
            raise OSError("worker memory job handle belongs to another process")
        self._api.close_job(self._handle)
        self._handle = None


def _raise_windows_error(operation: str) -> None:
    error = ctypes.WinError(ctypes.get_last_error())
    raise OSError(f"{operation}: {error}") from error


def _native_api() -> _MemoryApi:
    if sys.platform != "win32":
        raise OSError("isolated worker memory controls require Windows")
    return _WindowsMemoryApi()


def apply_worker_memory_limit(
    max_memory_bytes: int | None, *, api: _MemoryApi | None = None
) -> WorkerMemoryLimit | None:
    """Apply only an explicit committed-byte budget in the spawned worker.

    Native setup/readback failures are errors, including incompatible inherited
    jobs. Existing job policies are never altered or bypassed.
    """
    if max_memory_bytes is None:
        return None
    if (
        isinstance(max_memory_bytes, bool)
        or not isinstance(max_memory_bytes, int)
        or not 0 < max_memory_bytes <= _SIZE_T_MAX
    ):
        raise ValueError("worker memory budget must fit a positive Windows SIZE_T")
    api = _native_api() if api is None else api
    current = api.read_memory()
    if max_memory_bytes <= current.committed_bytes:
        raise ValueError(
            f"worker memory budget {max_memory_bytes} bytes does not exceed its "
            f"already committed {current.committed_bytes} bytes; "
            "a job cannot retroactively constrain earlier allocations"
        )
    handle = api.create_job()
    try:
        api.set_memory_limit(handle, max_memory_bytes)
        confirmed = api.query_memory_limit(handle)
        if confirmed != max_memory_bytes:
            raise OSError(
                "worker memory limit readback mismatch: "
                f"requested={max_memory_bytes}, actual={confirmed} committed bytes"
            )
        api.assign_current_process(handle)
        api.verify_current_process(handle)
    except (OSError, ValueError, MemoryError) as error:
        try:
            api.close_job(handle)
        except OSError as cleanup_error:
            raise OSError(
                f"{error}; job cleanup also failed: {cleanup_error}"
            ) from error
        raise
    return WorkerMemoryLimit(api, handle, max_memory_bytes)


def read_peak_rss(*, api: _MemoryApi | None = None) -> PeakRssReading:
    """Return native resident-byte telemetry, with complete unknown diagnostics."""
    try:
        api = _native_api() if api is None else api
        peak = api.read_memory().peak_rss_bytes
        if not 0 < peak < _SIZE_T_MAX:
            raise ValueError(f"GetProcessMemoryInfo returned invalid peak RSS: {peak}")
    except (OSError, ValueError, AttributeError, MemoryError, OverflowError) as error:
        detail = f"{type(error).__name__}: {error}"
        return PeakRssReading(None, (f"peak_rss_unavailable: {detail}",))
    return PeakRssReading(peak)


__all__ = (
    "PeakRssReading",
    "ProcessMemoryUsage",
    "WorkerMemoryLimit",
    "apply_worker_memory_limit",
    "read_peak_rss",
)
