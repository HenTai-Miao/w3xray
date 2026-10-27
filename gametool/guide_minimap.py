"""guide --minimap-marks: 把商店与自定义点位标注到小地图导出 PNG。

数据全部来自地图证据, 不用猜测来源:
- 底图: war3mapMap.blp (gametool.blp 解码, 覆盖 BLP1-JPEG 共享表拼接与 CMYK 变体);
- 坐标范围: w3i 镜头边界 (8f 前 4 个 = left,bottom,right,top) 与镜头补足 (4i)
  相加减推出可玩区, 小地图纹理按可玩区宽高比居中裁掉留边;
- 商店: 对象表单位行带 usei (Sellitems) 货架, 位置取 war3mapUnits.doo 放置坐标;
- 自定义追加点: --minimap-marks 的值以 .json 结尾时读 [[名称, X, Y], ...] (世界坐标)。
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

__all__ = (
    "GuideMinimapError",
    "crop_to_playable",
    "extra_marks_from_json",
    "playable_bounds",
    "render_marks",
    "shop_marks",
    "world_to_pixel",
    "write_guide_minimap",
)

if TYPE_CHECKING:
    from PIL.Image import Image

    from .map_data import MapData

from .placement_positions import (
    Point,
    PositionGroups,
    script_position_groups,
    unit_position_groups,
)
from .static_numbers import format_number
from .presentation_safety import single_line_text
from .placement_identity import PlacementObjectIndex
from .item_relation_field_variants import relation_field_variants, split_relation_codes
from .item_relation_models import ItemRelationKind
from .safe_output import write_chunks_safely
from .safe_output_models import SafeWriteStatus

# 点位 = (名称, 世界X, 世界Y)
Mark = tuple[str, float, float]
Bounds = tuple[float, float, float, float]


class GuideMinimapError(ValueError):
    """小地图标注图生成失败, message 面向命令行用户。"""


def script_unit_positions(md: MapData) -> PositionGroups:
    """Return every distinct static creation location for each unit rawcode."""
    return script_position_groups(md)


def playable_bounds(md: MapData) -> Bounds | None:
    """w3i 镜头边界 ± 镜头补足 → 可玩区 (left, bottom, right, top); 无证据返回 None。"""
    info = md.w3i
    if info is None or len(info.camera_bounds) < 4 or len(info.camera_margins) < 4:
        return None
    left, bottom, right, top = info.camera_bounds[:4]
    margin_left, margin_bottom, margin_right, margin_top = info.camera_margins[:4]
    playable: Bounds = (
        left + margin_left,
        bottom + margin_bottom,
        right - margin_right,
        top - margin_top,
    )
    if (
        not all(math.isfinite(value) for value in playable)
        or not math.isfinite(playable[2] - playable[0])
        or not math.isfinite(playable[3] - playable[1])
        or playable[2] - playable[0] <= 0
        or playable[3] - playable[1] <= 0
    ):
        return None
    return playable


def world_to_pixel(
    x: float, y: float, bounds: Bounds, w: float, h: float
) -> tuple[float, float]:
    """世界坐标 → 像素 (上=北, Y 轴向北增大)。"""
    left, bottom, right, top = bounds
    return (
        (x - left) / (right - left) * w,
        (top - y) / (top - bottom) * h,
    )


def crop_to_playable(img: Image, bounds: Bounds) -> Image:
    """小地图纹理把可玩区按比例居中装箱; 裁掉留边只留内容带 (方形图 + 3:2 图 → 裁上下)。"""
    width_span = bounds[2] - bounds[0]
    height_span = bounds[3] - bounds[1]
    aspect = width_span / height_span
    img_aspect = img.width / img.height
    if abs(img_aspect - aspect) <= 0.01:
        return img
    band_h = max(1, round(img.width / aspect))
    if band_h < img.height:
        top = (img.height - band_h) // 2
        return img.crop((0, top, img.width, top + band_h))
    band_w = max(1, round(img.height * aspect))
    if band_w < img.width:
        left = (img.width - band_w) // 2
        return img.crop((left, 0, left + band_w, img.height))
    return img


def shop_marks(
    md: MapData, positions: Mapping[str, Point | tuple[Point, ...]]
) -> tuple[Mark, ...]:
    """Return confirmed shop points; ambiguous DOO points stay separate evidence."""
    return _shop_marks_with_candidates(md, positions)[0]


def _shop_marks_with_candidates(
    md: MapData, positions: Mapping[str, Point | tuple[Point, ...]]
) -> tuple[tuple[Mark, ...], tuple[Mark, ...]]:
    marks: list[Mark] = []
    candidates: list[Mark] = []
    seen: set[str] = set()
    objects = PlacementObjectIndex(md)
    script_points: PositionGroups | None = None
    for obj in objects.objects.values():
        if obj.category not in ("单位", "英雄"):
            continue
        if obj.obj_id in seen:
            continue
        has_shelf = "usei" in obj.field_values or any(
            field_id == "usei" for field_id, _value in obj.fields
        )
        has_shelf = has_shelf or any(
            variant.kind in (ItemRelationKind.SHOP_SELL, ItemRelationKind.SHOP_MAKE)
            and split_relation_codes(variant.field.source_value)
            for variant in relation_field_variants(obj)
        )
        has_shelf = has_shelf or any(
            key.casefold() in ("sellitems", "makeitems", "umki")
            and split_relation_codes(value)
            for key, value in obj.fields
        )
        if not has_shelf:
            continue
        found = positions.get(obj.obj_id)
        if not found:
            continue
        seen.add(obj.obj_id)
        points = (
            (cast(Point, found),)
            if isinstance(found[0], (int, float))
            else cast(tuple[Point, ...], found)
        )
        confirmed = objects.placement(obj.obj_id, ("单位", "物品")).category == "单位"
        if not confirmed and script_points is None:
            script_points = script_position_groups(md)
        known_script = set((script_points or {}).get(obj.obj_id, ()))
        for x, y in points:
            target = marks if confirmed or (x, y) in known_script else candidates
            target.append((obj.name or obj.obj_id, x, y))
    return tuple(marks), tuple(candidates)


def extra_marks_from_json(path: str) -> tuple[Mark, ...]:
    """自定义点 JSON: [[名称, X, Y], ...] (世界坐标)。"""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise GuideMinimapError("自定义点位 JSON 应是数组: [[名称, X, Y], ...]")
    marks: list[Mark] = []
    for index, entry in enumerate(data):
        if (
            not isinstance(entry, list)
            or len(entry) != 3
            or not isinstance(entry[0], str)
            or not isinstance(entry[1], (int, float))
            or not isinstance(entry[2], (int, float))
            or isinstance(entry[1], bool)
            or isinstance(entry[2], bool)
        ):
            raise GuideMinimapError(f"自定义点位第 {index + 1} 项格式错误: {entry!r}")
        try:
            x, y = float(entry[1]), float(entry[2])
        except OverflowError as exc:
            raise GuideMinimapError(f"自定义点位第 {index + 1} 项坐标不可表示") from exc
        if not math.isfinite(x) or not math.isfinite(y):
            raise GuideMinimapError(f"自定义点位第 {index + 1} 项坐标必须是有限数值")
        marks.append((entry[0], x, y))
    return tuple(marks)


def load_minimap_assets(
    md: MapData,
) -> tuple[Image | None, PositionGroups]:
    """一次打开归档: 返回 (小地图图, 单位放置表)。

    load_map 默认不解析 doo 放置 (md.units 常为空), 这里直接读 war3mapUnits.doo;
    读不到的项保持空/None, 由调用方给出面向用户的错误。
    """
    source = md.archive_source
    if source is None:
        return None, unit_position_groups(md)
    from .blp import decode_blp
    from .doo import parse_units

    extra_units = []
    img = None
    with source.open() as archive:
        if archive.has_file("war3mapMap.blp"):
            decoded = decode_blp(archive.read_file("war3mapMap.blp"))
            if decoded is not None:
                img = decoded.convert("RGB")
        if archive.has_file("war3mapUnits.doo"):
            try:
                extra_units = parse_units(archive.read_file("war3mapUnits.doo"))
            except Exception as exc:
                raise GuideMinimapError(
                    f"预放置单位读取失败，无法确认全部点位: {exc}"
                ) from exc
    return img, unit_position_groups(md, extra_units)


def _load_font(size: int):
    """优先中文字体 (地图名/图例常含中文), 缺失时退回 Pillow 默认字体。"""
    from PIL import ImageFont

    for candidate in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        if os.path.exists(candidate):
            return ImageFont.truetype(candidate, size)
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


_PALETTE = (
    (255, 60, 60),
    (80, 140, 255),
    (120, 200, 60),
    (230, 120, 255),
    (255, 160, 40),
    (250, 215, 60),
    (120, 230, 190),
    (210, 210, 210),
)


def render_marks(
    img: Image,
    bounds: Bounds,
    marks: tuple[Mark, ...],
    out_path: str,
    *,
    scale: int = 4,
    title: str = "地图标注图",
) -> None:
    """裁剪后的底图 ×scale 放大, 画经纬网格/编号圆点/右侧图例, 存 PNG。"""
    from PIL import Image, ImageDraw

    if (
        scale <= 0
        or not all(math.isfinite(value) for value in bounds)
        or bounds[2] <= bounds[0]
        or bounds[3] <= bounds[1]
        or not math.isfinite(bounds[2] - bounds[0])
        or not math.isfinite(bounds[3] - bounds[1])
    ):
        raise GuideMinimapError("小地图需要有限、递增的世界边界和正数缩放")
    if any(not math.isfinite(x) or not math.isfinite(y) for _name, x, y in marks):
        raise GuideMinimapError("小地图点位包含无效坐标，无法绘制完整点位")
    upscaled = img.resize((img.width * scale, img.height * scale))
    width, height = upscaled.size
    draw = ImageDraw.Draw(upscaled)
    span = max(bounds[2] - bounds[0], bounds[3] - bounds[1])
    step = 8192.0
    while span / step > 8:
        step *= 2
    while span / step < 3 and step > 1024:
        step //= 2
    gfont = _load_font(13)
    for tick in range(1, math.ceil((bounds[2] - bounds[0]) / step)):
        gx = bounds[0] + tick * step
        if not bounds[0] < gx < bounds[2]:
            continue
        px, _ = world_to_pixel(gx, 0.0, bounds, width, height)
        draw.line([(px, 0), (px, height)], fill=(255, 255, 255), width=1)
        draw.text(
            (px + 3, 3), f"X{format_number(gx)}", fill=(255, 255, 160), font=gfont
        )
    for tick in range(1, math.ceil((bounds[3] - bounds[1]) / step)):
        gy = bounds[1] + tick * step
        if not bounds[1] < gy < bounds[3]:
            continue
        _, py = world_to_pixel(0.0, gy, bounds, width, height)
        draw.line([(0, py), (width, py)], fill=(255, 255, 255), width=1)
        draw.text(
            (3, py + 3), f"Y{format_number(gy)}", fill=(255, 255, 160), font=gfont
        )
    sfont = _load_font(14)
    radius = max(9, width // 85)
    for index, (name, wx, wy) in enumerate(marks):
        if not bounds[0] <= wx <= bounds[2] or not bounds[1] <= wy <= bounds[3]:
            continue
        px, py = world_to_pixel(wx, wy, bounds, width, height)
        color = _PALETTE[index % len(_PALETTE)]
        draw.ellipse(
            [px - radius, py - radius, px + radius, py + radius],
            fill=color,
            outline=(255, 255, 255),
            width=3,
        )
        label = str(index + 1)
        box = draw.textbbox((0, 0), label, font=sfont)
        draw.text(
            (px - (box[2] - box[0]) / 2, py - (box[3] - box[1]) / 2 - 1),
            label,
            fill=(0, 0, 0),
            font=sfont,
        )
    legend_pad = 36
    tfont = _load_font(22)
    font18 = _load_font(18)
    small = _load_font(14)
    title = single_line_text(title)
    captions = [
        f"{index + 1}  {single_line_text(name)}   ({format_number(wx)}, {format_number(wy)})"
        + (
            "（范围外）"
            if not bounds[0] <= wx <= bounds[2] or not bounds[1] <= wy <= bounds[3]
            else ""
        )
        for index, (name, wx, wy) in enumerate(marks)
    ]
    footers = (
        f"坐标范围: X {format_number(bounds[0])}~{format_number(bounds[2])}  Y {format_number(bounds[1])}~{format_number(bounds[3])}  上=北",
        "圆点编号与右侧图例一一对应",
        "静态点位：预放置、脚本创建位置与自定义点",
    )
    text_widths = [draw.textbbox((0, 0), title, font=tfont)[2]]
    text_widths.extend(
        draw.textbbox((0, 0), caption, font=font18)[2] + 28 for caption in captions
    )
    text_widths.extend(draw.textbbox((0, 0), line, font=small)[2] for line in footers)
    legend_w = math.ceil(max(430, max(text_widths) + 2 * legend_pad + 8))
    canvas_h = max(height, len(marks) * 34 + 18 + 48 + 8 + len(footers) * 26 + 24)
    canvas = Image.new("RGB", (width + legend_w, canvas_h), (16, 16, 20))
    canvas.paste(upscaled, (0, 0))
    legend = ImageDraw.Draw(canvas)
    cursor_y = 18
    legend.text((width + legend_pad, cursor_y), title, fill=(245, 245, 245), font=tfont)
    cursor_y += 48
    for index, (name, wx, wy) in enumerate(marks):
        color = _PALETTE[index % len(_PALETTE)]
        legend.ellipse(
            [width + legend_pad, cursor_y + 2, width + legend_pad + 20, cursor_y + 22],
            fill=color,
            outline=(255, 255, 255),
            width=2,
        )
        legend.text(
            (width + legend_pad + 28, cursor_y),
            captions[index],
            fill=(215, 215, 215),
            font=font18,
        )
        cursor_y += 34
    cursor_y += 8
    for line in footers:
        legend.text(
            (width + legend_pad, cursor_y), line, fill=(150, 150, 150), font=small
        )
        cursor_y += 26
    image_format = Image.registered_extensions().get(
        os.path.splitext(out_path)[1].lower()
    )
    if image_format is None:
        raise GuideMinimapError("小地图标注图输出需要支持的图片扩展名，例如 .png")
    # 编码与发布分别完成，编码失败或磁盘写入失败不能破坏已有标注图。
    with tempfile.TemporaryFile() as encoded:
        canvas.save(encoded, format=image_format)
        encoded.seek(0)
        absolute = os.path.abspath(out_path)
        result = write_chunks_safely(
            os.path.dirname(absolute),
            os.path.basename(absolute),
            iter(lambda: encoded.read(1024 * 1024), b""),
        )
    if result.status is not SafeWriteStatus.WRITTEN:
        raise GuideMinimapError(result.error or result.status.value)


def write_guide_minimap(
    md: MapData,
    out_path: str,
    extra_json: str | None = None,
) -> list[str]:
    """生成标注小地图; 返回给 CLI 打印的摘要行。失败抛 GuideMinimapError。"""
    bounds = playable_bounds(md)
    if bounds is None:
        raise GuideMinimapError("w3i 缺少镜头边界/补足, 无法把世界坐标对齐到小地图")
    img, positions = load_minimap_assets(md)
    shops, candidates = _shop_marks_with_candidates(md, positions)
    marks: list[Mark] = list(shops)
    extra_count = 0
    if extra_json:
        extra = extra_marks_from_json(extra_json)
        marks.extend(extra)
        extra_count = len(extra)
    if not marks:
        if candidates:
            raise GuideMinimapError(
                f"另有 {len(candidates)} 处候选商店位置，分类尚未确认为单位，不能标为确定商店；可用 guide --section shops 或 pack-query near 查看完整线索。"
            )
        raise GuideMinimapError(
            "没有可标注的点位 (对象表没有带 usei 货架且已放置的商店, 也未提供追加 JSON)"
        )
    if img is None:
        raise GuideMinimapError("地图里没有可解码的 war3mapMap.blp 小地图底图")
    img = crop_to_playable(img, bounds)
    render_marks(img, bounds, tuple(marks), out_path)
    notes = [
        f"小地图标注图已保存: {out_path}",
        f"点位 {len(marks)} 个 (商店 {len(shops)} + 自定义 {extra_count})",
        "自定义追加: --minimap-marks <marks.json>, JSON 格式 [[名称, X, Y], ...]",
    ]
    if candidates:
        notes.append(
            f"另有 {len(candidates)} 处候选商店位置未标为确定商店；可用 guide --section shops 或 pack-query near 查看完整线索。"
        )
    return notes
