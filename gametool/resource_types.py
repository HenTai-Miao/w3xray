"""Shared resource suffixes and labels without report/discovery dependencies."""

from typing import Final

_IMAGE_EXTS: Final = {"blp", "dds", "tga", "png", "jpg", "jpeg", "bmp"}
_MODEL_EXTS: Final = {"mdx", "mdl"}
_AUDIO_EXTS: Final = {"wav", "mp3", "ogg"}
_FONT_EXTS: Final = {"ttf", "otf"}
_UI_TEXT_EXTS: Final = {"txt", "ini", "fdf", "toc"}
_TABLE_EXTS: Final = {"slk"}
_CONFIG_EXTS: Final = {"json", "plist", "skin"}
_AI_EXTS: Final = {"ai"}
RESOURCE_EXTS: Final = (
    _IMAGE_EXTS
    | _MODEL_EXTS
    | _AUDIO_EXTS
    | _FONT_EXTS
    | _UI_TEXT_EXTS
    | _TABLE_EXTS
    | _CONFIG_EXTS
    | _AI_EXTS
)


def resource_kind(path: str) -> str:
    """Return the established resource label from the complete suffix."""
    normalized = path.strip().strip('"').strip("'").lower()
    ext = normalized.rsplit(".", 1)[-1] if "." in normalized else ""
    if ext in _IMAGE_EXTS:
        return "图像"
    if ext in _MODEL_EXTS:
        return "模型"
    if ext in _AUDIO_EXTS:
        return "音频"
    if ext in _FONT_EXTS:
        return "字体"
    if ext in _UI_TEXT_EXTS:
        return "UI/文本"
    if ext in _TABLE_EXTS:
        return "SLK表"
    if ext in _CONFIG_EXTS:
        return "配置"
    if ext in _AI_EXTS:
        return "AI脚本"
    return "资源"
