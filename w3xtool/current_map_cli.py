"""Typed CLI boundary for locating and parsing the current Warcraft map."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
import os
from pathlib import Path
import sys
from typing import Final, assert_never, override

from .cli_options import CliOptions, run_cli
from .current_map_discovery import locate_current_map
from .current_map_models import EvidenceKind, MapCandidate, ResolutionStatus
from .current_map_snapshot import (
    CurrentMapSnapshotError,
    cleanup_current_map_snapshot,
    cleanup_stale_current_map_snapshots,
    create_current_map_snapshot,
)
from .presentation_safety import format_user_exception, single_line_text


_ACCEPT_OPTION: Final = "--accept-suggestion"
_ROOT_OPTION: Final = "--root"
_FORWARDED_OPTIONS: Final = frozenset(
    {"--listfile", "--game-data", "--author-bundle", "--pack"}
)
_MAX_CANDIDATE_LINES: Final = 8
_MAX_CANDIDATE_PATH_CHARS: Final = 512
_MAX_DIAGNOSTIC_LINE_CHARS: Final = 768


@dataclass(frozen=True, slots=True)
class CurrentMapCliOptions:
    """Parsed discovery policy plus options forwarded to the existing map CLI."""

    roots: tuple[Path, ...] = ()
    accept_suggestion: bool = False
    map_options: CliOptions = field(default_factory=lambda: CliOptions(""))


@dataclass(frozen=True, slots=True)
class CurrentMapCliOptionError(ValueError):
    """Stable failure while parsing the `current` subcommand."""

    detail: str

    @override
    def __str__(self) -> str:
        return single_line_text(self.detail)


def parse_current_map_cli_options(argv: Sequence[str]) -> CurrentMapCliOptions:
    """Parse arguments following the `current` subcommand."""
    roots: list[Path] = []
    values: dict[str, str] = {}
    accept_suggestion = False
    index = 0
    while index < len(argv):
        option = argv[index]
        if option == _ACCEPT_OPTION:
            if accept_suggestion:
                raise CurrentMapCliOptionError(f"参数不能重复：{option}")
            accept_suggestion = True
            index += 1
            continue
        if option != _ROOT_OPTION and option not in _FORWARDED_OPTIONS:
            raise CurrentMapCliOptionError(f"不支持的参数：{option}")
        if option in values:
            raise CurrentMapCliOptionError(f"参数不能重复：{option}")
        value_index = index + 1
        if value_index >= len(argv) or not argv[value_index] or argv[value_index].startswith("--"):
            raise CurrentMapCliOptionError(f"参数缺少路径值：{option}")
        value = argv[value_index]
        if option == _ROOT_OPTION:
            roots.append(Path(value))
        else:
            values[option] = value
        index += 2
    return CurrentMapCliOptions(
        roots=tuple(roots),
        accept_suggestion=accept_suggestion,
        map_options=CliOptions(
            map_path="",
            listfile_path=values.get("--listfile"),
            game_data_path=values.get("--game-data"),
            pack_dir=values.get("--pack"),
            author_bundle_path=values.get("--author-bundle"),
        ),
    )


def run_current_map_cli(options: CurrentMapCliOptions) -> int:
    """Locate one authorized candidate, snapshot it, and reuse the map CLI."""
    cleanup_stale_current_map_snapshots()
    resolution = locate_current_map(options.roots)
    match resolution.status:
        case ResolutionStatus.FOUND:
            if len(resolution.candidates) != 1:
                if resolution.candidates:
                    _print_candidates("直接证据结果不唯一，不能自动选择。", resolution.candidates)
                    return 3
                print("当前地图定位结果不完整，未创建快照。", file=sys.stderr)
                return 2
            return _run_candidate(
                resolution.candidates[0],
                options,
                "已根据直接证据定位当前地图",
            )
        case ResolutionStatus.AMBIGUOUS:
            _print_candidates("发现多个直接证据候选，不能自动选择。", resolution.candidates)
            return 3
        case ResolutionStatus.SUGGESTED:
            if len(resolution.candidates) != 1:
                _print_candidates("提示候选不唯一，不能自动选择。", resolution.candidates)
                return 3 if resolution.candidates else 2
            if not options.accept_suggestion:
                _print_candidates(
                    "仅发现提示证据；确认路径后请添加 --accept-suggestion。",
                    resolution.candidates,
                )
                return 3
            return _run_candidate(
                resolution.candidates[0],
                options,
                "已接受单一提示候选",
            )
        case ResolutionStatus.NOT_FOUND:
            print("未找到正在使用的 Warcraft III 地图。", file=sys.stderr)
            return 2
        case ResolutionStatus.UNAVAILABLE:
            print("当前平台无法可靠探测正在使用的 Warcraft III 地图。", file=sys.stderr)
            return 2
        case unreachable:
            assert_never(unreachable)


def _run_candidate(
    candidate: MapCandidate,
    options: CurrentMapCliOptions,
    selection_message: str,
) -> int:
    print(
        single_line_text(
            f"{selection_message}：{_candidate_text(candidate)}",
            max_chars=_MAX_DIAGNOSTIC_LINE_CHARS,
        ),
        file=sys.stderr,
    )
    try:
        snapshot = create_current_map_snapshot(candidate.path)
    except CurrentMapSnapshotError as exc:
        error = format_user_exception(exc, paths=(os.fspath(candidate.path),))
        print(f"无法创建当前地图快照：{error}", file=sys.stderr)
        return 2
    try:
        delegated = replace(options.map_options, map_path=os.fspath(snapshot.path))
        return run_cli(delegated)
    finally:
        cleanup_current_map_snapshot(snapshot)


def _print_candidates(header: str, candidates: tuple[MapCandidate, ...]) -> None:
    print(single_line_text(header), file=sys.stderr)
    for candidate in candidates[:_MAX_CANDIDATE_LINES]:
        print(f"- {_candidate_text(candidate)}", file=sys.stderr)
    omitted = len(candidates) - _MAX_CANDIDATE_LINES
    if omitted > 0:
        print(f"- 另有 {omitted} 个候选未显示。", file=sys.stderr)


def _candidate_text(candidate: MapCandidate) -> str:
    path = single_line_text(
        os.fspath(candidate.path),
        max_chars=_MAX_CANDIDATE_PATH_CHARS,
    )
    labels: list[str] = []
    for evidence in candidate.evidence:
        label = _evidence_label(evidence.kind)
        if label not in labels:
            labels.append(label)
    sources = "、".join(labels) if labels else "未提供"
    return single_line_text(
        f"{path}（来源：{sources}）",
        max_chars=_MAX_DIAGNOSTIC_LINE_CHARS,
    )


def _evidence_label(kind: EvidenceKind) -> str:
    match kind:
        case EvidenceKind.DIRECT_OPEN:
            return "游戏进程打开文件"
        case EvidenceKind.EXPLICIT_ARGUMENT:
            return "游戏启动参数"
        case EvidenceKind.LIVE_FILE:
            return "文件使用中"
        case EvidenceKind.WGC_REFERENCE:
            return "WGC 配置引用"
        case EvidenceKind.RECENT_CACHE:
            return "最近地图缓存"
        case EvidenceKind.GAME_LOG:
            return "游戏日志"
        case unreachable:
            assert_never(unreachable)
