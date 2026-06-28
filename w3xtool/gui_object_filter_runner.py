"""Tk-safe background runner for object browser filtering."""

from __future__ import annotations

import queue
import threading
import traceback
from dataclasses import dataclass
from typing import Final, assert_never

from .api import GameObject, MapData
from .object_filter import ObjectFilterResult, filter_objects_by_query
from .theme import CARD, PARALLEL_CATS, ROW_ALT

OBJECT_FILTER_POLL_MS: Final = 35
OBJECT_TREE_LIMIT: Final = 32


@dataclass(frozen=True, slots=True)
class ObjectFilterError:
    """A worker failure that should be surfaced on the status bar."""

    message: str


ObjectFilterPayload = ObjectFilterResult | ObjectFilterError


class ObjectFilterRunnerMixin:
    """Run expensive object filtering away from the Tk main thread."""

    def _init_object_filter_runner(self) -> None:
        self._object_filter_results: queue.Queue[tuple[int, ObjectFilterPayload]] = queue.Queue()
        self._object_filter_token = 0
        self._object_filter_pending: set[int] = set()
        self._object_filter_poll_id: str | None = None

    def _shutdown_object_filter_runner(self) -> None:
        self._object_filter_token += 1
        self._object_filter_pending.clear()
        poll_id = getattr(self, "_object_filter_poll_id", None)
        if poll_id:
            try:
                self.after_cancel(poll_id)
            except Exception:
                pass
        self._object_filter_poll_id = None

    def _refresh_list(self) -> None:
        if not self.map_data:
            return
        self._object_filter_token += 1
        token = self._object_filter_token
        query = self.search_var.get()
        md = self.map_data
        self._object_filter_pending.add(token)
        self.status.configure(text="正在筛选对象 …")
        worker = threading.Thread(
            target=self._run_object_filter_job,
            args=(token, md, query),
            daemon=True,
            name=f"w3xray-object-filter-{token}",
        )
        worker.start()
        self._schedule_object_filter_poll()

    def _run_object_filter_job(self, token: int, md: MapData, query: str) -> None:
        try:
            payload: ObjectFilterPayload = filter_objects_by_query(md, query)
        except Exception as exc:  # noqa: BROAD_EXCEPT_OK
            traceback.print_exc()
            payload = ObjectFilterError(f"对象筛选失败：{exc}")
        self._object_filter_results.put((token, payload))

    def _schedule_object_filter_poll(self) -> None:
        if self._object_filter_poll_id is None:
            self._object_filter_poll_id = self.after(
                OBJECT_FILTER_POLL_MS,
                self._poll_object_filter_results,
            )

    def _poll_object_filter_results(self) -> None:
        self._object_filter_poll_id = None
        while True:
            try:
                token, payload = self._object_filter_results.get_nowait()
            except queue.Empty:
                break
            self._object_filter_pending.discard(token)
            if token != self._object_filter_token:
                continue
            self._handle_object_filter_payload(payload)
        if self._object_filter_pending:
            self._schedule_object_filter_poll()

    def _handle_object_filter_payload(self, payload: ObjectFilterPayload) -> None:
        match payload:
            case ObjectFilterResult() as result:
                self._apply_object_filter_result(result)
            case ObjectFilterError(message=message):
                self.status.configure(text=message)
            case unreachable:
                assert_never(unreachable)

    def _apply_object_filter_result(self, result: ObjectFilterResult) -> None:
        self._row_imgs = []
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
            mark = " 〔脚本〕" if ext == "script" else (" 〔原版〕" if ext == "base" else "")
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
