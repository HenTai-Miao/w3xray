"""Hands-on Tk workflow used by Windows source and packaged acceptance."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import override

from .gui import App
from .gui_loader import load_path_payload


@dataclass(frozen=True, slots=True)
class GuiAcceptanceError(RuntimeError):
    tab_label: str

    @override
    def __str__(self) -> str:
        return f"GUI tab did not activate: {self.tab_label}"


def run_gui_acceptance(map_path: Path) -> str:
    """Create the real workbench, load a map, and visit every primary tab."""
    payload = load_path_payload(str(map_path))
    app = App()
    app.withdraw()
    try:
        app._on_loaded(
            payload.active,
            payload.commands,
            payload.recipes,
            payload.resolver,
            payload.views,
            payload.campaign_path,
        )
        visited: list[str] = []
        for label in app.editor_tab_labels:
            app.tabs.set(label)
            app.update_idletasks()
            if app.tabs.get() != label:
                raise GuiAcceptanceError(label)
            visited.append(label)
        app.update()
        return f"loaded={payload.active.name}; tabs={len(visited)}; {','.join(visited)}"
    finally:
        _destroy_without_persisting(app)


def _destroy_without_persisting(app: App) -> None:
    app._shutdown_background_loader()
    app._shutdown_object_filter_runner()
    if app.icons is not None and hasattr(app.icons, "close"):
        app.icons.close()
    app.destroy()
