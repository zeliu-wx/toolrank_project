from __future__ import annotations

from toolrank.dace_rag import build_action_evidence_matrix
from tests.stage2_fixtures import budget, stage2_context


def test_matrix_uses_shared_legal_action_ids_and_never_emits_legacy_actions() -> None:
    matrix = build_action_evidence_matrix(stage2_context(), budget())
    assert [(action.action_id, action.action_type) for action in matrix.actions] == [
        ("run_primary", "RUN_PRIMARY"),
        ("plan_composition", "PLAN_COMPOSITION"),
    ]
    assert matrix.ownership_panel["reentrancy"].assignment_status == "COMPLEMENT_AVAILABLE"
    assert [item.tool for item in matrix.ownership_panel["reentrancy"].eligible_candidates] == ["b"]


def test_unknown_runtime_complement_is_ineligible() -> None:
    matrix = build_action_evidence_matrix(stage2_context(b_runtime=None), budget())
    assert matrix.ownership_panel["reentrancy"].assignment_status == "PRIMARY_ONLY_NO_COMPLEMENT"
    assert matrix.ownership_panel["reentrancy"].eligible_candidates == []
