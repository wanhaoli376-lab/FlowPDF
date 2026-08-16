from __future__ import annotations

from abc import ABC, abstractmethod


class EditCommand(ABC):
    """The single history interface used by every editing tool."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Short, user-visible action description."""

    @abstractmethod
    def execute(self) -> None:
        """Apply the command for the first time."""

    @abstractmethod
    def undo(self) -> None:
        """Restore the state before the command."""

    def redo(self) -> None:
        """Apply the command again after undo."""
        self.execute()

    @abstractmethod
    def serialize(self) -> dict[str, object]:
        """Return a password- and content-safe recovery record."""

    def merge_with(self, newer: EditCommand) -> bool:
        """Optionally absorb a newer high-frequency edit such as object movement."""
        return False

    @property
    def history_bytes(self) -> int:
        """Approximate retained memory; non-snapshot commands cost no tracked bytes."""
        return 0
