from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from threading import RLock


@dataclass(frozen=True, slots=True)
class TileKey:
    """Every input that can change rendered pixels belongs in the cache key."""

    document_id: str
    page_index: int
    scale: float
    rotation: int
    tile: tuple[float, float, float, float] | None
    revision: int
    purpose: str = "page"


class MemoryBoundLruCache[K, V]:
    """Thread-safe LRU cache whose hard limit is measured in bytes.

    Oversized values are rejected without evicting useful existing entries. The
    return value of :meth:`put` reports both rejected and evicted keys so callers
    can release external resources if needed.
    """

    def __init__(self, *, max_bytes: int, size_of: Callable[[V], int]) -> None:
        if max_bytes <= 0:
            raise ValueError("缓存上限必须大于 0")
        self._max_bytes = max_bytes
        self._size_of = size_of
        self._items: OrderedDict[K, tuple[V, int]] = OrderedDict()
        self._current_bytes = 0
        self._lock = RLock()

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @property
    def current_bytes(self) -> int:
        with self._lock:
            return self._current_bytes

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            return key in self._items

    def __iter__(self) -> Iterator[K]:
        with self._lock:
            return iter(tuple(self._items))

    def get(self, key: K) -> V | None:
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            self._items.move_to_end(key)
            return entry[0]

    def peek(self, key: K) -> V | None:
        with self._lock:
            entry = self._items.get(key)
            return None if entry is None else entry[0]

    def put(self, key: K, value: V) -> list[K]:
        size = self._size_of(value)
        if size < 0:
            raise ValueError("缓存对象大小不能为负数")
        with self._lock:
            if size > self._max_bytes:
                return [key]

            previous = self._items.pop(key, None)
            if previous is not None:
                self._current_bytes -= previous[1]
            self._items[key] = (value, size)
            self._current_bytes += size

            evicted: list[K] = []
            while self._current_bytes > self._max_bytes:
                old_key, (_, old_size) = self._items.popitem(last=False)
                self._current_bytes -= old_size
                evicted.append(old_key)
            return evicted

    def remove(self, key: K) -> V | None:
        with self._lock:
            entry = self._items.pop(key, None)
            if entry is None:
                return None
            self._current_bytes -= entry[1]
            return entry[0]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._current_bytes = 0

    def resize(self, max_bytes: int) -> list[K]:
        if max_bytes <= 0:
            raise ValueError("缓存上限必须大于 0")
        with self._lock:
            self._max_bytes = max_bytes
            evicted: list[K] = []
            while self._current_bytes > self._max_bytes:
                key, (_, size) = self._items.popitem(last=False)
                self._current_bytes -= size
                evicted.append(key)
            return evicted
