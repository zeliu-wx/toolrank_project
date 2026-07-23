"""Translate a checked Stage 2 certificate into a Stage 3 execution plan."""

from __future__ import annotations

from toolrank.schemas import CompositionPlan
from toolrank.schemas_v2 import Step2DecisionCertificate


def composition_from_certificate(
    certificate: Step2DecisionCertificate,
) -> CompositionPlan:
    selected = [
        item.tool
        for item in sorted(certificate.selected_plan, key=lambda item: item.execution_order)
    ]
    selected = list(dict.fromkeys(selected))
    primary = certificate.primary_tool
    if primary in selected:
        selected.remove(primary)
    selected.insert(0, primary)
    owners = {
        assignment.category: list(assignment.owner_tools)
        for assignment in certificate.category_assignments
    }
    return CompositionPlan(
        selected_tool_ids=selected,
        primary_tool_id=primary,
        complementary_tool_ids=[tool for tool in selected if tool != primary],
        estimated_plan_runtime_minutes=(
            certificate.budget.estimated_use.runtime_cap_minutes
        ),
        execution_schedule=certificate.budget.limit.execution_schedule,
        category_owners=owners,
        rationale=certificate.short_summary,
    )
