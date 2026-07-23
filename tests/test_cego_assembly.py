from __future__ import annotations

from toolrank.cego import assemble_decision, build_primary_only_certificate
from toolrank.dace_rag import build_action_evidence_matrix
from tests.stage2_fixtures import budget, stage2_context


def test_complement_is_added_without_replacing_primary() -> None:
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

    assert certificate.selected_action_id == "plan_composition"
    assert certificate.category_assignments[0].owner_tools == ["a", "b"]
    assert certificate.category_assignments[0].status == "COMPLEMENT_ADDED"


def test_invalid_or_absent_complement_keeps_primary() -> None:
    context = stage2_context()
    limit = budget()
    matrix = build_action_evidence_matrix(context, limit)
    certificate = assemble_decision(
        {"complements": [{"category": "reentrancy", "tool": "c", "evidence_refs": []}]},
        context,
        matrix,
        limit,
    )
    assert certificate.selected_action_id == "run_primary"
    assert certificate.category_assignments[0].owner_tools == ["a"]

    fallback = build_primary_only_certificate(context, matrix, limit)
    assert fallback.category_assignments[0].owner_tools == ["a"]
