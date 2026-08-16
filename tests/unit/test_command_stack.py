from __future__ import annotations

from dataclasses import dataclass

import pytest

from flowpdf.editing.command import EditCommand
from flowpdf.editing.command_stack import CommandHistoryLimitError, CommandStack


@dataclass
class CounterCommand(EditCommand):
    state: dict[str, int]
    delta: int

    @property
    def description(self) -> str:
        return f"change by {self.delta}"

    def execute(self) -> None:
        self.state["value"] += self.delta

    def undo(self) -> None:
        self.state["value"] -= self.delta

    def serialize(self) -> dict[str, object]:
        return {"type": "counter", "delta": self.delta}


@dataclass
class WeightedCounterCommand(CounterCommand):
    retained_bytes: int

    @property
    def history_bytes(self) -> int:
        return self.retained_bytes


def test_command_stack_executes_undoes_and_redoes_through_one_interface() -> None:
    state = {"value": 0}
    stack = CommandStack()

    stack.push(CounterCommand(state, 3))
    stack.push(CounterCommand(state, 4))
    assert state["value"] == 7
    assert stack.undo_description == "change by 4"

    assert stack.undo() is True
    assert state["value"] == 3
    assert stack.redo() is True
    assert state["value"] == 7
    assert stack.serialize() == [
        {"type": "counter", "delta": 3},
        {"type": "counter", "delta": 4},
    ]


def test_new_command_after_undo_discards_redo_branch() -> None:
    state = {"value": 0}
    stack = CommandStack()
    stack.push(CounterCommand(state, 1))
    stack.push(CounterCommand(state, 2))
    stack.undo()

    stack.push(CounterCommand(state, 10))

    assert state["value"] == 11
    assert stack.can_redo is False
    assert stack.serialize() == [
        {"type": "counter", "delta": 1},
        {"type": "counter", "delta": 10},
    ]


def test_failed_command_is_not_added_to_history() -> None:
    class FailingCommand(CounterCommand):
        def execute(self) -> None:
            raise RuntimeError("boom")

    state = {"value": 0}
    stack = CommandStack()

    with pytest.raises(RuntimeError, match="boom"):
        stack.push(FailingCommand(state, 1))

    assert stack.can_undo is False
    assert state["value"] == 0


def test_history_evicts_oldest_snapshot_when_byte_budget_is_reached() -> None:
    state = {"value": 0}
    stack = CommandStack(max_history_bytes=6)

    stack.push(WeightedCounterCommand(state, 1, 4))
    stack.push(WeightedCounterCommand(state, 2, 4))

    assert stack.history_bytes == 4
    assert stack.serialize() == [
        {"type": "counter", "delta": 1},
        {"type": "counter", "delta": 2},
    ]
    assert stack.undo() is True
    assert state["value"] == 1
    assert stack.serialize() == [{"type": "counter", "delta": 1}]


def test_single_command_over_byte_budget_is_never_executed() -> None:
    state = {"value": 0}
    stack = CommandStack(max_history_bytes=3)

    with pytest.raises(CommandHistoryLimitError, match="内存上限"):
        stack.push(WeightedCounterCommand(state, 1, 4))

    assert state["value"] == 0
    assert stack.serialize() == []
