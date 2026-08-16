from __future__ import annotations

from collections.abc import Callable

from flowpdf.editing.command import EditCommand


class CommandStack:
    """Transactional undo/redo history for every document mutation."""

    def __init__(self, *, max_depth: int = 200) -> None:
        if max_depth <= 0:
            raise ValueError("撤销历史上限必须大于 0")
        self._commands: list[EditCommand] = []
        self._cursor = 0
        self._clean_cursor = 0
        self._max_depth = max_depth
        self._listeners: list[Callable[[], None]] = []
        self._revision = 0

    @property
    def can_undo(self) -> bool:
        return self._cursor > 0

    @property
    def can_redo(self) -> bool:
        return self._cursor < len(self._commands)

    @property
    def is_dirty(self) -> bool:
        return self._clean_cursor < 0 or self._cursor != self._clean_cursor

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def undo_description(self) -> str | None:
        return self._commands[self._cursor - 1].description if self.can_undo else None

    @property
    def redo_description(self) -> str | None:
        return self._commands[self._cursor].description if self.can_redo else None

    def add_listener(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    def push(self, command: EditCommand) -> None:
        command.execute()

        if self._cursor < len(self._commands):
            if self._clean_cursor > self._cursor:
                self._clean_cursor = -1
            del self._commands[self._cursor :]

        if self._commands and self._commands[-1].merge_with(command):
            self._revision += 1
            self._notify()
            return

        self._commands.append(command)
        self._cursor += 1
        if len(self._commands) > self._max_depth:
            overflow = len(self._commands) - self._max_depth
            del self._commands[:overflow]
            self._cursor -= overflow
            self._clean_cursor = max(-1, self._clean_cursor - overflow)
        self._revision += 1
        self._notify()

    def undo(self) -> bool:
        if not self.can_undo:
            return False
        command = self._commands[self._cursor - 1]
        command.undo()
        self._cursor -= 1
        self._revision += 1
        self._notify()
        return True

    def redo(self) -> bool:
        if not self.can_redo:
            return False
        command = self._commands[self._cursor]
        command.redo()
        self._cursor += 1
        self._revision += 1
        self._notify()
        return True

    def mark_clean(self) -> None:
        self._clean_cursor = self._cursor
        self._notify()

    def clear(self) -> None:
        self._commands.clear()
        self._cursor = 0
        self._clean_cursor = 0
        self._revision += 1
        self._notify()

    def serialize(self) -> list[dict[str, object]]:
        return [command.serialize() for command in self._commands[: self._cursor]]

    def _notify(self) -> None:
        for callback in tuple(self._listeners):
            callback()
