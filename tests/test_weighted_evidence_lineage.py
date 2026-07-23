from __future__ import annotations

import json

import pytest

from toolrank.cego import _prompt_payload, assemble_decision
from toolrank.checker import check_decision
from toolrank.dace_rag import build_action_evidence_matrix
from toolrank.evidence_packet import build_stage2_context
from toolrank.scene_scoring import compute_scene_scores, select_primary
from toolrank.schemas_v2 import (
    BudgetProfile,
    Passage,
    Stage1EvidencePacket,
)
from tests.stage1_fixtures import (
    entry,
    knowledge_base,
    observation,
    scene_pool,
    tool_entry,
)


class FakeRetriever:
    def __init__(self, passages: list[Passage]) -> None:
        self.passages = passages

    def retrieve(self, _tools, _categories, top_k=3):
        _ = top_k
        return self.passages


def _context():
    kb = knowledge_base(
        [
            entry(
                "dataset_d1",
                [
                    observation("a", recall=0.9, precision=0.9, detected=1, total=5),
                    observation("b", recall=0.8, precision=0.8, detected=15, total=15),
                ],
            ),
            entry(
                "dataset_d2",
                [
                    observation("a", recall=0.9, precision=0.9, detected=1, total=5),
                    observation("b", recall=0.7, precision=0.7, detected=15, total=15),
                ],
            ),
        ]
    )
    pool = scene_pool(("dataset_d1", 0.7, 1.0), ("dataset_d2", 0.3, 1.0))
    table = [tool_entry("a", runtime=2.0), tool_entry("b", runtime=3.0)]
    scores = compute_scene_scores(pool, kb, ["a", "b"], 0.5, 0.5)
    selection = select_primary(pool, scores, table)
    stage1 = Stage1EvidencePacket(
        tool_table=table,
        scene_pool=pool,
        score_panel=scores,
        primary_selection=selection,
    )
    return build_stage2_context(stage1, kb, ["reentrancy"])


def _budget() -> BudgetProfile:
    return BudgetProfile(tool_slots=2, runtime_cap_minutes=10.0)


def _passage(
    passage_id: str,
    *,
    source_id: str,
    relation: str = "supports_owner",
    linked_evaluation_ids: list[str] | None = None,
    applicability_tags: list[str] | None = None,
) -> Passage:
    if relation == "owner_ineligible":
        return Passage(
            passage_id=passage_id,
            source_id=source_id,
            owner_tool="b",
            category="reentrancy",
            knowledge_kind="hard_scheduling_rule",
            action_scope=["SINGLE_TOOL", "PLAN_COMPOSITION", "CONTINUE_HEDGE"],
            applicability_tags=applicability_tags or [],
            relation_to_owner=relation,
            evidence_basis="official_documentation",
            source_reliability="official_tool_doc",
            claim_text="Tool b cannot process this target configuration.",
            source_excerpt="Official documentation states this unsupported configuration.",
            linked_evaluation_ids=linked_evaluation_ids,
        )
    negative = relation in {"opposes_owner", "owner_weaker"}
    return Passage(
        passage_id=passage_id,
        source_id=source_id,
        owner_tool="b",
        category="reentrancy",
        knowledge_kind="fp_precision_risk" if negative else "category_capability",
        action_scope=["PLAN_COMPOSITION"],
        applicability_tags=applicability_tags or [],
        relation_to_owner=relation,
        evidence_basis="benchmark_result",
        source_reliability="peer_reviewed",
        claim_text=(
            "Tool b has category-specific false-positive risk."
            if negative
            else "Tool b supports this vulnerability category."
        ),
        source_excerpt=(
            "The benchmark reports category-specific false-positive risk."
            if negative
            else "The benchmark reports category-specific detection capability."
        ),
        linked_evaluation_ids=linked_evaluation_ids,
    )


def _evaluation_ids(context) -> dict[str, str]:
    return {
        row.source_id: row.evaluation_id
        for row in context.stage1.score_panel.benchmark_scores
        if row.tool == "b"
    }


def _matrix(*passages: Passage):
    context = _context()
    matrix = build_action_evidence_matrix(
        context,
        _budget(),
        retriever=FakeRetriever(list(passages)),
    )
    return context, matrix


def _certificate(context, matrix, *refs: str):
    return assemble_decision(
        {
            "complements": [
                {
                    "category": "reentrancy",
                    "tool": "b",
                    "evidence_refs": list(refs),
                }
            ]
        },
        context,
        matrix,
        _budget(),
    )


def test_stage1_projection_preserves_scores_weights_metrics_and_stable_ids() -> None:
    context, matrix = _matrix()

    assert matrix.stage1_evidence.primary_tool == "a"
    assert set(matrix.stage1_evidence.tools) == {"a", "b"}
    assert matrix.stage1_evidence.benchmark_weights == {
        "dataset_d1_slice": 0.7,
        "dataset_d2_slice": 0.3,
    }
    tool_b = matrix.stage1_evidence.tools["b"]
    assert tool_b.S_t == pytest.approx(0.5)
    rows = {row.source_id: row for row in tool_b.benchmark_evaluations}
    assert set(rows) == {"dataset_d1", "dataset_d2"}
    assert rows["dataset_d1"].evaluation_id == "stage1_eval::b::dataset_d1_slice"
    assert rows["dataset_d1"].benchmark_id == "dataset_d1_slice"
    assert rows["dataset_d1"].dataset_id == "dataset_d1"
    assert rows["dataset_d1"].w_D == pytest.approx(0.7)
    assert rows["dataset_d1"].s_t_D == pytest.approx(0.5)
    assert rows["dataset_d1"].recall == pytest.approx(0.8)
    assert rows["dataset_d1"].precision == pytest.approx(0.8)
    assert context.stage1.primary_selection.primary_tool == "a"


def test_passages_preserve_explicit_zero_one_and_many_evaluation_links() -> None:
    context = _context()
    ids = _evaluation_ids(context)
    exact = _passage("passage_exact_d1", source_id="dataset_d1")
    many = _passage(
        "passage_many_rows",
        source_id="unrelated_source",
        linked_evaluation_ids=[ids["dataset_d1"], ids["dataset_d2"]],
    )
    explicit_zero = _passage(
        "passage_zero_rows",
        source_id="dataset_d1",
        linked_evaluation_ids=[],
    )
    fuzzy_only = _passage(
        "passage_fuzzy_source",
        source_id="dataset-d1",
    )
    _checked_context, matrix = _matrix(exact, many, explicit_zero, fuzzy_only)
    cards = {card.evidence_id: card for card in matrix.evidence_cards}

    assert cards[exact.passage_id].linked_evaluation_ids == [ids["dataset_d1"]]
    assert cards[exact.passage_id].benchmark_relevance_weight == pytest.approx(0.7)
    assert cards[many.passage_id].linked_evaluation_ids == [
        ids["dataset_d1"],
        ids["dataset_d2"],
    ]
    assert cards[many.passage_id].benchmark_relevance_weight is None
    assert cards[explicit_zero.passage_id].linked_evaluation_ids == []
    assert cards[explicit_zero.passage_id].benchmark_relevance_weight is None
    assert cards[fuzzy_only.passage_id].linked_evaluation_ids == []
    assert cards[fuzzy_only.passage_id].benchmark_relevance_weight is None

    by_id = {
        row.evaluation_id: row
        for tool in matrix.stage1_evidence.tools.values()
        for row in tool.benchmark_evaluations
    }
    assert by_id[ids["dataset_d1"]].linked_passage_ids == [exact.passage_id, many.passage_id]
    assert by_id[ids["dataset_d2"]].linked_passage_ids == [many.passage_id]


@pytest.mark.parametrize("invalid_link", ["missing_evaluation", "other_tool"])
def test_invalid_explicit_evaluation_link_fails_closed(invalid_link: str) -> None:
    context = _context()
    if invalid_link == "other_tool":
        evaluation_id = next(
            row.evaluation_id
            for row in context.stage1.score_panel.benchmark_scores
            if row.tool == "a"
        )
    else:
        evaluation_id = "stage1_eval::b::missing_benchmark"
    passage = _passage(
        "passage_invalid_link",
        source_id="unrelated_source",
        linked_evaluation_ids=[evaluation_id],
    )

    with pytest.raises(ValueError, match="explicit Stage 1 evaluation link"):
        build_action_evidence_matrix(
            context,
            _budget(),
            retriever=FakeRetriever([passage]),
        )


def test_duplicate_evidence_card_ids_fail_closed() -> None:
    passage = _passage(
        "ev_rcov_b_reentrancy",
        source_id="dataset_d1",
        linked_evaluation_ids=[],
    )

    with pytest.raises(ValueError, match="evidence card IDs must be unique"):
        build_action_evidence_matrix(
            _context(),
            _budget(),
            retriever=FakeRetriever([passage]),
        )


def test_noncanonical_stage1_evaluation_id_fails_closed() -> None:
    context = _context()
    payload = context.stage1.score_panel.benchmark_scores[0].model_dump()
    payload["evaluation_id"] = "stage1_eval::wrong::row"

    with pytest.raises(ValueError, match="evaluation ID must match"):
        type(context.stage1.score_panel.benchmark_scores[0]).model_validate(payload)


def test_cego_payload_carries_top_level_stage1_and_per_passage_lineage() -> None:
    context = _context()
    ids = _evaluation_ids(context)
    one = _passage("passage_payload_one", source_id="dataset_d1")
    many = _passage(
        "passage_payload_many",
        source_id="unrelated_source",
        linked_evaluation_ids=[ids["dataset_d1"], ids["dataset_d2"]],
    )
    unlinked = _passage(
        "passage_payload_none",
        source_id="dataset_d1",
        linked_evaluation_ids=[],
    )
    checked_context, matrix = _matrix(one, many, unlinked)

    payload = json.loads(
        _prompt_payload(
            checked_context,
            matrix,
            None,
            w_recall=0.5,
            w_precision=0.5,
        )
    )

    assert payload["stage1_evidence"]["primary_tool"] == "a"
    assert set(payload["stage1_evidence"]["tools"]) == {"a", "b"}
    assert payload["stage1_evidence"]["tools"]["a"]["S_t"] == pytest.approx(1.0)
    evidence = {
        item["id"]: item
        for item in payload["required_categories"][0]["eligible_candidates"][0]["evidence"]
    }
    assert evidence[one.passage_id]["evidence_type"] == "rag_passage"
    assert evidence[one.passage_id]["source"]["paper_id"] == "dataset_d1"
    assert evidence[one.passage_id]["benchmark_relevance_weight"] == pytest.approx(0.7)
    assert [row["evaluation_id"] for row in evidence[one.passage_id]["linked_evaluations"]] == [
        ids["dataset_d1"]
    ]
    assert [row["evaluation_id"] for row in evidence[many.passage_id]["linked_evaluations"]] == [
        ids["dataset_d1"],
        ids["dataset_d2"],
    ]
    assert [row["w_D"] for row in evidence[many.passage_id]["linked_evaluations"]] == [
        pytest.approx(0.7),
        pytest.approx(0.3),
    ]
    assert evidence[unlinked.passage_id]["linked_evaluations"] == []
    assert evidence[unlinked.passage_id]["benchmark_relevance_weight"] is None


def test_checker_uses_applicable_matrix_owned_relevance_weights() -> None:
    positive = _passage("passage_positive_d1", source_id="dataset_d1")
    negative = _passage(
        "passage_negative_d2",
        source_id="dataset_d2",
        relation="opposes_owner",
    )
    context, matrix = _matrix(positive, negative)
    certificate = _certificate(context, matrix, positive.passage_id)

    verdict = check_decision(certificate, context, matrix)

    assert verdict.status == "ACCEPT"


def test_checker_applies_applicability_symmetrically() -> None:
    inapplicable_positive = _passage(
        "passage_positive_wrong_solc",
        source_id="dataset_d1",
        applicability_tags=["solc:>=0.9.0"],
    )
    negative = _passage(
        "passage_negative_applies",
        source_id="dataset_d2",
        relation="opposes_owner",
    )
    context, matrix = _matrix(inapplicable_positive, negative)
    rejected = check_decision(
        _certificate(context, matrix, inapplicable_positive.passage_id),
        context,
        matrix,
    )
    assert "EVIDENCE_BALANCE_NOT_POSITIVE:reentrancy:b" in rejected.rule_failures

    positive = _passage("passage_positive_applies", source_id="dataset_d1")
    inapplicable_negative = _passage(
        "passage_negative_wrong_solc",
        source_id="dataset_d2",
        relation="opposes_owner",
        applicability_tags=["solc:>=0.9.0"],
    )
    context, matrix = _matrix(positive, inapplicable_negative)
    accepted = check_decision(
        _certificate(context, matrix, positive.passage_id),
        context,
        matrix,
    )
    assert accepted.status == "ACCEPT"


def test_unlinked_qualitative_passage_cannot_qualify_complement() -> None:
    unlinked = _passage(
        "passage_unlinked_only",
        source_id="dataset_d1",
        linked_evaluation_ids=[],
    )
    context, matrix = _matrix(unlinked)
    verdict = check_decision(
        _certificate(context, matrix, unlinked.passage_id),
        context,
        matrix,
    )

    assert "EVIDENCE_BALANCE_NOT_POSITIVE:reentrancy:b" in verdict.rule_failures


def test_model_supplied_weight_fields_cannot_override_matrix_values() -> None:
    positive = _passage("passage_matrix_weight", source_id="dataset_d1")
    negative = _passage(
        "passage_matrix_negative",
        source_id="dataset_d2",
        relation="opposes_owner",
    )
    context, matrix = _matrix(positive, negative)
    certificate = assemble_decision(
        {
            "complements": [
                {
                    "category": "reentrancy",
                    "tool": "b",
                    "evidence_refs": [positive.passage_id],
                    "w_D": 0.0,
                    "negative_weight": 999.0,
                }
            ]
        },
        context,
        matrix,
        _budget(),
    )

    assert check_decision(certificate, context, matrix).status == "ACCEPT"


def test_applicable_owner_ineligible_remains_a_hard_rejection() -> None:
    positive = _passage("passage_before_hard_block", source_id="dataset_d1")
    context, base_matrix = _matrix(positive)
    certificate = _certificate(context, base_matrix, positive.passage_id)
    hard = _passage(
        "passage_hard_block",
        source_id="dataset_d2",
        relation="owner_ineligible",
        linked_evaluation_ids=[],
    )
    checked_context, blocked_matrix = _matrix(positive, hard)

    verdict = check_decision(certificate, checked_context, blocked_matrix)

    assert "APPLICABLE_OWNER_INELIGIBLE:reentrancy:b" in verdict.rule_failures
    assert "APPLICABLE_OWNER_INELIGIBLE:reentrancy:b" in verdict.hard_failures
