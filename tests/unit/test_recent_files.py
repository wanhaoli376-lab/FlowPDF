from __future__ import annotations

from PySide6.QtCore import QSettings

from flowpdf.services.recent_files import RecentFiles


def test_recent_files_are_unicode_safe_deduplicated_and_bounded(tmp_path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    recent = RecentFiles(settings, limit=3)
    paths = [tmp_path / f"报告 {index}.pdf" for index in range(4)]
    for path in paths:
        path.write_bytes(b"pdf")
        recent.add(path)
    recent.add(paths[2])

    assert recent.paths() == [paths[2].resolve(), paths[3].resolve(), paths[1].resolve()]


def test_recent_files_drop_missing_entries(tmp_path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    recent = RecentFiles(settings)
    existing = tmp_path / "exists.pdf"
    missing = tmp_path / "missing.pdf"
    existing.write_bytes(b"pdf")
    recent.add(missing)
    recent.add(existing)

    assert recent.paths() == [existing.resolve()]


def test_recent_files_treat_qsettings_invalid_value_as_empty(tmp_path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("recent/files", None)

    assert RecentFiles(settings).paths() == []
