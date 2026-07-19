"""Validated global-generation batch-status view model and GUI."""
# pyright: reportAttributeAccessIssue=false, reportUninitializedInstanceVariable=false

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog
from typing import override

from .batch_global_models import GlobalGeneration
from .batch_global_publication import load_current_generation
from .batch_models import BatchState
from .gui_batch_status_layout import BatchStatusLayoutMixin


class BatchStatusLoadError(ValueError):
    """The selected batch root has no usable authoritative generation."""

    @override
    def __str__(self) -> str:
        return self.args[0]


@dataclass(frozen=True, slots=True)
class BatchStatusRow:
    map_path: str
    display_name: str
    publication: str
    archive: str
    knowledge: str
    knowledge_reasons: tuple[str, ...]
    source_coverage_gap_count: int
    unresolved_paths: int
    unresolved_references: int
    filtered_fields: int
    relation_partial_count: int
    raw_blocks: int
    damaged_blocks: int
    restricted_blocks: int


@dataclass(frozen=True, slots=True)
class BatchStatusSnapshot:
    root: Path
    generation: GlobalGeneration
    rows: tuple[BatchStatusRow, ...]


def load_batch_status(root: str | Path) -> BatchStatusSnapshot:
    """Load exactly the current validated global generation."""
    selected = Path(root).expanduser()
    if selected.is_symlink():
        raise BatchStatusLoadError("batch output root is a symlink")
    normalized = selected.resolve(strict=True)
    generation = load_current_generation(normalized)
    if generation is None:
        raise BatchStatusLoadError("validated generation is unavailable")
    return BatchStatusSnapshot(
        normalized, generation, batch_status_rows(generation.state)
    )


def batch_status_rows(state: BatchState) -> tuple[BatchStatusRow, ...]:
    """Render independent schema-six axes without deriving replacement state."""
    return tuple(
        BatchStatusRow(
            result.source.path,
            result.display_name,
            result.publication_result.value,
            result.archive_integrity.value,
            result.knowledge_evidence.value,
            tuple(reason.value for reason in result.knowledge_gap_reasons),
            result.source_coverage_gap_count,
            result.unresolved_icon_count,
            result.unresolved_icon_reference_count,
            result.filtered_icon_field_count,
            result.relation_partial_count,
            result.raw_block_count,
            result.damaged_block_count,
            result.restricted_block_count,
        )
        for result in state.results
    )


class BatchStatusGuiMixin(BatchStatusLayoutMixin):
    """Run validated status loading on the shared bounded GUI worker host."""

    def _init_batch_status_gui(self) -> None:
        self._batch_status_snapshot: BatchStatusSnapshot | None = None

    def _choose_batch_status_root(self) -> None:
        selected = filedialog.askdirectory(title="选择批量结果目录")
        if selected:
            self._start_batch_status_load(selected)

    def _start_batch_status_load(self, root: str) -> None:
        self.batch_status_label.configure(text="正在验证批量结果…")
        _ = self._start_gui_worker(
            "batch-status",
            lambda ticket: self._run_batch_status_load(ticket, root),
            replace=True,
        )

    def _run_batch_status_load(self, ticket, root: str) -> None:
        try:
            payload: BatchStatusSnapshot | BatchStatusLoadError = load_batch_status(
                root
            )
        except (OSError, ValueError) as exc:
            payload = BatchStatusLoadError(str(exc))
        _ = self._post_gui_worker(
            ticket, lambda: self._apply_batch_status_payload(payload)
        )

    def _apply_batch_status_payload(
        self, payload: BatchStatusSnapshot | BatchStatusLoadError
    ) -> None:
        if isinstance(payload, BatchStatusLoadError):
            self.batch_status_label.configure(text=str(payload))
            return
        self._batch_status_snapshot = payload
        self.batch_status_label.configure(
            text=f"已验证 generation {payload.generation.generation_id}"
        )
        tree = self.batch_status_tree
        tree.delete(*tree.get_children())
        for index, row in enumerate(payload.rows):
            tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    row.display_name,
                    row.publication,
                    row.archive,
                    row.knowledge,
                    "、".join(row.knowledge_reasons),
                    row.source_coverage_gap_count,
                    f"{row.unresolved_paths}/{row.unresolved_references}",
                    row.filtered_fields,
                    row.relation_partial_count,
                    f"{row.raw_blocks}/{row.damaged_blocks}/{row.restricted_blocks}",
                ),
            )
        self.batch_status_detail.configure(state="normal")
        self.batch_status_detail.delete("1.0", "end")
        self.batch_status_detail.insert(
            "end",
            f"根目录：{payload.root}\nGeneration：{payload.generation.generation_id}",
        )
        self.batch_status_detail.configure(state="disabled")
        self._set_global_icon_evidence(payload.generation.evidence)
