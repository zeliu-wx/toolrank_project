from __future__ import annotations

import json

from toolrank.cego import _prompt_payload
from toolrank.dace_rag import build_action_evidence_matrix
from toolrank.schemas_v2 import Passage
from tests.stage2_fixtures import budget, stage2_context


class FakeRetriever:
    def __init__(self, passage: Passage) -> None:
        self.passage = passage

    def retrieve(self, _tools, _categories, top_k=3):
        _ = top_k
        return [self.passage]


def test_applicable_owner_ineligible_evidence_blocks_complement() -> None:
    passage = Passage(
        passage_id="hard_b_reentrancy",
        source_id="official_b_docs",
        owner_tool="b",
        category="reentrancy",
        knowledge_kind="hard_scheduling_rule",
        action_scope=["SINGLE_TOOL", "PLAN_COMPOSITION", "CONTINUE_HEDGE"],
        relation_to_owner="owner_ineligible",
        evidence_basis="official_documentation",
        source_reliability="official_tool_doc",
        claim_text="Tool b cannot process this target configuration.",
        source_excerpt="Official documentation states this unsupported configuration.",
    )
    matrix = build_action_evidence_matrix(
        stage2_context(),
        budget(),
        retriever=FakeRetriever(passage),
    )
    panel = matrix.ownership_panel["reentrancy"]
    assert panel.assignment_status == "PRIMARY_ONLY_NO_COMPLEMENT"
    rejected = next(item for item in panel.rejected_candidates if item.tool == "b")
    assert rejected.caveat_refs == ["hard_b_reentrancy"]


def test_soft_precision_risk_reaches_the_cego_candidate_prompt() -> None:
    passage = Passage(
        passage_id="risk_b_reentrancy",
        source_id="benchmark_paper",
        owner_tool="b",
        category="reentrancy",
        knowledge_kind="fp_precision_risk",
        action_scope=["PLAN_COMPOSITION"],
        relation_to_owner="opposes_owner",
        evidence_basis="benchmark_result",
        source_reliability="peer_reviewed",
        claim_text="Tool b produced category-specific false-positive risk.",
        source_excerpt="The benchmark reports false-positive risk for this category.",
    )
    context = stage2_context()
    matrix = build_action_evidence_matrix(
        context,
        budget(),
        retriever=FakeRetriever(passage),
    )
    candidate = matrix.ownership_panel["reentrancy"].eligible_candidates[0]
    assert candidate.caveat_refs == ["risk_b_reentrancy"]

    payload = json.loads(
        _prompt_payload(context, matrix, None, w_recall=0.5, w_precision=0.5)
    )
    evidence = payload["required_categories"][0]["eligible_candidates"][0][
        "matrix_row"
    ]["evidence_by_slot"]["AGAINST"]
    assert any(
        item["evidence_id"] == "risk_b_reentrancy"
        and item["decision_role"] == "oppose"
        for item in evidence
    )
