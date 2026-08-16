from __future__ import annotations

from flowpdf.rendering.tile_cache import MemoryBoundLruCache


def test_cache_evicts_least_recently_used_entries_to_stay_bounded() -> None:
    cache: MemoryBoundLruCache[str, bytes] = MemoryBoundLruCache(max_bytes=6, size_of=len)
    cache.put("old", b"111")
    cache.put("kept", b"22")
    assert cache.get("old") == b"111"

    evicted = cache.put("new", b"333")

    assert evicted == ["kept"]
    assert cache.get("kept") is None
    assert cache.get("old") == b"111"
    assert cache.get("new") == b"333"
    assert cache.current_bytes == 6


def test_replacing_and_oversized_values_do_not_leak_accounted_memory() -> None:
    cache: MemoryBoundLruCache[str, bytes] = MemoryBoundLruCache(max_bytes=4, size_of=len)
    cache.put("page", b"12")
    cache.put("page", b"123")

    accepted = cache.put("huge", b"12345")

    assert accepted == ["huge"]
    assert cache.current_bytes == 3
    assert len(cache) == 1
