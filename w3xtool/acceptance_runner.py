"""Repeatable source and packaged-EXE acceptance workflows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import json
from pathlib import Path
import platform
import sys
from time import perf_counter
from typing import override

from .api import load_map
from .casclib_api import MAX_CASC_FILE_SIZE
from .casclib_enumeration import CascNameType
from .casclib_source import CascLibDataSource
from .knowledge_pack import write_knowledge_pack


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
class AcceptanceReport:
    created_at: str
    platform: str
    python: str
    executable: str
    checks: tuple[AcceptanceCheck, ...]

    @property
    def overall_status(self) -> AcceptanceStatus:
        return (
            AcceptanceStatus.FAIL
            if any(check.status is AcceptanceStatus.FAIL for check in self.checks)
            else AcceptanceStatus.PASS
        )

    def to_json(self) -> str:
        """Serialize stable machine-readable acceptance evidence."""
        payload = {
            "created_at": self.created_at,
            "platform": self.platform,
            "python": self.python,
            "executable": self.executable,
            "overall_status": self.overall_status.value,
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
    """Run independent acceptance lanes and preserve every result."""
    config.output_dir.mkdir(parents=True, exist_ok=True)
    checks: list[AcceptanceCheck] = []
    checks.append(_platform_check(config.require_windows))
    checks.append(_run_check("map_load", lambda: _check_map(config.map_path)))
    checks.append(_campaign_check(config.campaign_path))
    checks.append(_run_check(
        "knowledge_pack_export",
        lambda: _check_knowledge_pack(config.map_path, config.output_dir),
    ))
    checks.append(_run_check(
        "repeat_load",
        lambda: _check_repeat_load(config.map_path, config.repeat_count),
    ))
    checks.append(_casc_check(config.war3_dir))
    checks.append(_gui_check(config))
    return AcceptanceReport(
        created_at=datetime.now(UTC).isoformat(),
        platform=platform.platform(),
        python=sys.version.split()[0],
        executable=sys.executable,
        checks=tuple(checks),
    )


def write_acceptance_report(report: AcceptanceReport, path: Path) -> None:
    """Write acceptance JSON after all lanes have completed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(report.to_json(), encoding="utf-8")


def _run_check(name: str, action: Callable[[], str]) -> AcceptanceCheck:
    started = perf_counter()
    try:
        detail = action()
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK - acceptance boundary records each lane.
        return AcceptanceCheck(name, AcceptanceStatus.FAIL, f"{type(exc).__name__}: {exc}", _elapsed(started))
    return AcceptanceCheck(name, AcceptanceStatus.PASS, detail, _elapsed(started))


def _platform_check(require_windows: bool) -> AcceptanceCheck:
    if not require_windows:
        return AcceptanceCheck("windows_runtime", AcceptanceStatus.SKIP, "未要求 Windows", 0)
    if sys.platform != "win32":
        return AcceptanceCheck("windows_runtime", AcceptanceStatus.FAIL, f"当前平台：{sys.platform}", 0)
    return AcceptanceCheck("windows_runtime", AcceptanceStatus.PASS, platform.platform(), 0)


def _check_map(path: Path) -> str:
    md = load_map(str(path))
    if not md.scripts:
        raise AcceptanceCheckError("地图未加载出脚本")
    return f"{md.name}; files={len(md.all_files)}; objects={sum(md.category_counts().values())}"


def _campaign_check(path: Path | None) -> AcceptanceCheck:
    if path is None:
        return AcceptanceCheck("campaign_switch", AcceptanceStatus.SKIP, "未提供战役样本", 0)
    return _run_check("campaign_switch", lambda: _check_campaign(path))


def _check_campaign(path: Path) -> str:
    md = load_map(str(path))
    if not md.sub_maps:
        raise AcceptanceCheckError("战役没有可切换子图")
    names = ", ".join(sub.name for sub in md.sub_maps)
    return f"shared={sum(md.category_counts().values())}; submaps={len(md.sub_maps)}; {names}"


def _check_knowledge_pack(map_path: Path, output_dir: Path) -> str:
    md = load_map(str(map_path))
    pack_dir = output_dir / "knowledge-pack"
    count = write_knowledge_pack(md, str(pack_dir))
    manifest = pack_dir / "资料包目录.tsv"
    if count < 1 or not manifest.is_file():
        raise AcceptanceCheckError("资料包没有生成 资料包目录.tsv")
    return f"files={count}; path={pack_dir}"


def _check_repeat_load(map_path: Path, repeat_count: int) -> str:
    if repeat_count < 1:
        raise AcceptanceCheckError("重复次数必须大于 0")
    totals: list[int] = []
    for _index in range(repeat_count):
        md = load_map(str(map_path))
        totals.append(len(md.all_files) + len(md.scripts))
    if len(set(totals)) != 1:
        raise AcceptanceCheckError(f"重复加载结果不一致：{totals}")
    return f"repeat={repeat_count}; stable_total={totals[0]}"


def _casc_check(war3_dir: Path | None) -> AcceptanceCheck:
    if war3_dir is None:
        return AcceptanceCheck("real_windows_casc", AcceptanceStatus.SKIP, "未提供 W3XRAY_WAR3_DIR", 0)
    return _run_check("real_windows_casc", lambda: _check_casc(war3_dir))


def _check_casc(war3_dir: Path) -> str:
    names = (
        "UI/TriggerData.txt",
        "UI/TriggerStrings.txt",
        "ReplaceableTextures/CommandButtons/BTNSelectHeroOn.blp",
    )
    with CascLibDataSource(str(war3_dir)) as source:
        sizes = [len(source.read_file(name)) for name in names]
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
                    and entry.size <= MAX_CASC_FILE_SIZE
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
        f"resources={sizes}; first_root_entry={first.name}; type={first.name_type.name}; "
        f"unknown_root_entry={unknown.name}; unknown_type={unknown.name_type.name}"
    )


def _gui_check(config: AcceptanceConfig) -> AcceptanceCheck:
    if not config.run_gui:
        return AcceptanceCheck("gui_tabs", AcceptanceStatus.SKIP, "--no-gui", 0)
    return _run_check("gui_tabs", lambda: _run_gui(config.map_path))


def _run_gui(map_path: Path) -> str:
    from .gui_acceptance import run_gui_acceptance

    return run_gui_acceptance(map_path)


def _elapsed(started: float) -> int:
    return round((perf_counter() - started) * 1000)
