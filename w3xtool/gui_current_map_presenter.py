"""Typed events and bounded text for current-map GUI presentation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox
from typing import Final, assert_never

from .current_map_models import CurrentMapResolution, MapCandidate, ResolutionStatus
from .current_map_snapshot import CurrentMapSnapshot
from .presentation_safety import single_line_text


MAX_CANDIDATES: Final = 8
WORKER_ERROR_TITLE: Final = "获取当前地图失败"
WORKER_ERROR_MESSAGE: Final = "获取当前地图失败，请稍后重试。"
NOT_FOUND_MESSAGE: Final = "未找到正在使用的 Warcraft III 地图。"
UNAVAILABLE_MESSAGE: Final = "当前平台无法可靠探测正在使用的 Warcraft III 地图。"
CANDIDATE_CHOICE_TITLE: Final = "选择当前地图"
CANDIDATE_CHOICE_HEADER: Final = "发现多个候选，请选择正在使用的地图："
CANDIDATE_CHOICE_OMITTED: Final = "另有 {omitted} 个候选未显示。"
CANCELLED_STATUS: Final = "已取消获取当前地图"


@dataclass(frozen=True, slots=True)
class ResolutionReady:
    resolution: CurrentMapResolution


@dataclass(frozen=True, slots=True)
class SnapshotReady:
    snapshot: CurrentMapSnapshot


@dataclass(frozen=True, slots=True)
class WorkerError:
    """A stable worker failure without host details."""


type CurrentMapEvent = ResolutionReady | SnapshotReady | WorkerError


@dataclass(frozen=True, slots=True)
class AcceptedSuggestion:
    path: Path


@dataclass(frozen=True, slots=True)
class TerminalStatus:
    text: str


type PresentedResolution = AcceptedSuggestion | TerminalStatus


def candidate_text(candidate: MapCandidate) -> str:
    """Return one bounded, single-line candidate description."""
    path = single_line_text(str(candidate.path), max_chars=512)
    sources = "、".join(dict.fromkeys(item.kind.value for item in candidate.evidence))
    return single_line_text(
        f"{path}（来源：{sources or '未提供'}）",
        max_chars=768,
    )


def suggestion_prompt(candidate: MapCandidate) -> str:
    """Explain that a hint needs explicit confirmation."""
    return (
        f"仅发现提示证据，请确认后再打开：\n{candidate_text(candidate)}\n\n是否继续？"
    )


type CandidateChooser = Callable[[tuple[MapCandidate, ...]], Path | None]


def candidate_choice_rows(candidates: tuple[MapCandidate, ...]) -> tuple[str, ...]:
    """Return sanitized chooser rows capped at the bounded candidate count."""
    return tuple(candidate_text(item) for item in candidates[:MAX_CANDIDATES])


def _tk_choose_candidate(candidates: tuple[MapCandidate, ...]) -> Path | None:
    """Show one modal list dialog and return the picked path, or None."""
    import tkinter as tk

    dialog = tk.Toplevel()
    dialog.title(CANDIDATE_CHOICE_TITLE)
    dialog.grab_set()
    header = tk.Label(
        dialog,
        text=CANDIDATE_CHOICE_HEADER,
        anchor="w",
        justify="left",
    )
    header.pack(fill="x", padx=12, pady=(12, 4))
    rows = candidate_choice_rows(candidates)
    selection: list[Path] = []

    body = tk.Frame(dialog)
    listbox = tk.Listbox(
        body,
        width=110,
        height=len(rows),
        selectmode=tk.SINGLE,
        exportselection=False,
    )
    for row in rows:
        listbox.insert(tk.END, row)
    listbox.selection_set(0)
    listbox.grid(row=0, column=0, sticky="nsew")
    scrollbar = tk.Scrollbar(body, orient=tk.HORIZONTAL, command=listbox.xview)
    listbox.configure(xscrollcommand=scrollbar.set)
    scrollbar.grid(row=1, column=0, sticky="ew")
    body.columnconfigure(0, weight=1)
    body.rowconfigure(0, weight=1)
    body.pack(fill="both", expand=True, padx=12)
    if len(candidates) > MAX_CANDIDATES:
        omitted = tk.Label(
            dialog,
            text=CANDIDATE_CHOICE_OMITTED.format(omitted=len(candidates) - MAX_CANDIDATES),
            anchor="w",
            justify="left",
        )
        omitted.pack(fill="x", padx=12)

    def confirm(_event: object | None = None) -> None:
        picked = listbox.curselection()
        if picked and picked[0] < len(rows):
            selection.append(candidates[picked[0]].path)
        dialog.destroy()

    def cancel() -> None:
        dialog.destroy()

    buttons = tk.Frame(dialog)
    tk.Button(buttons, text="确定", width=10, command=confirm).pack(side="right", padx=6)
    tk.Button(buttons, text="取消", width=10, command=cancel).pack(side="right")
    buttons.pack(fill="x", padx=12, pady=(6, 12))
    listbox.bind("<Double-Button-1>", confirm)
    listbox.bind("<Return>", confirm)
    dialog.wait_window(dialog)
    return selection[0] if selection else None


_candidate_chooser: CandidateChooser = _tk_choose_candidate


def present_resolution(resolution: CurrentMapResolution) -> PresentedResolution:
    """Present one resolution and return its accepted or terminal UI outcome."""
    match resolution.status:
        case ResolutionStatus.SUGGESTED:
            if len(resolution.candidates) == 1:
                candidate = resolution.candidates[0]
                accepted = messagebox.askyesno(
                    "确认当前地图",
                    suggestion_prompt(candidate),
                )
                if accepted:
                    return AcceptedSuggestion(candidate.path)
                return TerminalStatus(CANCELLED_STATUS)
            return _present_candidates(resolution.candidates)
        case ResolutionStatus.AMBIGUOUS:
            return _present_candidates(resolution.candidates)
        case ResolutionStatus.NOT_FOUND:
            messagebox.showinfo("未找到当前地图", NOT_FOUND_MESSAGE)
            return TerminalStatus("未找到当前地图")
        case ResolutionStatus.UNAVAILABLE:
            messagebox.showinfo("无法探测当前地图", UNAVAILABLE_MESSAGE)
            return TerminalStatus("无法探测当前地图")
        case ResolutionStatus.FOUND:
            messagebox.showerror(WORKER_ERROR_TITLE, WORKER_ERROR_MESSAGE)
            return TerminalStatus(WORKER_ERROR_TITLE)
        case unreachable:
            assert_never(unreachable)


def _present_candidates(candidates: tuple[MapCandidate, ...]) -> PresentedResolution:
    """Let the user pick among bounded candidates instead of refusing."""
    chosen = _candidate_chooser(candidates)
    if chosen is not None:
        return AcceptedSuggestion(chosen)
    return TerminalStatus(CANCELLED_STATUS)
