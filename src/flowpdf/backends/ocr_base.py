from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from flowpdf.utils.coordinates import Rect


class OcrUnavailableError(RuntimeError):
    """No optional local OCR adapter is installed."""


@dataclass(frozen=True, slots=True)
class OcrText:
    text: str
    rect: Rect
    confidence: float


class OcrBackend(ABC):
    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def recognize_page(self, image: bytes) -> list[OcrText]:
        raise NotImplementedError

    @abstractmethod
    def recognize_region(self, image: bytes, rect: Rect) -> list[OcrText]:
        raise NotImplementedError


class UnavailableOcrBackend(OcrBackend):
    def is_available(self) -> bool:
        return False

    def recognize_page(self, image: bytes) -> list[OcrText]:
        raise OcrUnavailableError("需要安装可选 OCR 组件后才能识别此页面")

    def recognize_region(self, image: bytes, rect: Rect) -> list[OcrText]:
        raise OcrUnavailableError("需要安装可选 OCR 组件后才能识别此区域")
