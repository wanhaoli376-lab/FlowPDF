from __future__ import annotations

from flowpdf.editing.text_editor import OverflowStrategy, layout_text
from flowpdf.utils.coordinates import Rect


def test_auto_shrink_reduces_font_until_text_fits() -> None:
    result = layout_text(
        "A moderately long line",
        Rect(0, 0, 100, 30),
        font_size=18,
        strategy=OverflowStrategy.AUTO_SHRINK,
        min_font_size=6,
    )

    assert 6 <= result.font_size < 18
    assert result.overflow is False


def test_wrap_keeps_font_size_and_breaks_text_into_lines() -> None:
    result = layout_text(
        "中文内容会自动换行",
        Rect(0, 0, 48, 100),
        font_size=12,
        strategy=OverflowStrategy.WRAP,
    )

    assert result.font_size == 12
    assert len(result.lines) >= 2
    assert "".join(result.lines) == "中文内容会自动换行"


def test_expand_grows_bottom_edge_to_contain_wrapped_text() -> None:
    original = Rect(10, 20, 80, 35)

    result = layout_text(
        "one two three four five six",
        original,
        font_size=12,
        strategy=OverflowStrategy.EXPAND,
    )

    assert result.rect.y0 == original.y0
    assert result.rect.y1 > original.y1
    assert result.overflow is False


def test_warn_preserves_size_and_reports_overflow() -> None:
    result = layout_text(
        "far too wide for this box",
        Rect(0, 0, 20, 10),
        font_size=14,
        strategy=OverflowStrategy.WARN,
    )

    assert result.font_size == 14
    assert result.overflow is True
