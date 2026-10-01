from datetime import UTC, datetime, timedelta

import pytest

from opspilot.agent.budget import BudgetExceededError, ExecutionBudget


def test_model_turn_limit_is_enforced_before_overrun() -> None:
    budget = ExecutionBudget(max_model_turns=1)
    budget.consume_model_turn()

    with pytest.raises(BudgetExceededError, match="Model turn"):
        budget.consume_model_turn()


def test_tool_call_limit_is_enforced_before_overrun() -> None:
    budget = ExecutionBudget(max_tool_calls=1)
    budget.consume_tool_call()

    with pytest.raises(BudgetExceededError, match="Tool call"):
        budget.consume_tool_call()


def test_runtime_limit_is_enforced() -> None:
    budget = ExecutionBudget(
        max_run_seconds=1,
        started_at=datetime.now(UTC) - timedelta(seconds=2),
    )

    with pytest.raises(BudgetExceededError, match="Run time"):
        budget.consume_tool_call()
