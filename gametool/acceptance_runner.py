"""Repeatable source and packaged-EXE acceptance workflows."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import json
import hashlib
import os
from pathlib import Path
import platform
import sys
from time import perf_counter
from typing import override

from .acceptance_batch import check_batch_publication
from .acceptance_queries import check_query_workflow
from .api import load_map
from .casclib_api import (
    CascFileNotFoundError,
    CtypesCascLibApi,
    MAX_CASC_FILE_SIZE,
    default_dll_path,
)
from .casclib_enumeration import CascNameType
from .casclib_source import CascLibDataSource
from .knowledge_pack import write_knowledge_pack_report
from .knowledge_results import KnowledgeWriteStatus
from .live_report_io import _parents, validate_report_destination, write_report_bytes
from .windows_output_paths import native_output_path, validate_output_root


class AcceptanceStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class AcceptanceCheck:
    name: str
    status: AcceptanceStatus
    detail: str
    duration_ms: int


@dataclass(frozen=True, slots=True)
class AcceptanceNotRequested:
    name: str
    reason: str


@dataclass(frozen=True, slots=True)
class AcceptanceReport:
    created_at: str
    platform: str
    python: str
    executable: str
    checks: tuple[AcceptanceCheck, ...]
    requested_checks: tuple[str, ...] | None = None
    not_requested: tuple[AcceptanceNotRequested, ...] = ()

    def __post_init__(self) -> None:
        # Legacy hand-built reports treated their recorded checks as requested.
        # Preserve their statuses; an explicit empty plan remains incomplete.
        if self.requested_checks is None:
            object.__setattr__(self, "requested_checks", self.executed_checks)

    @property
    def executed_checks(self) -> tuple[str, ...]:
        return tuple(check.name for check in self.checks)

    @property
    def requested_coverage_complete(self) -> bool:
        requested = self.requested_checks or ()
        executed = self.executed_checks
        unrequested = tuple(check.name for check in self.not_requested)
        return (
            bool(requested)
            and len(requested) == len(set(requested))
            and len(executed) == len(set(executed))
            and len(unrequested) == len(set(unrequested))
            and set(requested) == set(executed)
            and not set(requested).intersection(unrequested)
            and all(check.status is AcceptanceStatus.PASS for check in self.checks)
        )

    @property
    def real_casc_verified(self) -> bool:
        checks = tuple(
            check for check in self.checks if check.name == "real_windows_casc"
        )
        return (
            "real_windows_casc" in (self.requested_checks or ())
            and not any(
                check.name == "real_windows_casc" for check in self.not_requested
            )
            and len(checks) == 1
            and checks[0].status is AcceptanceStatus.PASS
        )

    @property
    def overall_status(self) -> AcceptanceStatus:
        return (
            AcceptanceStatus.PASS
            if self.requested_coverage_complete
            else AcceptanceStatus.FAIL
        )

    def to_json(self) -> str:
        """Serialize acceptance coverage of the requested checks only."""
        payload = {
            "created_at": self.created_at,
            "platform": self.platform,
            "python": self.python,
            "executable": self.executable,
            "overall_status": self.overall_status.value,
            "coverage_scope": "requested",
            "requested_checks": list(self.requested_checks or ()),
            "executed_checks": list(self.executed_checks),
            "not_requested": [
                {"name": check.name, "reason": check.reason}
                for check in self.not_requested
            ],
            "requested_coverage_complete": self.requested_coverage_complete,
            "coverage_complete": self.requested_coverage_complete,
            "real_casc_verified": self.real_casc_verified,
            "skipped_checks": [
                check.name
                for check in self.checks
                if check.status is AcceptanceStatus.SKIP
            ],
            "checks": [
                {
                    "name": check.name,
                    "status": check.status.value,
                    "detail": check.detail,
                    "duration_ms": check.duration_ms,
                }
                for check in self.checks
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


@dataclass(frozen=True, slots=True)
class AcceptanceConfig:
    map_path: Path
    campaign_path: Path | None
    war3_dir: Path | None
    output_dir: Path
    repeat_count: int = 5
    run_gui: bool = True
    require_windows: bool = False


@dataclass(frozen=True, slots=True)
class AcceptanceCheckError(RuntimeError):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


def run_acceptance(config: AcceptanceConfig) -> AcceptanceReport:
    """Plan the requested acceptance lanes and preserve every executed result."""
    lanes: tuple[tuple[str, bool, Callable[[], AcceptanceCheck], str], ...] = (
        (
            "windows_runtime",
            config.require_windows,
            lambda: _platform_check(config.require_windows),
            "未请求 --require-windows",
        ),
        (
            "bundled_casclib",
            config.require_windows,
            lambda: _bundled_casclib_check(config.require_windows),
            "未请求 --require-windows 的捆绑原生库检查",
        ),
        (
            "map_load",
            True,
            lambda: _run_check("map_load", lambda: _check_map(config.map_path)),
            "",
        ),
        (
            "campaign_switch",
            config.campaign_path is not None,
            lambda: _campaign_check(config.campaign_path),
            "未提供 --campaign 战役样本",
        ),
        (
            "knowledge_pack_export",
            True,
            lambda: _run_check(
                "knowledge_pack_export",
                lambda: _check_knowledge_pack(config.map_path, config.output_dir),
            ),
            "",
        ),
        (
            "pack_query_workflow",
            True,
            lambda: _run_check(
                "pack_query_workflow",
                lambda: check_query_workflow(config.output_dir / "knowledge-pack"),
            ),
            "",
        ),
        (
            "batch_publication",
            True,
            lambda: _run_check(
                "batch_publication",
                lambda: check_batch_publication(config.map_path, config.output_dir),
            ),
            "",
        ),
        (
            "repeat_load",
            True,
            lambda: _run_check(
                "repeat_load",
                lambda: _check_repeat_load(config.map_path, config.repeat_count),
            ),
            "",
        ),
        (
            "real_windows_casc",
            config.war3_dir is not None,
            lambda: _casc_check(config.war3_dir),
            "未配置真实 CASC 目录；通过 --war3-dir 或非空 GAMEXRAY_WAR3_DIR 请求；真实 CASC 未验证",
        ),
        (
            "gui_tabs",
            config.run_gui,
            lambda: _gui_check(config),
            "未请求 GUI 验收（run_gui=False / --no-gui）",
        ),
    )
    requested = tuple(name for name, selected, _action, _reason in lanes if selected)
    not_requested = tuple(
        AcceptanceNotRequested(name, reason)
        for name, selected, _action, reason in lanes
        if not selected
    )
    config.output_dir.mkdir(parents=True, exist_ok=True)
    checks = tuple(action() for _name, selected, action, _reason in lanes if selected)
    return AcceptanceReport(
        created_at=datetime.now(UTC).isoformat(),
        platform=platform.platform(),
        python=sys.version.split()[0],
        executable=sys.executable,
        checks=checks,
        requested_checks=requested,
        not_requested=not_requested,
    )


@contextmanager
def _acceptance_report_destination(path: Path) -> Iterator[Path]:
    """Create missing ordinary parents while holding their existing ancestry."""
    validate_output_root(os.fspath(path))
    target = Path(os.path.abspath(path))
    with ExitStack() as held:
        for directory in reversed(target.parents):
            native = Path(native_output_path(str(directory)))
            if not os.path.lexists(native):
                native.mkdir()
            # The leaf is only a probe spelling; _parents never creates it.
            held.enter_context(_parents(native / ".acceptance-parent"))
        _ = validate_report_destination(target)
        yield target


def prepare_acceptance_report(path: Path) -> Path:
    """Reject existing reports, map aliases and unsafe parents before any lane."""
    with _acceptance_report_destination(path) as target:
        return target


def write_acceptance_report(report: AcceptanceReport, path: Path) -> None:
    """Publish a complete new report without replacing any existing asset."""
    with _acceptance_report_destination(path) as target:
        _ = write_report_bytes(target, report.to_json().encode("utf-8"))


def _run_check(name: str, action: Callable[[], str]) -> AcceptanceCheck:
    started = perf_counter()
    try:
        detail = action()
    except Exception as exc:  # BROAD_EXCEPT_OK - acceptance boundary records each lane.
        return AcceptanceCheck(
            name,
            AcceptanceStatus.FAIL,
            f"{type(exc).__name__}: {exc}",
            _elapsed(started),
        )
    return AcceptanceCheck(name, AcceptanceStatus.PASS, detail, _elapsed(started))


def _platform_check(require_windows: bool) -> AcceptanceCheck:
    if not require_windows:
        return AcceptanceCheck(
            "windows_runtime", AcceptanceStatus.SKIP, "未要求 Windows", 0
        )
    if sys.platform != "win32":
        return AcceptanceCheck(
            "windows_runtime", AcceptanceStatus.FAIL, f"当前平台：{sys.platform}", 0
        )
    return AcceptanceCheck(
        "windows_runtime", AcceptanceStatus.PASS, platform.platform(), 0
    )


def _bundled_casclib_check(require_windows: bool) -> AcceptanceCheck:
    if not require_windows:
        return AcceptanceCheck(
            "bundled_casclib", AcceptanceStatus.SKIP, "未要求 Windows", 0
        )
    return _run_check("bundled_casclib", _check_bundled_casclib)


def _check_bundled_casclib() -> str:
    path = default_dll_path()
    _ = CtypesCascLibApi(dll_path=path)
    return f"path={path}; bytes={path.stat().st_size}"


def _check_map(path: Path) -> str:
    md = load_map(str(path))
    try:
        if not md.scripts:
            raise AcceptanceCheckError("地图未加载出脚本")
        return f"{md.name}; files={len(md.all_files)}; objects={sum(md.category_counts().values())}"
    finally:
        md.close()


def _campaign_check(path: Path | None) -> AcceptanceCheck:
    if path is None:
        return AcceptanceCheck(
            "campaign_switch", AcceptanceStatus.SKIP, "未提供战役样本", 0
        )
    return _run_check("campaign_switch", lambda: _check_campaign(path))


def _check_campaign(path: Path) -> str:
    md = load_map(str(path))
    try:
        if not md.sub_maps:
            raise AcceptanceCheckError("战役没有可切换子图")
        names = ", ".join(sub.name for sub in md.sub_maps)
        return f"shared={sum(md.category_counts().values())}; submaps={len(md.sub_maps)}; {names}"
    finally:
        md.close()


def _check_knowledge_pack(map_path: Path, output_dir: Path) -> str:
    md = load_map(str(map_path))
    try:
        pack_dir = output_dir / "knowledge-pack"
        report = write_knowledge_pack_report(md, str(pack_dir))
        manifest = pack_dir / "资料包目录.tsv"
        if not manifest.is_file():
            raise AcceptanceCheckError("资料包没有生成 资料包目录.tsv")
        if report.status is not KnowledgeWriteStatus.COMPLETE:
            raise AcceptanceCheckError(
                f"资料包部分或全部失败：成功 {report.written_count}，失败 {report.failed_count}",
            )
        return f"files={report.written_count}; path={pack_dir}"
    finally:
        md.close()


def _check_repeat_load(map_path: Path, repeat_count: int) -> str:
    if repeat_count < 1:
        raise AcceptanceCheckError("重复次数必须大于 0")
    totals: list[int] = []
    snapshots: list[str] = []
    for _index in range(repeat_count):
        md = load_map(str(map_path))
        try:
            totals.append(len(md.all_files) + len(md.scripts))
            snapshot = json.dumps(
                {
                    "files": md.all_files,
                    "scripts": md.scripts,
                    "objects": {
                        category: [
                            (obj.obj_id, obj.name, obj.field_values, obj.fields)
                            for obj in objects
                        ]
                        for category, objects in md.objects.items()
                    },
                },
                ensure_ascii=True,
                sort_keys=True,
            )
            snapshots.append(hashlib.sha256(snapshot.encode("utf-8")).hexdigest())
        finally:
            md.close()
    if len(set(totals)) != 1 or len(set(snapshots)) != 1:
        raise AcceptanceCheckError(f"重复加载结果不一致：{totals}")
    return f"repeat={repeat_count}; stable_total={totals[0]}"


def _casc_check(war3_dir: Path | None) -> AcceptanceCheck:
    if war3_dir is None:
        return AcceptanceCheck(
            "real_windows_casc", AcceptanceStatus.SKIP, "未提供 GAMEXRAY_WAR3_DIR", 0
        )
    return _run_check("real_windows_casc", lambda: _check_casc(war3_dir))


def _check_casc(war3_dir: Path) -> str:
    names = (
        "UI/TriggerData.txt",
        "UI/TriggerStrings.txt",
        "ReplaceableTextures/CommandButtons/BTNSelectHeroOn.blp",
    )
    with CascLibDataSource(str(war3_dir)) as source:
        # 官方客户端可按需精简 CASC 内容（如 3.0 模块化安装），探测文件集
        # 只需命中其一即可证明真实读取链路；缺失项如实写入证据串。
        found: list[tuple[str, int]] = []
        missing: list[str] = []
        for name in names:
            try:
                found.append((name, len(source.read_file(name))))
            except CascFileNotFoundError:
                missing.append(name)
        if not found:
            raise AcceptanceCheckError(
                "真实安装 CASC 中找不到任何探测文件：" + "、".join(names)
            )
        entries = source.iter_entries()
        first = None
        unknown = None
        try:
            for entry in entries:
                if first is None:
                    first = entry
                if (
                    entry.name_type is not CascNameType.FULL
                    and entry.is_local
                    and entry.size is not None
                    and (MAX_CASC_FILE_SIZE is None or entry.size <= MAX_CASC_FILE_SIZE)
                ):
                    unknown = entry
                    break
        finally:
            entries.close()
        if first is None:
            raise AcceptanceCheckError("CASC Root 枚举为空")
        if unknown is None:
            raise AcceptanceCheckError("CASC Root 未找到可重开的未知路径条目")
        unknown_payload = source.read_file(unknown.read_name)
        if len(unknown_payload) != unknown.size:
            raise AcceptanceCheckError("未知路径条目重开后大小不一致")
    return (
        f"resources={found}; missing={missing or '无'}; "
        f"first_root_entry={first.name}; type={first.name_type.name}; "
        f"unknown_root_entry={unknown.name}; unknown_type={unknown.name_type.name}"
    )


def _gui_check(config: AcceptanceConfig) -> AcceptanceCheck:
    if not config.run_gui:
        return AcceptanceCheck("gui_tabs", AcceptanceStatus.SKIP, "--no-gui", 0)
    return _run_check(
        "gui_tabs",
        lambda: _run_gui(
            config.map_path, config.output_dir / "knowledge-pack", config.campaign_path
        ),
    )


def _run_gui(
    map_path: Path, pack_path: Path | None = None, campaign_path: Path | None = None
) -> str:
    from .gui_acceptance import run_gui_acceptance

    return run_gui_acceptance(map_path, pack_path, campaign_path)


def _elapsed(started: float) -> int:
    return round((perf_counter() - started) * 1000)
