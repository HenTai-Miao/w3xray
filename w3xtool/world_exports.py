"""TSV exports for parsed World Editor region, camera and sound metadata."""

from __future__ import annotations

from collections.abc import Iterable

from .w3world import Camera, Region, Sound


def format_regions_tsv(regions: Iterable[Region]) -> str:
    """Return parsed W3R regions as TSV."""
    rows = ["ID\t名称\t左\t下\t右\t上\t天气\t环境声音\t颜色RGB\tAlpha"]
    for region in regions:
        rows.append("\t".join((
            str(region.region_id),
            _tsv(region.name),
            _num(region.left),
            _num(region.bottom),
            _num(region.right),
            _num(region.top),
            _tsv(region.weather_effect),
            _tsv(region.ambient_sound),
            ",".join(str(part) for part in region.color_rgb),
            str(region.alpha),
        )))
    return "\n".join(rows) + "\n"


def format_cameras_tsv(cameras: Iterable[Camera]) -> str:
    """Return parsed W3C cameras as TSV."""
    rows = ["名称\t目标X\t目标Y\tZ偏移\t旋转\t攻击角\t距离\t滚转\t视野\t远裁剪\t近裁剪\t本地俯仰\t本地偏航\t本地滚转"]
    for camera in cameras:
        rows.append("\t".join((
            _tsv(camera.name),
            _num(camera.target_x),
            _num(camera.target_y),
            _num(camera.offset_z),
            _num(camera.rotation),
            _num(camera.angle_of_attack),
            _num(camera.distance),
            _num(camera.roll),
            _num(camera.field_of_view),
            _num(camera.far_clip),
            _num(camera.near_clip),
            _maybe_num(camera.local_pitch),
            _maybe_num(camera.local_yaw),
            _maybe_num(camera.local_roll),
        )))
    return "\n".join(rows) + "\n"


def format_sounds_tsv(sounds: Iterable[Sound]) -> str:
    """Return parsed W3S sounds as TSV."""
    rows = [
        "名称\t路径\t变量\tEAX\t循环\t3D\t音乐\t导入\t音量\t淡入\t淡出\t音高\t音高变化\t优先级\t声道\t最小距离\t最大距离\t截断距离"
    ]
    for sound in sounds:
        rows.append("\t".join((
            _tsv(sound.name),
            _tsv(sound.path),
            _tsv(sound.variable_name),
            _tsv(sound.eax_effect),
            _yes_no(sound.is_looping),
            _yes_no(sound.is_3d),
            _yes_no(sound.is_music),
            _yes_no(sound.is_imported),
            str(sound.volume),
            str(sound.fade_in_rate),
            str(sound.fade_out_rate),
            _num(sound.pitch),
            _num(sound.pitch_variance),
            str(sound.priority),
            str(sound.channel),
            _num(sound.min_distance),
            _num(sound.max_distance),
            _num(sound.cutoff_distance),
        )))
    return "\n".join(rows) + "\n"


def _maybe_num(value: float | None) -> str:
    if value is None:
        return ""
    return _num(value)


def _num(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.4g}"


def _yes_no(value: bool) -> str:
    return "是" if value else "否"


def _tsv(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")
