from dataclasses import dataclass, field
from datetime import UTC, datetime


class BudgetExceededError(RuntimeError):
    """Raised before an Agent exceeds a configured execution budget."""


@dataclass(slots=True)
class ExecutionBudget:
    max_model_turns: int = 8
    max_tool_calls: int = 12
    max_run_seconds: int = 180
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    model_turns: int = 0
    tool_calls: int = 0

    def consume_model_turn(self) -> None:
        self._assert_time_remaining()
        if self.model_turns >= self.max_model_turns:
            raise BudgetExceededError("Model turn budget exceeded")
        self.model_turns += 1

    def consume_tool_call(self) -> None:
        self._assert_time_remaining()
        if self.tool_calls >= self.max_tool_calls:
            raise BudgetExceededError("Tool call budget exceeded")
        self.tool_calls += 1

    def _assert_time_remaining(self) -> None:
        elapsed = (datetime.now(UTC) - self.started_at).total_seconds()
        if elapsed >= self.max_run_seconds:
            raise BudgetExceededError("Run time budget exceeded")
