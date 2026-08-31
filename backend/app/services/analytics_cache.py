"""Process-local cache for derived portfolio analysis.

The encrypted database is intentionally single-process.  Its revision changes
after every successful mutation, which gives cached read models a simple and
safe invalidation boundary without persisting derived data.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Callable, TypeVar


T = TypeVar("T")


class AnalyticsCache:
    def __init__(self) -> None:
        self._entries: dict[str, tuple[int, object]] = {}

    def get(self, key: str, revision: int, build: Callable[[], T]) -> T:
        entry = self._entries.get(key)
        if entry and entry[0] == revision:
            return deepcopy(entry[1])  # callers may adjust response models
        value = build()
        self._entries[key] = (revision, deepcopy(value))
        return value

    def clear(self) -> None:
        self._entries.clear()


analytics_cache = AnalyticsCache()
