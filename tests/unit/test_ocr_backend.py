from __future__ import annotations

import pytest

from flowpdf.backends.ocr_base import OcrUnavailableError, UnavailableOcrBackend


def test_optional_ocr_backend_does_not_block_application_startup() -> None:
    backend = UnavailableOcrBackend()

    assert backend.is_available() is False
    with pytest.raises(OcrUnavailableError, match="可选 OCR"):
        backend.recognize_page(b"image")
