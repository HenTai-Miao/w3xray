from __future__ import annotations

from pathlib import Path
from typing import Never

import pytest

from tests.test_gui_current_map import _candidate, _harness, _snapshot
from w3xtool import gui_current_map as current_gui
from w3xtool import gui_current_map_presenter as presenter
from w3xtool.current_map_models import CurrentMapResolution, EvidenceKind, ResolutionStatus


@pytest.mark.parametrize("accepted", (True, False))
def test_single_suggestion_requires_confirmation_before_snapshot(
    accepted: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness(monkeypatch)
    source = tmp_path / "hint.w3x"
    snapshot = _snapshot(tmp_path / "private" / "current.w3x")
    resolution = CurrentMapResolution(
        ResolutionStatus.SUGGESTED,
        (_candidate(source, EvidenceKind.RECENT_CACHE),),
    )
    monkeypatch.setattr(current_gui, "locate_current_map", lambda _roots: resolution)
    created: list[Path] = []
    monkeypatch.setattr(
        current_gui,
        "create_current_map_snapshot",
        lambda path: created.append(path) or snapshot,
    )
    confirmations: list[str] = []
    monkeypatch.setattr(
        current_gui.messagebox,
        "askyesno",
        lambda _title, message, **_options: confirmations.append(message) or accepted,
    )

    harness.on_open_current_map()
    harness._poll_current_map_results()

    assert len(confirmations) == 1
    assert str(source) in confirmations[0]
    assert created == ([source] if accepted else [])
    assert harness.loaded == ([str(snapshot.path)] if accepted else [])
    assert harness.button_state() == "normal"
    expected_status = "正在解析当前地图" if accepted else "已取消获取当前地图"
    assert harness.status_text() == expected_status


@pytest.mark.parametrize(
    ("status", "kind"),
    (
        (ResolutionStatus.AMBIGUOUS, EvidenceKind.DIRECT_OPEN),
        (ResolutionStatus.SUGGESTED, EvidenceKind.RECENT_CACHE),
    ),
)
def test_non_unique_candidates_offer_a_bounded_choice_that_never_guesses(
    status: ResolutionStatus,
    kind: EvidenceKind,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness(monkeypatch)
    candidates = tuple(
        _candidate(tmp_path / f"candidate-{index}\x1b\n.w3x", kind)
        for index in range(10)
    )
    resolution = CurrentMapResolution(status, candidates)
    monkeypatch.setattr(current_gui, "locate_current_map", lambda _roots: resolution)
    offered: list[tuple[object, ...]] = []
    snapshot = _snapshot(tmp_path / "private" / "current.w3x")
    created: list[Path] = []
    monkeypatch.setattr(
        current_gui,
        "create_current_map_snapshot",
        lambda path: created.append(path) or snapshot,
    )

    def chooser(choice_candidates: tuple[object, ...]) -> object:
        offered.append(choice_candidates)
        return choice_candidates[7].path  # type: ignore[attr-defined]

    monkeypatch.setattr(presenter, "_candidate_chooser", chooser)

    harness.on_open_current_map()
    harness._poll_current_map_results()

    assert len(offered) == 1 and len(offered[0]) == 10
    assert created == [candidates[7].path]
    assert harness.loaded == [str(snapshot.path)]
    assert harness.button_state() == "normal"


@pytest.mark.parametrize(
    ("status", "kind"),
    (
        (ResolutionStatus.AMBIGUOUS, EvidenceKind.DIRECT_OPEN),
        (ResolutionStatus.SUGGESTED, EvidenceKind.RECENT_CACHE),
    ),
)
def test_declining_the_candidate_choice_loads_nothing(
    status: ResolutionStatus,
    kind: EvidenceKind,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness(monkeypatch)
    candidates = tuple(_candidate(tmp_path / f"pick-{index}.w3x", kind) for index in range(3))
    resolution = CurrentMapResolution(status, candidates)
    monkeypatch.setattr(current_gui, "locate_current_map", lambda _roots: resolution)
    monkeypatch.setattr(presenter, "_candidate_chooser", lambda _candidates: None)

    harness.on_open_current_map()
    harness._poll_current_map_results()

    assert harness.loaded == []
    assert harness.status_text() == "已取消获取当前地图"


def test_candidate_choice_rows_are_bounded_and_sanitized(tmp_path: Path) -> None:
    # Given: ten candidates whose paths contain control characters.
    candidates = tuple(
        _candidate(tmp_path / f"candidate-{index}\x1b\n.w3x", EvidenceKind.RECENT_CACHE)
        for index in range(10)
    )

    # When: the pure chooser rows are rendered.
    rows = presenter.candidate_choice_rows(candidates)
    joined = "\n".join(rows)

    # Then: at most eight sanitized rows are offered and the omission is stated.
    assert len(rows) == 8
    assert "candidate-7" in joined and "candidate-8" not in joined
    assert "\x1b" not in joined


@pytest.mark.parametrize(
    ("status", "expected", "expected_status"),
    (
        (
            ResolutionStatus.NOT_FOUND,
            "未找到正在使用的 Warcraft III 地图。",
            "未找到当前地图",
        ),
        (
            ResolutionStatus.UNAVAILABLE,
            "当前平台无法可靠探测正在使用的 Warcraft III 地图。",
            "无法探测当前地图",
        ),
    ),
)
def test_no_result_statuses_have_stable_messages(
    status: ResolutionStatus,
    expected: str,
    expected_status: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness(monkeypatch)
    resolution = CurrentMapResolution(status, ())
    messages: list[str] = []
    monkeypatch.setattr(current_gui, "locate_current_map", lambda _roots: resolution)
    monkeypatch.setattr(
        current_gui.messagebox,
        "showinfo",
        lambda _title, message, **_options: messages.append(message),
    )

    harness.on_open_current_map()
    harness._poll_current_map_results()

    assert messages == [expected]
    assert harness.loaded == []
    assert harness.status_text() == expected_status


@pytest.mark.parametrize("snapshot_failure", (False, True))
def test_worker_failures_have_one_stable_error(
    snapshot_failure: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness(monkeypatch)
    candidate = _candidate(tmp_path / "private.w3x", EvidenceKind.DIRECT_OPEN)
    resolution = CurrentMapResolution(ResolutionStatus.FOUND, (candidate,))

    def failure(_value: tuple[Path, ...] | Path) -> Never:
        raise OSError("private detail")

    monkeypatch.setattr(
        current_gui,
        "locate_current_map",
        (lambda _roots: resolution) if snapshot_failure else failure,
    )
    monkeypatch.setattr(current_gui, "create_current_map_snapshot", failure)
    errors: list[tuple[str, str]] = []
    monkeypatch.setattr(
        current_gui.messagebox,
        "showerror",
        lambda title, message, **_options: errors.append((title, message)),
    )

    harness.on_open_current_map()
    harness._poll_current_map_results()

    assert errors == [("获取当前地图失败", "获取当前地图失败，请稍后重试。")]
    assert harness.status_text() == "获取当前地图失败"
