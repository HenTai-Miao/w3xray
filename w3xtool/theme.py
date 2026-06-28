"""GUI visual tokens for the anime-styled map inspection terminal."""

from __future__ import annotations

# Typography: CJK UI first, with a monospaced face for dense data panes.
FONT = "Microsoft YaHei UI"
TITLE_FONT = "Bahnschrift"
MONO_FONT = "JetBrains Mono"

# Layout version: bump when saved sash positions no longer match the UI shell.
LAYOUT_VERSION = 5

# Palette: blue-white anime data terminal with warm pink action accents.
BG = "#eaf6ff"
TOPBAR = "#f9fdff"
CARD = "#ffffff"
CARD_RAISED = "#e9f5ff"
PANEL = "#f5fbff"
HEADER = "#d8ecff"
ROW_ALT = "#f2f9ff"
BORDER = "#b8d9f6"
TEXT = "#28445f"
TEXT_STRONG = "#102a43"
SUBTLE = "#6b89a6"
MUTED = "#91a8bd"
ACCENT = "#ff77a9"
ACCENT_HOVER = "#ff93ba"
ACCENT_DARK = "#ff5f9e"
INFO = "#2ebbd9"
INFO_HOVER = "#5ed7f0"
SECONDARY = "#e4f1ff"
SECONDARY_HOVER = "#d2eaff"
SEL_BG = "#bfe8ff"
SEL_TEXT = "#102a43"

PARALLEL_CATS = ["物品", "单位", "技能", "科技"]
CATEGORY_COLORS = {
    "物品": "#ff9f43",
    "单位": "#31b978",
    "技能": "#2ebbd9",
    "科技": "#8d79ff",
}


def entry_style():
    return {
        "fg_color": PANEL,
        "border_color": BORDER,
        "border_width": 1,
        "text_color": TEXT,
        "placeholder_text_color": MUTED,
    }


def primary_button_style():
    return {
        "fg_color": ACCENT_DARK,
        "hover_color": ACCENT_HOVER,
        "text_color": "#ffffff",
        "corner_radius": 18,
    }


def secondary_button_style():
    return {
        "fg_color": SECONDARY,
        "hover_color": SECONDARY_HOVER,
        "text_color": TEXT,
        "corner_radius": 16,
    }


def card_style():
    return {
        "fg_color": CARD,
        "corner_radius": 14,
        "border_width": 1,
        "border_color": BORDER,
    }
