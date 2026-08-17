from __future__ import annotations

import re

from flowpdf.utils.fonts import FontResolver

_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
_ALIASES = {
    "simsun": "SimSun",
    "stsong": "SimSun",
    "songti": "SimSun",
    "microsoftyahei": "Microsoft YaHei",
    "msyh": "Microsoft YaHei",
    "arialmt": "Arial",
    "timesnewromanpsmt": "Times New Roman",
}


class ImportFontResolver:
    def __init__(self, resolver: FontResolver | None = None) -> None:
        self.warnings: list[str] = []
        self._resolver = resolver or FontResolver(warning_handler=self._record_warning)

    def resolve(self, pdf_font_name: str, text: str) -> str:
        stripped = _SUBSET_PREFIX.sub("", pdf_font_name).strip()
        alias_key = re.sub(r"[^a-z0-9]", "", stripped.casefold())
        requested = _ALIASES.get(alias_key, stripped)
        return self._resolver.resolve(requested, text=text).family

    def _record_warning(self, warning: str) -> None:
        if warning not in self.warnings:
            self.warnings.append(warning)
