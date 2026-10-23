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
import os
import re
from typing import TYPE_CHECKING

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

from .script_sources import analysis_script_texts

# 点位 = (名称, 世界X, 世界Y)
Mark = tuple[str, float, float]
Bounds = tuple[float, float, float, float]


class GuideMinimapError(ValueError):
    """小地图标注图生成失败, message 面向命令行用户。"""


# 与 pack_query_cli._CREATE_UNIT_RE 同一模式: 脚本 CreateUnit 字面量坐标
_CREATE_UNIT_RE = re.compile(
    r"CreateUnit\s*\(\s*\w+\s*,\s*'(\w{4})'\s*,\s*(-?\s?[\d.]+)\s*,\s*(-?\s?[\d.]+)"
)


def script_unit_positions(md: MapData) -> dict[str, tuple[float, float]]:
    """war3mapUnits.doo 缺失 (全脚本放置) 的图: 从脚本 CreateUnit 字面量提取位置。

    同一 fourcc 多次 CreateUnit 只留首次 (商店/NPC 通常只有一个固定放置点)。
    """
    positions: dict[str, tuple[float, float]] = {}
    for _source, text in analysis_script_texts(md):
        for match in _CREATE_UNIT_RE.finditer(text):
            code = match.group(1)
            if code not in positions:
                positions[code] = (
                    float(match.group(2).replace(" ", "")),
                    float(match.group(3).replace(" ", "")),
                )
    return positions


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
    if playable[2] - playable[0] <= 0 or playable[3] - playable[1] <= 0:
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
    band_h = round(img.width / aspect)
    if band_h < img.height:
        top = (img.height - band_h) // 2
        return img.crop((0, top, img.width, top + band_h))
    band_w = round(img.height * aspect)
    if band_w < img.width:
        left = (img.width - band_w) // 2
        return img.crop((left, 0, left + band_w, img.height))
    return img


def shop_marks(
    md: MapData, positions: dict[str, tuple[float, float]]
) -> tuple[Mark, ...]:
    """带 usei 货架且有放置坐标的单位 → (名, X, Y) 列表; 坐标来自 load_minimap_assets。"""
    marks: list[Mark] = []
    seen: set[str] = set()
    for obj in md.objects.get("单位", []):
        if obj.obj_id in seen:
            continue
        has_shelf = "usei" in obj.field_values or any(
            field_id == "usei" for field_id, _value in obj.fields
        )
        if not has_shelf:
            continue
        position = positions.get(obj.obj_id)
        if position is None:
            continue
        seen.add(obj.obj_id)
        marks.append((obj.name or obj.obj_id, position[0], position[1]))
    return tuple(marks)


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
        ):
            raise GuideMinimapError(f"自定义点位第 {index + 1} 项格式错误: {entry!r}")
        marks.append((entry[0], float(entry[1]), float(entry[2])))
    return tuple(marks)


def load_minimap_assets(
    md: MapData,
) -> tuple[Image | None, dict[str, tuple[float, float]]]:
    """一次打开归档: 返回 (小地图图, 单位放置表)。

    load_map 默认不解析 doo 放置 (md.units 常为空), 这里直接读 war3mapUnits.doo;
    读不到的项保持空/None, 由调用方给出面向用户的错误。
    """
    source = md.archive_source
    if source is None:
        return None, {}
    from .blp import decode_blp
    from .doo import parse_units

    # 证据优先级: war3mapUnits.doo 放置 > md.units (同源) > 脚本 CreateUnit 字面量
    positions: dict[str, tuple[float, float]] = dict(script_unit_positions(md))
    img = None
    with source.open() as archive:
        if archive.has_file("war3mapMap.blp"):
            decoded = decode_blp(archive.read_file("war3mapMap.blp"))
            if decoded is not None:
                img = decoded.convert("RGB")
        if archive.has_file("war3mapUnits.doo"):
            try:
                for unit in parse_units(archive.read_file("war3mapUnits.doo")):
                    positions[unit.type_id] = (unit.x, unit.y)
            except Exception:  # noqa: BLE001, S110 - 放置表解析失败不阻断底图。
                pass
    for unit in md.units:
        positions[unit.type_id] = (unit.x, unit.y)
    return img, positions


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

    upscaled = img.resize((img.width * scale, img.height * scale))
    width, height = upscaled.size
    draw = ImageDraw.Draw(upscaled)
    span = bounds[2] - bounds[0]
    step = 8192.0
    while span / step > 8:
        step *= 2
    while span / step < 3 and step > 1024:
        step //= 2
    gfont = _load_font(13)
    gx = bounds[0] + step
    while gx < bounds[2] - 1:
        px, _ = world_to_pixel(gx, 0.0, bounds, width, height)
        draw.line([(px, 0), (px, height)], fill=(255, 255, 255), width=1)
        draw.text((px + 3, 3), f"X{int(gx)}", fill=(255, 255, 160), font=gfont)
        gx += step
    gy = bounds[1] + step
    while gy < bounds[3] - 1:
        _, py = world_to_pixel(0.0, gy, bounds, width, height)
        draw.line([(0, py), (width, py)], fill=(255, 255, 255), width=1)
        draw.text((3, py + 3), f"Y{int(gy)}", fill=(255, 255, 160), font=gfont)
        gy += step
    sfont = _load_font(14)
    radius = max(9, width // 85)
    for index, (name, wx, wy) in enumerate(marks):
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
    legend_w = 430
    canvas_h = max(height, len(marks) * 34 + 145)
    canvas = Image.new("RGB", (width + legend_w, canvas_h), (16, 16, 20))
    canvas.paste(upscaled, (0, 0))
    legend = ImageDraw.Draw(canvas)
    tfont = _load_font(22)
    font18 = _load_font(18)
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
            f"{index + 1}  {name}   ({int(wx)}, {int(wy)})",
            fill=(215, 215, 215),
            font=font18,
        )
        cursor_y += 34
    cursor_y += 8
    small = _load_font(14)
    for line in (
        f"坐标范围: X {int(bounds[0])}~{int(bounds[2])}  Y {int(bounds[1])}~{int(bounds[3])}  上=北",
        "圆点编号与右侧图例一一对应",
    ):
        legend.text(
            (width + legend_pad, cursor_y), line, fill=(150, 150, 150), font=small
        )
        cursor_y += 26
    canvas.save(out_path)


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
    shops = shop_marks(md, positions)
    marks: list[Mark] = list(shops)
    extra_count = 0
    if extra_json:
        extra = extra_marks_from_json(extra_json)
        marks.extend(extra)
        extra_count = len(extra)
    if not marks:
        raise GuideMinimapError(
            "没有可标注的点位 (对象表没有带 usei 货架且已放置的商店, 也未提供追加 JSON)"
        )
    if img is None:
        raise GuideMinimapError("地图里没有可解码的 war3mapMap.blp 小地图底图")
    img = crop_to_playable(img, bounds)
    render_marks(img, bounds, tuple(marks), out_path)
    return [
        f"小地图标注图已保存: {out_path}",
        f"点位 {len(marks)} 个 (商店 {len(shops)} + 自定义 {extra_count})",
        "自定义追加: --minimap-marks <marks.json>, JSON 格式 [[名称, X, Y], ...]",
    ]
