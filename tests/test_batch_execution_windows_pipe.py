"""Windows ended-pipe behavior for isolated batch workers."""

from __future__ import annotations

from time import monotonic

from w3xtool.batch_execution import MapExecutionFailure, _wait_for_child


class _ExitedProcess:
    exitcode = 7

    def is_alive(self) -> bool:
        return False

    def join(self, timeout: float | None = None) -> None:
        _ = timeout
        return None

    def terminate(self) -> None:
        raise AssertionError("an exited process must not be terminated")

    def kill(self) -> None:
        raise AssertionError("an exited process must not be killed")

    def close(self) -> None:
        return None


class _EndedReceiver:
    def poll(self, timeout: float = 0.0) -> bool:
        _ = timeout
        raise BrokenPipeError("pipe has ended")

    def recv_bytes(self, maxlength: int | None = None) -> bytes:
        _ = maxlength
        raise AssertionError("an ended pipe has no payload")

    def close(self) -> None:
        return None


def test_ended_windows_pipe_reports_child_exit() -> None:
    # Given: Windows reports a hard-exited child's empty pipe from poll().
    process = _ExitedProcess()
    receiver = _EndedReceiver()

    # When
    outcome = _wait_for_child(process, receiver, monotonic() + 1.0, None)

    # Then
    assert isinstance(outcome, MapExecutionFailure)
    assert outcome.code == "child_process_exit"
    assert "7" in outcome.detail
