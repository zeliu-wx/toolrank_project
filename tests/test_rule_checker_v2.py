from __future__ import annotations

from toolrank.cego import assemble_decision
from toolrank.checker import check_decision
from toolrank.dace_rag import build_action_evidence_matrix
from tests.stage2_fixtures import budget, stage2_context


def test_checker_accepts_grounded_additive_complement() -> None:
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
    assert check_decision(certificate, context, matrix).status == "ACCEPT"


def test_checker_rejects_changed_primary() -> None:
    context = stage2_context()
    limit = budget()
    matrix = build_action_evidence_matrix(context, limit)
    certificate = assemble_decision({}, context, matrix, limit).model_copy(update={"primary_tool": "b"})
    verdict = check_decision(certificate, context, matrix)
    assert "PRIMARY_TOOL_NOT_STAGE1_PRIMARY" in verdict.rule_failures


def test_checker_recomputes_candidate_strength_as_defense_in_depth() -> None:
    context = stage2_context(
        primary_rate=0.2,
        primary_n_eff=100.0,
        peer_rate=0.8,
        peer_n_eff=100.0,
    )
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

    weakened_context = context.model_copy(deep=True)
    for row in weakened_context.recall_coverage.matrix:
        if row.tool == "a":
            row.R_hat = 0.9
        elif row.tool == "b":
            row.R_hat = 0.8

    verdict = check_decision(certificate, weakened_context, matrix)
    assert (
        "COMPLEMENT_NOT_EVIDENCE_STRONGER_THAN_PRIMARY:reentrancy:b"
        in verdict.rule_failures
    )
