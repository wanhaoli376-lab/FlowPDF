from __future__ import annotations

import pytest

from flowpdf.backends.base import TextStyle
from flowpdf.editing.text_editor import OverflowStrategy
from flowpdf.ui.dialogs.text_edit_dialog import TextEditDialog


def test_text_dialog_round_trips_supported_style_properties(qapp) -> None:
    style = TextStyle(
        font_family="Segoe UI",
        font_size=16.5,
        color=(0.1, 0.2, 0.3),
        background_color=(0.9, 0.8, 0.7),
        opacity=0.65,
        underline=True,
        alignment=2,
        overflow=OverflowStrategy.AUTO_SHRINK,
    )
    dialog = TextEditDialog(text="中英 Mixed", style=style)

    text, restored = dialog.text_and_style()

    assert text == "中英 Mixed"
    assert restored.font_size == pytest.approx(16.5)
    assert restored.opacity == pytest.approx(0.65)
    assert restored.underline is True
    assert restored.alignment == 2
    assert restored.overflow is OverflowStrategy.AUTO_SHRINK
    assert restored.background_color is not None
    dialog.close()
