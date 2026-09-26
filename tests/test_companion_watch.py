from __future__ import annotations

from pathlib import Path
import threading

from w3xtool.companion_watch import (
    _LOCATE_FAILED_NOTE,
    _PROBE_UNAVAILABLE_NOTE,
    _RUNNING_NO_HINTS_NOTE,
    _SNAPSHOT_FAILED_NOTE,
    CompanionEvent,
    companion_transition,
    game_process_running,
    run_companion_watch,
    source_key,
)
from w3xtool.current_map_models import (
    CurrentMapResolution,
    GameProcess,
    MapCandidate,
    ResolutionStatus,
)
from w3xtool.current_map_process import ProcessProbeReport
from w3xtool.current_map_snapshot import CurrentMapSnapshot

_A = Path("/maps/a.w3x")
_B = Path("/maps/b.w3x")
_ROOTS = (Path("/maps"),)


def _report(processes: int = 0, available: bool = True) -> ProcessProbeReport:
    return ProcessProbeReport(
        tuple(GameProcess(100 + index, "war3.exe", "") for index in range(processes)),
        available,
    )


def _resolution(
    status: ResolutionStatus,
    path: Path | None = None,
) -> CurrentMapResolution:
    if path is None:
        return CurrentMapResolution(status, ())
    return CurrentMapResolution(status, (MapCandidate(path, ()),))


def _multi_resolution(
    status: ResolutionStatus,
    *paths: Path,
) -> CurrentMapResolution:
    return CurrentMapResolution(
        status,
        tuple(MapCandidate(path, ()) for path in paths),
    )


def _snapshot(path: Path) -> CurrentMapSnapshot:
    return CurrentMapSnapshot(
        path=path.parent / "current.w3x",
        source_path=path,
        sha256="0" * 64,
        source_device=1,
        source_inode=1,
        source_size=0,
        source_mtime_ns=0,
        _directory_device=1,
        _directory_inode=1,
    )


class _Hooks:
    """Record every hook event and remember the newest adopted source."""

    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []
        self.last_source: Path | None = None

    def on_game_started(self) -> None:
        self.events.append(("started", None))

    def on_game_exited(self) -> None:
        self.events.append(("exited", None))

    def on_map_ready(self, snapshot: CurrentMapSnapshot) -> None:
        self.last_source = snapshot.source_path
        self.events.append(("ready", snapshot.source_path))

    def on_map_unresolved(self, resolution: CurrentMapResolution) -> None:
        self.events.append(("unresolved", resolution))

    def on_watch_note(self, message: str) -> None:
        self.events.append(("note", message))

    def names(self) -> list[str]:
        return [name for name, _payload in self.events]

    def payloads(self, name: str) -> list[object]:
        return [payload for event, payload in self.events if event == name]


class _Script:
    """Scripted probe/locate/snapshot/sleep inputs for one watch run."""

    def __init__(
        self,
        hooks: _Hooks,
        reports: list[ProcessProbeReport],
        resolutions: list[CurrentMapResolution],
        sleeps: list[bool],
    ) -> None:
        self.hooks = hooks
        self.reports = list(reports)
        self.resolutions = list(resolutions)
        self.sleeps = list(sleeps)
        self.probe_calls = 0
        self.locate_calls: list[tuple[tuple[Path, ...], ProcessProbeReport]] = []
        self.snapshot_calls: list[Path] = []
        self.locate_error = False
        self.snapshot_error = False

    def probe(self) -> ProcessProbeReport:
        self.probe_calls += 1
        return self.reports.pop(0)

    def locate(
        self,
        roots: tuple[Path, ...],
        report: ProcessProbeReport,
    ) -> CurrentMapResolution:
        self.locate_calls.append((roots, report))
        if self.locate_error:
            raise RuntimeError("locate failed")
        return self.resolutions.pop(0)

    def snapshot(self, path: Path) -> CurrentMapSnapshot:
        self.snapshot_calls.append(path)
        if self.snapshot_error:
            raise OSError("snapshot failed")
        return _snapshot(path)

    def sleep(self, _seconds: float) -> bool:
        return self.sleeps.pop(0)

    def loaded_source(self) -> str | None:
        if self.hooks.last_source is None:
            return None
        return source_key(self.hooks.last_source)

    def run(self, cancellation: threading.Event | None = None) -> None:
        run_companion_watch(
            cancellation if cancellation is not None else threading.Event(),
            roots_provider=lambda: _ROOTS,
            probe=self.probe,
            locate=self.locate,
            snapshot_factory=self.snapshot,
            loaded_source=self.loaded_source,
            hooks=self.hooks,
            interval_seconds=5.0,
            sleep=self.sleep,
        )


def test_companion_transition_emits_only_real_edges() -> None:
    assert companion_transition(None, True) is None
    assert companion_transition(None, False) is None
    assert companion_transition(True, True) is None
    assert companion_transition(False, False) is None
    assert companion_transition(False, True) is CompanionEvent.GAME_STARTED
    assert companion_transition(True, False) is CompanionEvent.GAME_EXITED


def test_game_process_running_requires_a_usable_probe() -> None:
    assert game_process_running(_report(processes=1)) is True
    assert game_process_running(_report(processes=0)) is False
    assert game_process_running(_report(processes=1, available=False)) is False


def test_watch_auto_loads_new_maps_for_one_running_session() -> None:
    hooks = _Hooks()
    script = _Script(
        hooks,
        reports=[
            _report(),
            _report(processes=1),
            _report(processes=1),
            _report(processes=1),
            _report(),
        ],
        resolutions=[
            _resolution(ResolutionStatus.FOUND, _A),
            _resolution(ResolutionStatus.FOUND, _A),
            _resolution(ResolutionStatus.FOUND, _B),
        ],
        sleeps=[False, False, False, False, True],
    )

    script.run()

    assert hooks.names() == ["started", "ready", "ready", "exited"]
    assert hooks.payloads("ready") == [_A, _B]
    assert script.snapshot_calls == [_A, _B]
    assert [roots for roots, _seen in script.locate_calls] == [_ROOTS] * 3


def test_watch_prompts_once_per_stable_hint_set() -> None:
    hooks = _Hooks()
    script = _Script(
        hooks,
        reports=[
            _report(),
            _report(processes=1),
            _report(processes=1),
            _report(processes=1),
        ],
        resolutions=[
            _resolution(ResolutionStatus.SUGGESTED, _A),
            _resolution(ResolutionStatus.SUGGESTED, _A),
            _resolution(ResolutionStatus.NOT_FOUND),
        ],
        sleeps=[False, False, False, True],
    )

    script.run()

    assert hooks.names() == ["started", "unresolved", "note"]
    unresolved = hooks.payloads("unresolved")
    assert len(unresolved) == 1
    assert isinstance(unresolved[0], CurrentMapResolution)
    assert unresolved[0].candidates[0].path == _A
    assert hooks.payloads("note") == [_RUNNING_NO_HINTS_NOTE]
    assert script.snapshot_calls == []


def test_watch_reprompts_when_the_hint_set_changes() -> None:
    hooks = _Hooks()
    script = _Script(
        hooks,
        reports=[_report(processes=1)] * 3,
        resolutions=[
            _multi_resolution(ResolutionStatus.AMBIGUOUS, _A, _B),
            _multi_resolution(ResolutionStatus.AMBIGUOUS, _A, _B),
            _resolution(ResolutionStatus.SUGGESTED, _B),
        ],
        sleeps=[False, False, True],
    )

    script.run()

    assert hooks.names() == ["unresolved", "unresolved"]
    assert script.snapshot_calls == []


def test_watch_stays_silent_when_the_loaded_map_is_among_hints() -> None:
    hooks = _Hooks()
    script = _Script(
        hooks,
        reports=[_report(processes=1)] * 3,
        resolutions=[_resolution(ResolutionStatus.SUGGESTED, _A)] * 3,
        sleeps=[False, False, True],
    )
    script.hooks.last_source = _A

    script.run()

    assert hooks.names() == []


def test_watch_reprompts_after_game_exit_resets_the_session() -> None:
    hooks = _Hooks()
    script = _Script(
        hooks,
        reports=[
            _report(processes=1),
            _report(),
            _report(processes=1),
        ],
        resolutions=[
            _resolution(ResolutionStatus.SUGGESTED, _A),
            _resolution(ResolutionStatus.SUGGESTED, _A),
            _resolution(ResolutionStatus.SUGGESTED, _A),
        ],
        sleeps=[False, False, True],
    )

    script.run()

    assert hooks.names() == ["unresolved", "exited", "started", "unresolved"]


def test_watch_notes_when_direct_evidence_has_several_candidates() -> None:
    hooks = _Hooks()
    script = _Script(
        hooks,
        reports=[_report(processes=1)],
        resolutions=[_multi_resolution(ResolutionStatus.FOUND, _A, _B)],
        sleeps=[True],
    )

    script.run()

    assert hooks.names() == ["note"]
    assert hooks.payloads("note") == [_RUNNING_NO_HINTS_NOTE]
    assert script.snapshot_calls == []


def test_watch_reports_probe_unavailable_without_fabricating_edges() -> None:
    hooks = _Hooks()
    script = _Script(
        hooks,
        reports=[_report(available=False), _report()],
        resolutions=[],
        sleeps=[False, True],
    )

    script.run()

    assert hooks.names() == ["note"]
    assert hooks.payloads("note") == [_PROBE_UNAVAILABLE_NOTE]
    assert script.locate_calls == []


def test_watch_survives_locate_and_snapshot_failures() -> None:
    hooks = _Hooks()
    script = _Script(
        hooks,
        reports=[_report(), _report(processes=1)],
        resolutions=[_resolution(ResolutionStatus.FOUND, _A)],
        sleeps=[False, True],
    )
    script.locate_error = True

    script.run()

    assert hooks.names() == ["started", "note"]
    assert hooks.payloads("note") == [_LOCATE_FAILED_NOTE]

    retry_hooks = _Hooks()
    retry = _Script(
        retry_hooks,
        reports=[_report(), _report(processes=1)],
        resolutions=[_resolution(ResolutionStatus.FOUND, _A)],
        sleeps=[False, True],
    )
    retry.snapshot_error = True

    retry.run()

    assert retry_hooks.names() == ["started", "note"]
    assert retry_hooks.payloads("note") == [_SNAPSHOT_FAILED_NOTE]


def test_watch_exits_before_probing_when_already_cancelled() -> None:
    hooks = _Hooks()
    script = _Script(
        hooks,
        reports=[_report(processes=1)],
        resolutions=[],
        sleeps=[],
    )
    cancellation = threading.Event()
    cancellation.set()

    script.run(cancellation)

    assert script.probe_calls == 0
    assert hooks.names() == []
