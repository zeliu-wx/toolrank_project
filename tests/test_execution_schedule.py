from __future__ import annotations

from toolrank.plan_runtime import plan_runtime_minutes
from toolrank.schemas import ExecutionSchedule
from toolrank.schemas_v2 import BudgetProfile
from tests.stage1_fixtures import tool_entry


def test_default_timeout_is_runtime_budget_in_seconds() -> None:
    budget = BudgetProfile(tool_slots=2, runtime_cap_minutes=12.5)

    assert budget.execution_schedule.tool_timeout_seconds == 750.0
    assert budget.execution_schedule.timeout_source == "budget_default"


def test_plan_runtime_is_parallel_max_times_sequential_file_count() -> None:
    schedule = ExecutionSchedule(
        contract_count=3,
        execution_jobs=0,
        tool_timeout_seconds=600.0,
    )

    assert plan_runtime_minutes(
        ["a", "b"],
        [tool_entry("a", runtime=2.0), tool_entry("b", runtime=9.0)],
        schedule,
    ) == 27.0


def test_explicit_jobs_cap_makes_composition_illegal_but_primary_legal() -> None:
    schedule = ExecutionSchedule(
        contract_count=1,
        execution_jobs=1,
        tool_timeout_seconds=600.0,
        timeout_source="explicit",
    )
    table = [tool_entry("a", runtime=2.0), tool_entry("b", runtime=3.0)]

    assert plan_runtime_minutes(["a"], table, schedule) == 2.0
    assert plan_runtime_minutes(["a", "b"], table, schedule) is None


def test_explicit_short_timeout_rejects_tool_before_execution() -> None:
    schedule = ExecutionSchedule(
        contract_count=1,
        execution_jobs=0,
        tool_timeout_seconds=60.0,
        timeout_source="explicit",
    )

    assert plan_runtime_minutes(["a"], [tool_entry("a", runtime=2.0)], schedule) is None
