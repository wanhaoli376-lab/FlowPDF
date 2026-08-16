from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from threading import RLock

# MuPDF / PyMuPDF is not thread-safe. Keep one process-wide re-entrant gate so
# independent backend instances and snapshot render jobs cannot enter it at the
# same time. The GUI remains asynchronous; only the native engine call is
# serialized.
PYMUPDF_LOCK = RLock()


def serialized_pymupdf[**P, R](
    function: Callable[P, R],
) -> Callable[P, R]:
    @wraps(function)
    def guarded(*args: P.args, **kwargs: P.kwargs) -> R:
        with PYMUPDF_LOCK:
            return function(*args, **kwargs)

    return guarded
