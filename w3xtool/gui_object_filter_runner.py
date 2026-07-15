"""Tk-safe background runner for object browser filtering."""

from __future__ import annotations

from collections.abc import Callable
import traceback
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, assert_never

from .api import GameObject, MapData
from .gui_worker_registry import GuiWorkerTicket
from .object_filter import ObjectFilterResult, filter_objects_by_query
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

    class _Configurable(Protocol):
        def configure(self, *, text: str) -> None: ...

    class _TypingSearchVariable:
        def get(self) -> str:
            return ""

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
        self.status.configure(text="正在筛选对象 …")
        _ = self._start_gui_worker(
            "object-filter",
            lambda ticket: self._run_object_filter_job(ticket, md, query),
            replace=True,
        )

    def _run_object_filter_job(
        self,
        ticket: GuiWorkerTicket,
        md: MapData,
        query: str,
    ) -> None:
        try:
            payload: ObjectFilterPayload = filter_objects_by_query(md, query)
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
