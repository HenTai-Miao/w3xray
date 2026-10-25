"""Complete spatial queries with precise data independent of rendered text."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Protocol, TypedDict, runtime_checkable

from .pack_query_regions import NearRegion, containing_regions
from .static_numbers import format_number
from .script_sources import AnalysisScriptSource


type Point = tuple[float, float]


class NearEntry(TypedDict):
    kind: str
    name: str
    code: str
    count: int
    x: float
    y: float
    dist: float
    drops: str | None
    sell: str | None
    detail: str
    positions: tuple[Point, ...]


@dataclass(frozen=True, slots=True)
class SpatialQueryResult:
    lines: tuple[str, ...]
    entries: tuple[NearEntry, ...] = ()
    regions: tuple[NearRegion, ...] = ()
    regions_total: int = 0


class SpatialSources(Protocol):
    def _read_rows(self, pack: Path, relative: str) -> list[list[str]]: ...
    def load_items(self, pack: Path) -> dict[str, tuple[str, str]]: ...
    def load_units(self, pack: Path) -> dict[str, str]: ...
    def load_destructables(self, pack: Path) -> dict[str, str]: ...
    def load_placements(self, pack: Path) -> list[tuple[str, float, float, str]]: ...
    def load_script_sources(self, pack: Path) -> tuple[tuple[str, str], ...]: ...
    def load_script_contexts(self, pack: Path) -> tuple[AnalysisScriptSource, ...]: ...
    def _source_drop_map(self, pack: Path) -> dict[str, str]: ...
    def _source_shop_map(self, pack: Path) -> dict[str, str]: ...


@runtime_checkable
class PlacementDiagnostics(Protocol):
    def load_placement_diagnostics(self, pack: Path) -> list[str]: ...


def preplaced_objects(
    pack: Path, sources: SpatialSources
) -> Iterator[tuple[str, str, str, Point]]:
    """Share complete, header-driven placement reads across where and near."""
    item_names = {
        code: name for code, (name, _description) in sources.load_items(pack).items()
    }
    for relative, kind in (("预放置单位.tsv", "单位"), ("预放置装饰物.tsv", "装饰")):
        yield from _placed_rows(pack, relative, kind, item_names, sources)


def _placed_rows(
    pack: Path,
    relative: str,
    default_kind: str,
    item_names: dict[str, str],
    sources: SpatialSources,
) -> Iterator[tuple[str, str, str, Point]]:
    rows = sources._read_rows(pack, relative)
    if not rows:
        return
    try:
        x_column, y_column = rows[0].index("X"), rows[0].index("Y")
    except ValueError:
        x_column, y_column = 3, 4
    for row in rows[1:]:
        if len(row) <= max(x_column, y_column, 2):
            continue
        code, name = row[1], row[2] or row[1]
        kind = "物品" if default_kind == "单位" and code in item_names else default_kind
        if kind == "物品" and name == code:
            name = item_names[code]
        try:
            point = (float(row[x_column]), float(row[y_column]))
        except ValueError:
            continue
        if all(math.isfinite(value) for value in point):
            yield kind, code, name, point


def cluster_points(
    points: Sequence[Point], radius: float = 1200.0
) -> Iterator[tuple[Point, ...]]:
    """Keep greedy seed grouping while visiting only neighboring spatial cells."""
    if not math.isfinite(radius) or radius <= 0:
        raise ValueError("spatial cell radius must be finite and positive")
    buckets: dict[tuple[int, int], dict[int, Point]] = {}
    for index, (x, y) in enumerate(points):
        buckets.setdefault((math.floor(x / radius), math.floor(y / radius)), {})[
            index
        ] = (x, y)
    used: set[int] = set()
    for index, seed in enumerate(points):
        if index in used:
            continue
        cx, cy = math.floor(seed[0] / radius), math.floor(seed[1] / radius)
        members: dict[int, Point] = {}
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                cell = buckets.get((cx + dx, cy + dy), {})
                members.update(
                    (i, p)
                    for i, p in cell.items()
                    if math.hypot(p[0] - seed[0], p[1] - seed[1]) < radius
                )
        ordered = tuple(members[i] for i in sorted(members))
        for i, (x, y) in members.items():
            used.add(i)
            key = (math.floor(x / radius), math.floor(y / radius))
            del buckets[key][i]
            if not buckets[key]:
                del buckets[key]
        yield ordered


def _center(points: Sequence[Point]) -> Point:
    count = len(points)
    if count == 1:
        return points[0]

    def mean(axis: int) -> float:
        try:
            return math.fsum(point[axis] for point in points) / count
        except OverflowError:
            return math.fsum(point[axis] / count for point in points)

    return mean(0), mean(1)


class _Output:
    def __init__(self, x: float, y: float, radius: float) -> None:
        self.x = x
        self.y = y
        self.lines: list[str] = [
            f"== 坐标 ({format_number(x)}, {format_number(y)}) 半径 {format_number(radius)} =="
        ]
        self.entries: list[NearEntry] = []
        self.regions: list[NearRegion] = []
        self.regions_total = 0

    def distance(self, point: Point) -> float:
        return math.hypot(point[0] - self.x, point[1] - self.y)

    def add(
        self,
        kind: str,
        name: str,
        code: str,
        points: tuple[Point, ...],
        *,
        drops: str | None = None,
        sell: str | None = None,
    ) -> None:
        x, y = _center(points)
        distance = self.distance((x, y))
        suffix = (f"  掉: {drops}" if drops else "") + (f"  卖: {sell}" if sell else "")
        line = f"  {kind}: {name} [{code}] ×{len(points)} @({format_number(x)},{format_number(y)}) 距{format_number(distance)}{suffix}"
        self.lines.append(line)
        self.entries.append(
            NearEntry(
                kind=kind,
                name=name,
                code=code,
                count=len(points),
                x=x,
                y=y,
                dist=distance,
                drops=drops,
                sell=sell,
                detail=line.strip(),
                positions=points,
            )
        )

    def limit_note(self, total: int, limit: int) -> None:
        if limit and total > limit:
            self.lines.append(
                f"  (已达 --limit {limit}, 其余 {total - limit} 条未显示——去掉 --limit 看全量)"
            )

    def result(self) -> SpatialQueryResult:
        if any(entry["count"] > 1 for entry in self.entries):
            self.lines.insert(
                1, "  聚合行坐标为组中心；--json 的 positions 保留每个实例的完整坐标。"
            )
        return SpatialQueryResult(
            tuple(self.lines),
            tuple(self.entries),
            tuple(self.regions),
            self.regions_total,
        )


def query_near(
    pack: Path, query: str, limit: int, sources: SpatialSources
) -> SpatialQueryResult:
    """Read all spatial sources, preserving every visible placement in JSON."""
    parts = query.split()
    kind_filter = ""
    if "--kind" in parts:
        index = parts.index("--kind")
        if index + 1 >= len(parts):
            return SpatialQueryResult(
                ("未知 --kind: 需要一个值 (单位/装饰/物品/脚本)",)
            )
        kind_filter = parts[index + 1]
        parts = parts[:index] + parts[index + 2 :]
    if len(parts) not in (2, 3):
        return SpatialQueryResult(
            (
                "用法: near <x> <y> [radius=3000] [--kind 单位/装饰/物品/脚本]",
                "  （坐标来源: live 探针输出尾部 JSON 的 x/y, 或地图编辑器; 查脚底有什么/附近谁在掉什么）",
            )
        )
    try:
        x, y = float(parts[0]), float(parts[1])
        radius = float(parts[2]) if len(parts) == 3 else 3000.0
    except ValueError:
        return SpatialQueryResult(("坐标与半径必须是数字: near <x> <y> [radius]",))
    if not all(math.isfinite(value) for value in (x, y, radius)) or radius < 0:
        return SpatialQueryResult(
            ("坐标与半径必须是有限数字，且半径必须非负: near <x> <y> [radius]",)
        )
    if kind_filter not in ("", "单位", "装饰", "物品", "脚本"):
        return SpatialQueryResult(
            (f"未知 --kind {kind_filter} (可选: 单位/装饰/物品/脚本; 缺省=全部)",)
        )
    output = _Output(x, y, radius)
    drops, shops = sources._source_drop_map(pack), sources._source_shop_map(pack)
    item_names = {
        code: name for code, (name, _description) in sources.load_items(pack).items()
    }
    for relative, default_kind in (
        ("预放置单位.tsv", "单位"),
        ("预放置装饰物.tsv", "装饰"),
    ):
        if kind_filter == "脚本" or (
            default_kind == "装饰" and kind_filter not in ("", "装饰")
        ):
            continue
        grouped: dict[tuple[str, str, str], list[Point]] = {}
        nearest: dict[str, list[tuple[float, str]]] = {}
        for kind, code, name, point in _placed_rows(
            pack, relative, default_kind, item_names, sources
        ):
            if kind_filter and kind_filter != kind:
                continue
            distance = output.distance(point)
            nearest.setdefault(kind, []).append((distance, f"{name} [{code}]"))
            if distance <= radius:
                grouped.setdefault((kind, code, name), []).append(point)
        hits: list[tuple[float, str, str, str, tuple[Point, ...]]] = []
        for (kind, code, name), points in grouped.items():
            groups = cluster_points(points) if kind == "装饰" else (tuple(points),)
            for group in groups:
                hits.append((output.distance(_center(group)), kind, code, name, group))
        hits.sort(key=lambda hit: (hit[0], hit[1], hit[2], hit[3]))
        for _distance, kind, code, name, points in hits[:limit] if limit else hits:
            output.add(
                "装饰群" if kind == "装饰" else kind,
                name,
                code,
                points,
                drops=drops.get(code),
                sell=shops.get(code),
            )
        output.limit_note(len(hits), limit)
        found_kinds = {kind for kind, _code, _name in grouped}
        for kind, candidates in nearest.items():
            if kind in found_kinds:
                continue
            candidates.sort()
            for distance, label in candidates[:limit] if limit else candidates:
                output.lines.append(
                    f"  (半径外最近{kind}: {label} 距{format_number(distance)})"
                )
            output.limit_note(len(candidates), limit)
    placements = sources.load_placements(pack)
    for placement_kind, filter_kind, label, names in (
        ("item", "物品", "脚本物品", item_names),
        ("destructable", "装饰", "脚本可破坏物", sources.load_destructables(pack)),
        ("unit", "单位", "脚本单位", sources.load_units(pack)),
    ):
        if kind_filter not in ("", "脚本", filter_kind):
            continue
        grouped_script: dict[tuple[str, float, float], list[Point]] = {}
        for code, px, py, kind in placements:
            if kind == placement_kind and output.distance((px, py)) <= radius:
                grouped_script.setdefault((code, px, py), []).append((px, py))
        ordered = sorted(
            grouped_script.items(),
            key=lambda row: (output.distance((row[0][1], row[0][2])), row[0]),
        )
        for (code, _px, _py), points in ordered[:limit] if limit else ordered:
            output.add(
                label,
                names.get(code, code),
                code,
                tuple(points),
                drops=drops.get(code) if placement_kind != "item" else None,
                sell=shops.get(code) if placement_kind == "unit" else None,
            )
        output.limit_note(len(ordered), limit)
    if kind_filter in ("", "脚本", "单位"):
        matches = containing_regions(sources.load_script_contexts(pack), x, y)
        output.regions_total = len(matches)
        output.regions.extend(matches[:limit] if limit else matches)
        if output.regions:
            names = dict.fromkeys(region["name"] for region in output.regions)
            output.lines.append("  所在矩形: " + ", ".join(names))
            for region in output.regions:
                left, bottom, right, top = map(format_number, region["bounds"])
                output.lines.append(
                    f"    区域 {region['name']}: ({left},{bottom}) .. ({right},{top}) — {region['source']}:{region['line']} / 偏移{region['offset']}"
                )
                output.lines.append("      原文: " + region["expression"])
            output.limit_note(len(matches), limit)
    if len(output.lines) == 1:
        detail = f" {kind_filter} 类命中" if kind_filter else "预放置/脚本内容"
        output.lines = [
            f"坐标 ({format_number(x)},{format_number(y)}) 半径 {format_number(radius)} 内无{detail}。",
            "  （核对坐标; 可去掉 --kind 看全部类，或加大半径参数: near <x> <y> <radius>）",
        ]
    if isinstance(sources, PlacementDiagnostics) and (
        notes := sources.load_placement_diagnostics(pack)
    ):
        output.lines.append(
            f"  ⚠ 另有 {len(notes)} 条脚本点位诊断（对象、坐标或来源未确认）；上述结果仅含已确认点位。"
        )
        output.lines.extend(notes)
    return output.result()
