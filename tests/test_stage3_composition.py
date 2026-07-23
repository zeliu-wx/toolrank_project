from __future__ import annotations

from toolrank.cego import assemble_decision
from toolrank.composition import composition_from_certificate
from toolrank.dace_rag import build_action_evidence_matrix
from tests.stage2_fixtures import budget, stage2_context


def test_certificate_becomes_additive_parallel_composition() -> None:
    context = stage2_context()
    limit = budget()
    matrix = build_action_evidence_matrix(context, limit)
    certificate = assemble_decision(
        {
            "complements": [
                {
                    "category": "reentrancy",
                    "tool": "b",
                    "evidence_refs": ["ev_rcov_b_reentrancy"],
                }
            ]
        },
        context,
        matrix,
        limit,
    )

    composition = composition_from_certificate(certificate)
    assert composition.primary_tool_id == "a"
    assert composition.selected_tool_ids == ["a", "b"]
    assert composition.category_owners == {"reentrancy": ["a", "b"]}
    assert composition.estimated_plan_runtime_minutes == 8.0
