"""Retained GUI map sources close after their final background reader exits."""

from __future__ import annotations

from collections.abc import Callable, Iterable
import logging
import threading

from .map_data import MapData

_LOGGER = logging.getLogger(__name__)


def map_family(maps: Iterable[MapData]) -> tuple[MapData, ...]:
    """Collect complete source families once without assuming a depth bound."""
    pending = list(maps)
    result: dict[int, MapData] = {}
    while pending:
        md = pending.pop()
        if id(md) in result:
            continue
        result[id(md)] = md
        pending.extend(md.sub_maps)
    return tuple(result.values())


def close_gui_maps(maps: Iterable[MapData]) -> None:
    """Release all owned sources even if one source's close operation fails."""
    for md in map_family(maps):
        try:
            md.close()
        except (
            Exception
        ):  # BROAD_EXCEPT_OK - a source cleanup failure cannot strand other GUI maps.
            _LOGGER.exception("GUI map source cleanup failed")


class GuiMapResources:
    """Own loaded maps while navigation or a worker still needs their sources."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owned: dict[int, MapData] = {}
        self._retired: dict[int, MapData] = {}
        self._borrowed: dict[int, int] = {}

    def remember(self, maps: Iterable[MapData]) -> None:
        with self._lock:
            self._owned.update((id(md), md) for md in maps)

    def acquire(self, md: MapData) -> Callable[[], None]:
        family = tuple(id(item) for item in map_family((md,)))
        with self._lock:
            self._owned[id(md)] = md
            for key in family:
                self._borrowed[key] = self._borrowed.get(key, 0) + 1
        released = False

        def release() -> None:
            nonlocal released
            with self._lock:
                if released:
                    return
                released = True
                for key in family:
                    count = self._borrowed[key] - 1
                    if count:
                        self._borrowed[key] = count
                    else:
                        del self._borrowed[key]
                ready = self._take_closeable()
            close_gui_maps(ready)

        return release

    def synchronize(self, retained: Iterable[MapData]) -> None:
        wanted = {id(md) for md in map_family(retained)}
        with self._lock:
            for key, md in tuple(self._owned.items()):
                if any(id(item) in wanted for item in map_family((md,))):
                    continue
                self._retired[key] = self._owned.pop(key)
            ready = self._take_closeable()
        close_gui_maps(ready)

    def close(self) -> None:
        with self._lock:
            self._retired.update(self._owned)
            self._owned.clear()
            ready = self._take_closeable()
        close_gui_maps(ready)

    def _take_closeable(self) -> tuple[MapData, ...]:
        ready = []
        for key, md in tuple(self._retired.items()):
            if not any(id(item) in self._borrowed for item in map_family((md,))):
                ready.append(self._retired.pop(key))
        return tuple(ready)
