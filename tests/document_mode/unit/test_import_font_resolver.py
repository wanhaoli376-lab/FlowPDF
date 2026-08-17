from __future__ import annotations

from pathlib import Path

from flowpdf.document_mode.importing.font_resolver import ImportFontResolver
from flowpdf.utils.fonts import FontResolver


def test_import_font_resolver_strips_subset_prefix_and_uses_cjk_fallback() -> None:
    resolver = ImportFontResolver(
        FontResolver(
            {
                "SimSun": Path("C:/test/fonts/simsun.ttc"),
                "Segoe UI": Path("C:/test/fonts/segoeui.ttf"),
            }
        )
    )

    assert resolver.resolve("ABCDEE+SimSun", "中文") == "SimSun"
    assert resolver.resolve("ABCDEF+MissingCjkFont", "中文") == "SimSun"
