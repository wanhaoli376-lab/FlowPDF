from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from tests.generate_test_pdfs import generate_test_pdfs

from flowpdf.backends.pymupdf_backend import PyMuPdfBackend
from flowpdf.rendering.render_scheduler import RenderPriority, RenderScheduler, RenderSource
from flowpdf.rendering.tile_cache import MemoryBoundLruCache, TileKey


def run_benchmark() -> dict[str, object]:
    QCoreApplication.instance() or QCoreApplication(["flowpdf-benchmark"])
    with tempfile.TemporaryDirectory(prefix="flowpdf-benchmark-") as temporary:
        root = Path(temporary)
        fixtures = generate_test_pdfs(root / "fixtures", include_stress=True)
        source_path = fixtures["stress"]
        backend = PyMuPdfBackend()

        started = time.perf_counter()
        backend.open_document(source_path)
        open_seconds = time.perf_counter() - started

        started = time.perf_counter()
        first_page = backend.render_page(0, 1.0)
        first_page_seconds = time.perf_counter() - started

        cache = MemoryBoundLruCache(
            max_bytes=512 * 1024 * 1024,
            size_of=lambda rendered: rendered.byte_size,
        )
        started = time.perf_counter()
        for page_index in range(backend.page_count()):
            rendered = backend.render_page(page_index, 0.12)
            cache.put(
                TileKey(backend.document_id, page_index, 0.12, 0, None, 0, "benchmark"),
                rendered,
            )
        thumbnail_seconds = time.perf_counter() - started

        started = time.perf_counter()
        span_count = sum(
            len(backend.extract_text_spans(index)) for index in range(backend.page_count())
        )
        extraction_seconds = time.perf_counter() - started

        snapshot = RenderSource(backend.document_id, backend.document_bytes())
        scheduler = RenderScheduler(max_cache_bytes=16 * 1024 * 1024, max_threads=1)
        keys = [
            TileKey(backend.document_id, index, 0.12, 0, None, 0, "queue-baseline")
            for index in range(backend.page_count())
        ]
        for key in keys:
            scheduler.request(
                snapshot,
                key,
                owner="scroll-simulation",
                priority=RenderPriority.PRELOAD,
            )
        maximum_queue = scheduler.pending_count
        scheduler.cancel_owner_obsolete("scroll-simulation", {keys[150]})
        queue_after_jump = scheduler.pending_count
        scheduler.shutdown()

        started = time.perf_counter()
        backend.save_document(root / "saved.pdf")
        save_seconds = time.perf_counter() - started
        backend.close_document()

        return {
            "environment": {
                "python": sys.version.split()[0],
                "platform": sys.platform,
                "cpu_count": os.cpu_count(),
            },
            "fixture": {"pages": 300, "source_bytes": source_path.stat().st_size},
            "seconds": {
                "open_document": round(open_seconds, 6),
                "first_page_render": round(first_page_seconds, 6),
                "all_thumbnails": round(thumbnail_seconds, 6),
                "extract_all_text": round(extraction_seconds, 6),
                "save_document": round(save_seconds, 6),
            },
            "render": {
                "first_page_bytes": first_page.byte_size,
                "thumbnail_cache_bytes": cache.current_bytes,
                "thumbnail_cache_limit_bytes": cache.max_bytes,
                "maximum_simulated_queue": maximum_queue,
                "queue_after_page_jump_cancellation": queue_after_jump,
            },
            "text_span_count": span_count,
            "process_peak_working_set_bytes": _peak_working_set(),
            "note": "当前开发机基线；不代表其他电脑的绝对性能。",
        }


def _peak_working_set() -> int | None:
    if sys.platform != "win32":
        return None

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ProcessMemoryCounters),
        ctypes.c_ulong,
    ]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    process = kernel32.GetCurrentProcess()
    succeeded = psapi.GetProcessMemoryInfo(
        process,
        ctypes.byref(counters),
        counters.cb,
    )
    return int(counters.PeakWorkingSetSize) if succeeded else None


def main() -> int:
    parser = argparse.ArgumentParser(description="记录 FlowPDF 当前机器性能基线")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_benchmark()
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
