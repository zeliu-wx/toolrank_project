from __future__ import annotations

from toolrank.plan_runtime import plan_runtime_minutes
from toolrank.schemas import ExecutionSchedule
from tests.stage1_fixtures import tool_entry


def test_plan_runtime_is_max_not_sum_for_one_contract() -> None:
    table = [tool_entry("a", runtime=4.0), tool_entry("b", runtime=9.0)]
    assert plan_runtime_minutes(["a", "b"], table, ExecutionSchedule()) == 9.0


def test_plan_runtime_is_unverifiable_when_any_runtime_is_unknown() -> None:
    table = [tool_entry("a", runtime=4.0), tool_entry("b", runtime=None)]
    assert plan_runtime_minutes(["a", "b"], table, ExecutionSchedule()) is None
