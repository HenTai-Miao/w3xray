"""Typed events and bounded text for current-map GUI presentation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox
from typing import Final, assert_never

from .current_map_models import CurrentMapResolution, MapCandidate, ResolutionStatus
from .current_map_snapshot import CurrentMapSnapshot
from .presentation_safety import single_line_text


MAX_CANDIDATES: Final = 8
NON_UNIQUE_TITLE: Final = "当前地图候选不唯一"
WORKER_ERROR_TITLE: Final = "获取当前地图失败"
WORKER_ERROR_MESSAGE: Final = "获取当前地图失败，请稍后重试。"
NOT_FOUND_MESSAGE: Final = "未找到正在使用的 Warcraft III 地图。"
UNAVAILABLE_MESSAGE: Final = "当前平台无法可靠探测正在使用的 Warcraft III 地图。"
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


def candidate_list_message(header: str, candidates: tuple[MapCandidate, ...]) -> str:
    """List at most eight inert candidate paths and report omissions."""
    lines = [single_line_text(header)]
    lines.extend(f"- {candidate_text(item)}" for item in candidates[:MAX_CANDIDATES])
    omitted = len(candidates) - MAX_CANDIDATES
    if omitted > 0:
        lines.append(f"- 另有 {omitted} 个候选未显示。")
    return "\n".join(lines)


def present_resolution(resolution: CurrentMapResolution) -> PresentedResolution:
    """Present one resolution and return its accepted or terminal UI outcome."""
    match resolution.status:
        case ResolutionStatus.SUGGESTED:
            if len(resolution.candidates) != 1:
                messagebox.showwarning(
                    NON_UNIQUE_TITLE,
                    candidate_list_message(
                        "发现多个提示候选，不能自动选择。",
                        resolution.candidates,
                    ),
                )
                return TerminalStatus(NON_UNIQUE_TITLE)
            candidate = resolution.candidates[0]
            accepted = messagebox.askyesno(
                "确认当前地图",
                suggestion_prompt(candidate),
            )
            if accepted:
                return AcceptedSuggestion(candidate.path)
            return TerminalStatus(CANCELLED_STATUS)
        case ResolutionStatus.AMBIGUOUS:
            messagebox.showwarning(
                NON_UNIQUE_TITLE,
                candidate_list_message(
                    "发现多个直接证据候选，不能自动选择。",
                    resolution.candidates,
                ),
            )
            return TerminalStatus(NON_UNIQUE_TITLE)
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
