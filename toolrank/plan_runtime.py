"""Shared paper-faithful plan-runtime accounting and executability checks."""

from __future__ import annotations

import math

from toolrank.schemas import ExecutionSchedule
from toolrank.schemas_v2 import BudgetProfile, BudgetUsage, ToolTableEntry


_ALERT_ORDER = {"low": 0, "medium": 1, "high": 2}


def planning_runtime_minutes(entry: ToolTableEntry) -> float | None:
    """Project one per-input planning duration without changing Stage 1 runtime."""
    if entry.family == "fuzz":
        campaign = entry.tool_cost.fuzz_campaign_budget
        return (
            campaign.allocated_runtime_seconds / 60.0
            if campaign is not None
            else None
        )
    return entry.tool_cost.expected_runtime_minutes


def plan_constraint_reasons(
    tools: list[str],
    tool_table: list[ToolTableEntry],
    schedule: ExecutionSchedule,
) -> list[str]:
    unique_tools = list(dict.fromkeys(tools))
    reasons: list[str] = []
    if schedule.execution_jobs != 0 and schedule.execution_jobs < len(unique_tools):
        reasons.append("INSUFFICIENT_EXECUTION_JOBS")
    table = {entry.tool: entry for entry in tool_table}
    for tool in unique_tools:
        entry = table.get(tool)
        if entry is None:
            reasons.append(f"TOOL_NOT_IN_TABLE:{tool}")
            continue
        campaign = entry.tool_cost.fuzz_campaign_budget
        if campaign is not None:
            if not math.isclose(
                campaign.allocated_runtime_seconds,
                schedule.tool_timeout_seconds,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                reasons.append(f"FUZZ_CAMPAIGN_TIMEOUT_MISMATCH:{tool}")
                continue
            if campaign.timeout_source != schedule.timeout_source:
                reasons.append(f"FUZZ_CAMPAIGN_TIMEOUT_SOURCE_MISMATCH:{tool}")
                continue
        runtime = planning_runtime_minutes(entry)
        if runtime is None:
            reasons.append(f"RUNTIME_UNKNOWN:{tool}")
        elif (
            campaign is None
            and schedule.timeout_source == "explicit"
            and runtime * 60.0 > schedule.tool_timeout_seconds
        ):
            reasons.append(f"TOOL_TIMEOUT_TOO_SHORT:{tool}")
    return reasons


def plan_runtime_minutes(
    tools: list[str],
    tool_table: list[ToolTableEntry],
    schedule: ExecutionSchedule,
) -> float | None:
    """Return ``max(per-contract runtime) * sequential contract count``.

    The paper's maximum rule is valid only when every selected tool has a
    worker. An explicit smaller job cap makes the composition ineligible.
    """
    unique_tools = list(dict.fromkeys(tools))
    if plan_constraint_reasons(unique_tools, tool_table, schedule):
        return None
    table = {entry.tool: entry for entry in tool_table}
    runtimes = [planning_runtime_minutes(table[tool]) for tool in unique_tools]
    return max((runtime for runtime in runtimes if runtime is not None), default=0.0) * schedule.contract_count


def estimated_budget(
    tools: list[str],
    tool_table: list[ToolTableEntry],
    schedule: ExecutionSchedule | None = None,
) -> BudgetProfile | None:
    unique_tools = list(dict.fromkeys(tools))
    resolved_schedule = schedule or ExecutionSchedule()
    runtime = plan_runtime_minutes(unique_tools, tool_table, resolved_schedule)
    if runtime is None:
        return None
    table = {entry.tool: entry for entry in tool_table}
    alert = "low"
    for tool in unique_tools:
        entry = table.get(tool)
        if entry is None:
            return None
        if _ALERT_ORDER[entry.tool_cost.alert_risk] > _ALERT_ORDER[alert]:
            alert = entry.tool_cost.alert_risk
    return BudgetProfile(
        tool_slots=len(unique_tools),
        runtime_cap_minutes=runtime,
        alert_cap=alert,
        execution_schedule=resolved_schedule,
    )


def budget_usage(
    tools: list[str],
    tool_table: list[ToolTableEntry],
    limit: BudgetProfile,
) -> BudgetUsage | None:
    if limit.execution_schedule is None:
        return None
    estimated = estimated_budget(tools, tool_table, limit.execution_schedule)
    if estimated is None:
        return None
    return BudgetUsage(
        limit=limit,
        estimated_use=estimated,
        remaining_after_plan=BudgetProfile(
            tool_slots=max(0, limit.tool_slots - estimated.tool_slots),
            runtime_cap_minutes=max(0.0, limit.runtime_cap_minutes - estimated.runtime_cap_minutes),
            alert_cap=limit.alert_cap,
            execution_schedule=limit.execution_schedule,
        ),
    )


def within_budget(estimated: BudgetProfile, limit: BudgetProfile) -> bool:
    return (
        estimated.tool_slots <= limit.tool_slots
        and estimated.runtime_cap_minutes <= limit.runtime_cap_minutes
        and _ALERT_ORDER[estimated.alert_cap] <= _ALERT_ORDER[limit.alert_cap]
    )
