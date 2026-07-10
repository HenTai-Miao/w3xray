"""Public mutable map-extraction models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .external_listfile import ExternalListfileReport

if TYPE_CHECKING:
    from .archive_source import ArchiveSource
    from .extraction_diagnostics import ExtractionDiagnostic


@dataclass(slots=True)
class GameObject:
    """Mutable object builder populated by the extraction pipeline."""

    category: str
    ext: str
    obj_id: str
    base_id: str
    name: str
    is_custom: bool
    fields: list[tuple[str, str]] = field(default_factory=list)
    search_text: str = ""
    icon: str = ""
    ref_fields: list[tuple[str, list[str]]] = field(default_factory=list)
    field_values: dict[str, str] = field(default_factory=dict)
    field_sources: dict[str, str] = field(default_factory=dict)

    @property
    def decimal(self) -> int:
        """Return the four-character object code as a big-endian integer."""
        value = self.obj_id.encode("latin-1", "ignore")[:4].ljust(4, b"\x00")
        return int.from_bytes(value, "big")


@dataclass(slots=True)
class MapData:
    """Mutable map builder preserving the original public extraction fields.

    Extraction incrementally populates this model, so mutability is intentional.
    New lifecycle fields are appended to preserve legacy positional construction.
    """

    path: str
    name: str
    objects: dict[str, list[GameObject]] = field(default_factory=dict)
    scripts: dict[str, str] = field(default_factory=dict)
    all_files: list[str] = field(default_factory=list)
    external_listfile: ExternalListfileReport | None = None
    sub_maps: list[MapData] = field(default_factory=list)
    obj_index: dict[str, GameObject] = field(default_factory=dict)
    doodads: list[object] = field(default_factory=list)
    units: list[object] = field(default_factory=list)
    regions: list[object] = field(default_factory=list)
    cameras: list[object] = field(default_factory=list)
    sounds: list[object] = field(default_factory=list)
    game_configs: list[object] = field(default_factory=list)
    trigger_summary: object | None = None
    preview_icons: object | None = None
    import_summary: object | None = None
    w3i: object | None = None
    w3f: object | None = None
    references: dict[str, list[tuple[str, list[tuple[str, str | None]]]]] = field(default_factory=dict)
    referenced_by: dict[str, list[tuple[str, str, str]]] = field(default_factory=dict)
    orphans: list[GameObject] = field(default_factory=list)
    ref_low_coverage: bool = False
    script_features: list[object] = field(default_factory=list)
    author_bundle_files: tuple[str, ...] = ()
    archive_source: ArchiveSource | None = None
    diagnostics: list[ExtractionDiagnostic] = field(default_factory=list)
    ui_strings: dict[int, str] | None = None
    _closed: bool = field(default=False, init=False, repr=False)

    def category_counts(self) -> dict[str, int]:
        """Return object counts by category in insertion order."""
        return {category: len(items) for category, items in self.objects.items()}

    def close(self) -> None:
        """Close this map's source and recursively close embedded maps once."""
        if self._closed:
            return
        self._closed = True
        try:
            if self.archive_source is not None:
                self.archive_source.close()
        finally:
            for sub_map in self.sub_maps:
                sub_map.close()
