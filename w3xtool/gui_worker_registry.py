"""Generation-aware registry for bounded GUI background workers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import threading
from time import monotonic
from typing import Protocol


@dataclass(frozen=True, slots=True)
class GuiWorkerTicket:
    worker_id: int
    group: str
    generation: int
    cancellation: threading.Event


class GuiWorkerRegistryStopped(RuntimeError):
    """A worker was requested after application shutdown began."""

    def __init__(self, group: str) -> None:
        self.group = group
        super().__init__(f"GUI worker registry is stopped: {group}")


class GuiWorkerThread(Protocol):
    """Joinable daemon handle created by a worker thread factory."""

    def start(self) -> None: ...

    def join(self, timeout: float | None = None) -> None: ...

    def is_alive(self) -> bool: ...


class GuiWorkerThreadFactory(Protocol):
    """Construct one named GUI worker without starting it."""

    def __call__(
        self,
        *,
        target: Callable[[], None],
        daemon: bool,
        name: str,
    ) -> GuiWorkerThread: ...


type GuiWorkerTarget = Callable[[GuiWorkerTicket], None]


@dataclass(frozen=True, slots=True)
class _WorkerRecord:
    ticket: GuiWorkerTicket
    thread: GuiWorkerThread


class GuiWorkerRegistry:  # noqa: MUTABLE_OK - lifecycle registry owns changing workers.
    """Track worker generations and bound application shutdown."""

    def __init__(
        self,
        thread_factory: GuiWorkerThreadFactory = threading.Thread,
    ) -> None:
        self._thread_factory = thread_factory
        self._lock = threading.Lock()
        self._stopped = False
        self._next_worker_id = 1
        self._generations: dict[str, int] = {}
        self._workers: dict[int, _WorkerRecord] = {}

    def start(
        self,
        group: str,
        target: GuiWorkerTarget,
        *,
        replace: bool,
    ) -> GuiWorkerTicket:
        """Start one daemon worker and optionally invalidate its group."""
        with self._lock:
            if self._stopped:
                raise GuiWorkerRegistryStopped(group)
            generation = self._generation_for_start(group, replace)
            worker_id = self._next_worker_id
            self._next_worker_id += 1
            ticket = GuiWorkerTicket(
                worker_id,
                group,
                generation,
                threading.Event(),
            )
            thread = self._thread_factory(
                target=lambda: self._run(ticket, target),
                daemon=True,
                name=f"w3xray-{group}-{worker_id}",
            )
            self._workers[worker_id] = _WorkerRecord(ticket, thread)
        try:
            thread.start()
        except RuntimeError:
            ticket.cancellation.set()
            self.finish(ticket)
            raise
        return ticket

    def cancel_group(self, group: str) -> None:
        """Invalidate one group and request cooperative cancellation."""
        with self._lock:
            self._generations[group] = self._generations.get(group, 0) + 1
            tickets = tuple(
                record.ticket
                for record in self._workers.values()
                if record.ticket.group == group
            )
        for ticket in tickets:
            ticket.cancellation.set()

    def accepts(self, ticket: GuiWorkerTicket) -> bool:
        """Return whether a callback still belongs to the active generation."""
        with self._lock:
            return (
                not self._stopped
                and self._generations.get(ticket.group, 0) == ticket.generation
            )

    def finish(self, ticket: GuiWorkerTicket) -> None:
        """Forget a completed worker without invalidating queued callbacks."""
        with self._lock:
            current = self._workers.get(ticket.worker_id)
            if current is not None and current.ticket == ticket:
                del self._workers[ticket.worker_id]

    def shutdown(self, timeout_seconds: float) -> tuple[str, ...]:
        """Cancel all workers and join them under one shared deadline."""
        deadline = monotonic() + max(0.0, timeout_seconds)
        with self._lock:
            self._stopped = True
            groups = tuple(self._generations)
        for group in groups:
            self.cancel_group(group)
        with self._lock:
            records = tuple(self._workers[key] for key in sorted(self._workers))
        for record in records:
            record.thread.join(max(0.0, deadline - monotonic()))
        with self._lock:
            active = tuple(
                record
                for key in sorted(self._workers)
                if (record := self._workers[key]).thread.is_alive()
            )
        return tuple(dict.fromkeys(record.ticket.group for record in active))

    def _generation_for_start(self, group: str, replace: bool) -> int:
        generation = self._generations.get(group, 0)
        if replace or generation == 0:
            generation += 1
            self._generations[group] = generation
        if replace:
            for record in self._workers.values():
                if record.ticket.group == group:
                    record.ticket.cancellation.set()
        return generation

    def _run(self, ticket: GuiWorkerTicket, target: GuiWorkerTarget) -> None:
        try:
            target(ticket)
        finally:
            self.finish(ticket)


__all__ = (
    "GuiWorkerRegistry",
    "GuiWorkerRegistryStopped",
    "GuiWorkerThread",
    "GuiWorkerThreadFactory",
    "GuiWorkerTarget",
    "GuiWorkerTicket",
)
