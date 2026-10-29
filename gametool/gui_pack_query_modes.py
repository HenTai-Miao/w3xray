"""Canonical query commands and their visible GUI mode rows."""

from __future__ import annotations


MODE_ROWS = (
    (
        "doc",
        "search",
        "list",
        "buffs",
        "export",
        "synth",
        "skills",
        "units",
        "locate",
        "near",
        "where",
        "drop",
    ),
    ("again", "stats", "shop", "tech", "item", "heroes"),
    ("price", "quest", "cmd", "text", "refs", "affixes", "registered", "diff", "calls"),
)
NO_MODE_SELECTION = "<<none>>"
_LABELS = {"calls": "脚本调用"}
_COMMANDS_BY_LABEL = {label: command for command, label in _LABELS.items()}


def mode_command(value: str) -> str:
    """Keep display labels out of saved queries and shared execution requests."""
    return _COMMANDS_BY_LABEL.get(value, value)


def mode_row_labels(row: int) -> list[str]:
    """Return exactly the displayed values for one command row."""
    return [_LABELS.get(command, command) for command in MODE_ROWS[row]]


def mode_row_selections(command: str) -> tuple[str, ...]:
    """Select only the row containing the canonical command."""
    command = mode_command(command)
    label = _LABELS.get(command, command)
    return tuple(label if command in row else NO_MODE_SELECTION for row in MODE_ROWS)
