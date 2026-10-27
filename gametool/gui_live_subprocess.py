"""Per-request live probe subprocesses with owned process-tree cleanup."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import ctypes
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .live_cli import LiveCliOptions

_LOGGER = logging.getLogger(__name__)


def build_live_probe_command(
    options: LiveCliOptions,
    *,
    executable: str | None = None,
    frozen: bool | None = None,
) -> tuple[str, ...]:
    from .live_cli import _request_arguments

    executable = sys.executable if executable is None else executable
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    prefix = (
        (executable, "live")
        if frozen
        else (executable, "-X", "utf8", "-m", "gametool", "live")
    )
    return (*prefix, *_request_arguments(options))


def build_live_probe_environment(
    environment: Mapping[str, str] | None = None,
    *,
    frozen: bool | None = None,
) -> dict[str, str]:
    env = dict(os.environ if environment is None else environment)
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if not frozen:
        env["PYTHONSAFEPATH"] = "1"
        package_root = str(Path(__file__).resolve().parents[1])
        inherited = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            package_root if inherited is None else package_root + os.pathsep + inherited
        )
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


@dataclass(frozen=True, slots=True)
class OwnedProbeIdentity:
    parent_pid: int
    pid: int


@dataclass(frozen=True, slots=True)
class LiveProbeResult:
    exit_code: int
    stdout: str
    stderr: str
    cancelled: bool = False


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


class _WindowsProbeJob:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel = self._kernel
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        kernel.CreateJobObjectW.restype = ctypes.c_void_p
        kernel.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        kernel.SetInformationJobObject.restype = ctypes.c_int
        kernel.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel.AssignProcessToJobObject.restype = ctypes.c_int
        kernel.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.TerminateJobObject.restype = ctypes.c_int
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.restype = ctypes.c_int
        self._resume = ctypes.WinDLL("ntdll").NtResumeProcess
        self._resume.argtypes = [ctypes.c_void_p]
        self._resume.restype = ctypes.c_long
        self._handle = kernel.CreateJobObjectW(None, None)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _ExtendedJobLimits(
            BasicLimitInformation=_BasicJobLimits(LimitFlags=0x2000)
        )
        if not kernel.SetInformationJobObject(
            self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, process: subprocess.Popen[str]) -> None:
        if not self._kernel.AssignProcessToJobObject(
            self._handle, int(getattr(process, "_handle"))
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    def resume(self, process: subprocess.Popen[str]) -> None:
        status = self._resume(int(getattr(process, "_handle")))
        if status < 0:
            raise OSError(f"无法恢复本次探针子进程: NTSTATUS {status & 0xFFFFFFFF:08x}")

    def stop(self) -> None:
        with self._lock:
            if self._handle and not self._kernel.TerminateJobObject(self._handle, 2):
                raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        with self._lock:
            handle, self._handle = self._handle, None
        if handle and not self._kernel.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


class LiveProbeChild:
    """Own exactly one request, including a Windows launcher and its descendants."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        env: Mapping[str, str],
        cwd: str,
    ) -> None:
        self.command = tuple(command)
        self._env = dict(env)
        self._cwd = cwd
        self._lock = threading.Lock()
        self._cancelled = threading.Event()
        self._started = False
        self._process: subprocess.Popen[str] | None = None
        self._job: _WindowsProbeJob | None = None
        self.identity: OwnedProbeIdentity | None = None

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            process, job, identity = self._process, self._job, self.identity
            if identity is None or identity.parent_pid != os.getpid():
                return
            try:
                if job is not None:
                    job.stop()
                elif process is not None:
                    if os.name == "nt":
                        process.terminate()
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass  # This owned request has already exited.
            except OSError:
                _LOGGER.warning(
                    "failed to cancel owned live probe child %s",
                    identity.pid,
                    exc_info=True,
                )

    def run(self) -> LiveProbeResult:
        with self._lock:
            if self._started:
                raise RuntimeError("同一探针请求不能重复启动")
            self._started = True
            if self._cancelled.is_set():
                return LiveProbeResult(2, "", "", True)
        process = None
        job = _WindowsProbeJob() if os.name == "nt" else None
        try:
            process = subprocess.Popen(
                self.command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self._env,
                cwd=self._cwd,
                creationflags=(0x00000004 | 0x08000000) if job is not None else 0,
                start_new_session=job is None,
            )
            if job is not None:
                job.assign(process)
            with self._lock:
                self._process, self._job = process, job
                self.identity = OwnedProbeIdentity(os.getpid(), process.pid)
            if self._cancelled.is_set():
                self.cancel()
            elif job is not None:
                try:
                    job.resume(process)
                except OSError:
                    if not self._cancelled.is_set():
                        raise
            stdout, stderr = process.communicate()
            return LiveProbeResult(
                process.returncode, stdout, stderr, self._cancelled.is_set()
            )
        finally:
            if job is not None:
                job.close()
            if process is not None:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=2)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
            with self._lock:
                self._process, self._job = None, None
