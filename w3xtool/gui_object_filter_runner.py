"""Tk-safe background runner for object browser filtering."""

from __future__ import annotations

from collections.abc import Callable
import traceback
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, assert_never

from .api import GameObject, MapData
from .gui_worker_registry import GuiWorkerTicket
from .object_filter import (
    ALL_OBJECTS_LABEL,
    ObjectFilterResult,
    filter_objects_by_query,
    object_fine_category,
)
from .theme import CARD, PARALLEL_CATS, ROW_ALT

OBJECT_TREE_LIMIT: Final = 32


@dataclass(frozen=True, slots=True)
class ObjectFilterError:
    """A worker failure that should be surfaced on the status bar."""

    message: str


ObjectFilterPayload = ObjectFilterResult | ObjectFilterError


if TYPE_CHECKING:
    from .gui_worker_registry import GuiWorkerTarget

    class _SearchVariable(Protocol):
        def get(self) -> str: ...

    class _FineCombo(Protocol):
        def get(self) -> str: ...

        def set(self, value: str) -> None: ...

        def configure(self, *, values: list[str]) -> None: ...

    class _Configurable(Protocol):
        def configure(self, *, text: str) -> None: ...

    class _TypingSearchVariable:
        def get(self) -> str:
            return ""

    class _TypingFineCombo:
        def get(self) -> str:
            return ALL_OBJECTS_LABEL

        def set(self, value: str) -> None:
            _ = value

        def configure(self, *, values: list[str]) -> None:
            _ = values

    class _TypingConfigurable:
        def configure(self, *, text: str) -> None:
            _ = text

    class _ObjectTree(Protocol):
        def delete(self, *items: str) -> None: ...

        def get_children(self) -> tuple[str, ...]: ...

        def insert(
            self,
            parent: str,
            index: str,
            *,
            iid: str,
            image: str,
            text: str,
            tags: tuple[str, ...],
        ) -> str: ...

        def tag_configure(self, tag: str, *, background: str) -> None: ...

    class _ObjectFilterHost:
        map_data: MapData | None = None
        search_var: _SearchVariable = _TypingSearchVariable()
        status: _Configurable = _TypingConfigurable()
        col_results: dict[str, list[GameObject]] = {}
        col_headers: dict[str, _Configurable] = {}
        col_trees: dict[str, _ObjectTree] = {}
        object_fine_filter: _FineCombo = _TypingFineCombo()

        def _start_gui_worker(
            self,
            group: str,
            target: GuiWorkerTarget,
            *,
            replace: bool,
        ) -> GuiWorkerTicket: ...

        def _post_gui_worker(
            self,
            ticket: GuiWorkerTicket,
            callback: Callable[[], None],
            *,
            cleanup: Callable[[], None] | None = None,
        ) -> bool: ...

        def _cancel_gui_worker_group(self, group: str) -> None: ...

        def _render_object_cards(self) -> None: ...

        def _autosize_tree(self, tree: _ObjectTree) -> None: ...

else:
    _ObjectFilterHost = object


class ObjectFilterRunnerMixin(_ObjectFilterHost):
    """Run expensive object filtering away from the Tk main thread."""

    def _init_object_filter_runner(self) -> None:
        """Retain the explicit subsystem initialization hook."""

    def _shutdown_object_filter_runner(self) -> None:
        self._cancel_gui_worker_group("object-filter")

    def _refresh_list(self) -> None:
        if not self.map_data:
            return
        query = self.search_var.get()
        md = self.map_data
        fine_filter = self._sync_object_fine_choices(md)
        self.status.configure(text="正在筛选对象 …")
        _ = self._start_gui_worker(
            "object-filter",
            lambda ticket: self._run_object_filter_job(ticket, md, query, fine_filter),
            replace=True,
        )

    def _sync_object_fine_choices(self, md: MapData) -> str:
        """细类下拉只列当前地图对象出现过的细类，保留仍然有效的选择。"""
        present = sorted(
            {
                fine
                for objects in md.objects.values()
                for fine in (object_fine_category(obj) for obj in objects)
                if fine
            }
        )
        current = self.object_fine_filter.get()
        self.object_fine_filter.configure(values=[ALL_OBJECTS_LABEL, *present])
        if current != ALL_OBJECTS_LABEL and current not in present:
            self.object_fine_filter.set(ALL_OBJECTS_LABEL)
            return ALL_OBJECTS_LABEL
        return current

    def _run_object_filter_job(
        self,
        ticket: GuiWorkerTicket,
        md: MapData,
        query: str,
        fine_filter: str,
    ) -> None:
        try:
            payload: ObjectFilterPayload = filter_objects_by_query(
                md, query, fine_filter
            )
        except Exception as exc:  # noqa: BROAD_EXCEPT_OK
            traceback.print_exc()
            payload = ObjectFilterError(f"对象筛选失败：{exc}")
        _ = self._post_gui_worker(
            ticket,
            lambda: self._handle_object_filter_payload(payload),
        )

    def _handle_object_filter_payload(self, payload: ObjectFilterPayload) -> None:
        match payload:
            case ObjectFilterResult() as result:
                self._apply_object_filter_result(result)
            case ObjectFilterError(message=message):
                self.status.configure(text=message)
            case unreachable:
                assert_never(unreachable)

    def _apply_object_filter_result(self, result: ObjectFilterResult) -> None:
        for category in PARALLEL_CATS:
            objects = result.results_by_category.get(category, [])
            self.col_results[category] = objects
            self._refresh_object_tree(category, objects)
            self.col_headers[category].configure(text=f"{category}  ({len(objects)})")
        self.status.configure(text="  ".join(result.summary))
        self._render_object_cards()

    def _refresh_object_tree(self, category: str, objects: list[GameObject]) -> None:
        tree = self.col_trees[category]
        tree.delete(*tree.get_children())
        for index, obj in enumerate(objects[:OBJECT_TREE_LIMIT]):
            ext = getattr(obj, "ext", "")
            mark = (
                " 〔脚本〕"
                if ext == "script"
                else (" 〔原版〕" if ext == "base" else "")
            )
            tree.insert(
                "",
                "end",
                iid=str(index),
                image="",
                text=f" {obj.name}{mark}",
                tags=("odd" if index % 2 else "even",),
            )
        tree.tag_configure("odd", background=ROW_ALT)
        tree.tag_configure("even", background=CARD)
        self._autosize_tree(tree)
