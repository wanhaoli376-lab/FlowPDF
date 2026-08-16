from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")


@dataclass(frozen=True, slots=True)
class FontResolution:
    requested_family: str
    family: str
    path: Path | None
    replaced: bool


class FontResolver:
    """Resolve PDF font names to local files with deterministic CJK fallback."""

    _cjk_fallbacks = (
        "Microsoft YaHei",
        "Microsoft JhengHei",
        "SimSun",
        "Noto Sans CJK SC",
        "Noto Sans CJK TC",
        "Source Han Sans SC",
        "Arial Unicode MS",
    )
    _latin_fallbacks = ("Segoe UI", "Arial", "DejaVu Sans")

    def __init__(
        self,
        fonts: Mapping[str, Path] | None = None,
        *,
        warning_handler: Callable[[str], None] | None = None,
    ) -> None:
        available = dict(fonts) if fonts is not None else self.discover_system_fonts()
        self._fonts = {
            self._normalize(family): (family, Path(path)) for family, path in available.items()
        }
        self._warning_handler = warning_handler

    def resolve(self, requested_family: str | None, *, text: str = "") -> FontResolution:
        requested = requested_family or ""
        normalized = self._normalize(requested)
        match = self._fonts.get(normalized)
        if match is not None:
            return FontResolution(requested, match[0], match[1], False)

        fallback_names = self._cjk_fallbacks if contains_cjk(text) else self._latin_fallbacks
        fallback = next(
            (
                self._fonts[self._normalize(name)]
                for name in fallback_names
                if self._normalize(name) in self._fonts
            ),
            None,
        )
        if fallback is None and self._fonts:
            fallback = next(iter(self._fonts.values()))
        family, path = fallback if fallback is not None else ("Helvetica", None)
        resolution = FontResolution(requested, family, path, True)
        if self._warning_handler is not None:
            shown = requested or "未指定字体"
            self._warning_handler(f"字体“{shown}”不可用，已替换为“{family}”。")
        return resolution

    @classmethod
    def discover_system_fonts(cls) -> dict[str, Path]:
        windows_root = Path(
            os.environ.get("WINDIR") or os.environ.get("SYSTEMROOT") or "C:/Windows"
        )
        candidates = {
            "Microsoft YaHei": windows_root / "Fonts" / "msyh.ttc",
            "Microsoft JhengHei": windows_root / "Fonts" / "msjh.ttc",
            "SimSun": windows_root / "Fonts" / "simsun.ttc",
            "Segoe UI": windows_root / "Fonts" / "segoeui.ttf",
            "Arial": windows_root / "Fonts" / "arial.ttf",
            "Arial Unicode MS": windows_root / "Fonts" / "arialuni.ttf",
            "Noto Sans CJK SC": Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            "DejaVu Sans": Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        }
        return {family: path for family, path in candidates.items() if path.is_file()}

    @staticmethod
    def _normalize(family: str) -> str:
        stripped = _SUBSET_PREFIX.sub("", family.strip())
        return " ".join(stripped.split()).casefold()


def contains_cjk(text: str) -> bool:
    return any(
        "\u3400" <= character <= "\u9fff" or "\uf900" <= character <= "\ufaff" for character in text
    )
