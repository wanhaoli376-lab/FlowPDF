from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import QSettings


class Theme(StrEnum):
    LIGHT = "light"
    DARK = "dark"


class SettingsService:
    def __init__(self, settings: QSettings | None = None) -> None:
        self.settings = settings or QSettings()

    @property
    def cache_limit_mb(self) -> int:
        value = int(self.settings.value("render/cache_mb", 512))
        return max(64, min(4096, value))

    @cache_limit_mb.setter
    def cache_limit_mb(self, value: int) -> None:
        self.settings.setValue("render/cache_mb", max(64, min(4096, int(value))))

    @property
    def theme(self) -> Theme:
        try:
            return Theme(str(self.settings.value("appearance/theme", Theme.LIGHT.value)))
        except ValueError:
            return Theme.LIGHT

    @theme.setter
    def theme(self, value: Theme) -> None:
        self.settings.setValue("appearance/theme", value.value)

    def sync(self) -> None:
        self.settings.sync()
