from __future__ import annotations

from pathlib import Path

from flowpdf.utils.fonts import FontResolver


def test_missing_font_uses_chinese_fallback_and_reports_replacement() -> None:
    warnings: list[str] = []
    resolver = FontResolver(
        {"Microsoft YaHei": Path("C:/Windows/Fonts/msyh.ttc")},
        warning_handler=warnings.append,
    )

    result = resolver.resolve("MissingSubset+Unknown", text="中文内容")

    assert result.family == "Microsoft YaHei"
    assert result.path == Path("C:/Windows/Fonts/msyh.ttc")
    assert result.replaced is True
    assert warnings and "已替换" in warnings[0]


def test_existing_font_matching_ignores_case_and_pdf_subset_prefix() -> None:
    resolver = FontResolver({"Arial": Path("C:/Windows/Fonts/arial.ttf")})

    result = resolver.resolve("ABCDEF+ARIAL", text="English")

    assert result.family == "Arial"
    assert result.replaced is False
    assert result.path.name == "arial.ttf"
