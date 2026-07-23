from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from toolrank.schemas_v2 import (
    BudgetProfile,
    BudgetUsage,
    CategoryAssignment,
    ForbiddenClaimsAttestation,
    SelectedToolEntry,
    Step2DecisionCertificate,
)


def budget_usage() -> BudgetUsage:
    limit = BudgetProfile(tool_slots=2, runtime_cap_minutes=10.0)
    used = BudgetProfile(tool_slots=1, runtime_cap_minutes=2.0)
    remaining = BudgetProfile(tool_slots=1, runtime_cap_minutes=8.0)
    return BudgetUsage(limit=limit, estimated_use=used, remaining_after_plan=remaining)


def test_category_assignment_is_additive_and_never_ownerless() -> None:
    primary_only = CategoryAssignment(category="reentrancy", owner_tools=["a"])
    assert primary_only.status == "PRIMARY_ONLY"
    assert primary_only.complement_tool is None

    complemented = CategoryAssignment(
        category="reentrancy",
        owner_tools=["a", "b"],
        complement_tool="b",
        status="COMPLEMENT_ADDED",
    )
    assert complemented.owner_tools == ["a", "b"]

    with pytest.raises(ValidationError):
        CategoryAssignment(category="reentrancy", owner_tools=[])


def test_certificate_rejects_legacy_action_type_and_has_no_legacy_fields() -> None:
    schema = Step2DecisionCertificate.model_json_schema()
    schema_text = json.dumps(schema)
    for legacy in (
        "RUN_ROBUST_SINGLE",
        "STOP_WITH_GAPS",
        "certified_primary",
        "candidate_set",
    ):
        assert legacy not in schema_text
    assert "tool_categories" not in schema["properties"]
    assert "owner_tool" not in schema["$defs"]["CategoryAssignment"]["properties"]

    with pytest.raises(ValidationError):
        Step2DecisionCertificate(
            decision_type="RUN_ROBUST_SINGLE",
            selected_action_id="legacy",
            selected_plan=[SelectedToolEntry(tool="a", role="STARTER", execution_order=1)],
            primary_tool="a",
            category_assignments=[],
            budget=budget_usage(),
            forbidden_claims_attestation=ForbiddenClaimsAttestation(),
        )
