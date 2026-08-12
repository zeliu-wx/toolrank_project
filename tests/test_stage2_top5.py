from __future__ import annotations

import json

import pytest

from toolrank.assignment_evidence import MAX_COMPLEMENT_CANDIDATES
from toolrank.cego import _prompt_payload, assemble_decision
from toolrank.checker import check_decision
from toolrank.dace_rag import build_action_evidence_matrix
from toolrank.schemas_v2 import RecallCoverageEntry, Step2DecisionCertificate
from tests.stage1_fixtures import tool_entry
from tests.stage2_fixtures import budget, stage2_context


def _seven_candidate_context():
    context = stage2_context(
        primary_rate=0.0,
        primary_n_eff=100.0,
        peer_rate=0.90,
        peer_n_eff=100.0,
    )
    rates = {
        "d": 0.88,
        "e": 0.86,
        "f": 0.84,
        "g": 0.82,
        "h": 0.80,
        "i": 0.78,
    }
    context.stage1.tool_table.extend(
        tool_entry(tool, runtime=1.0) for tool in [*rates, "j"]
    )
    context.recall_coverage.matrix.extend(
        RecallCoverageEntry(
            tool=tool,
            category="reentrancy",
            R_hat=rate,
            n_eff=100.0,
            support_level="eligible",
        )
        for tool, rate in rates.items()
    )
    context.recall_coverage.matrix.append(
        RecallCoverageEntry(
            tool="j",
            category="reentrancy",
            R_hat=0.99,
            n_eff=14.99,
            support_level="under_evidenced",
        )
    )
    return context


def test_seven_eligible_candidates_are_ranked_and_capped_at_five() -> None:
    context = _seven_candidate_context()
    matrix = build_action_evidence_matrix(
        context,
        budget(slots=8, runtime=20.0),
    )
    panel = matrix.ownership_panel["reentrancy"]

    assert MAX_COMPLEMENT_CANDIDATES == 5
    assert [candidate.tool for candidate in panel.eligible_candidates] == [
        "b",
        "d",
        "e",
        "f",
        "g",
    ]
    assert [
        candidate.tool for candidate in panel.not_shortlisted_candidates
    ] == ["h", "i"]
    assert all(
        candidate.eligibility == "not_shortlisted"
        for candidate in panel.not_shortlisted_candidates
    )
    row_status = {
        row.tool: row.ownership_eligibility
        for row in matrix.relevant_matrix_rows
        if row.category == "reentrancy"
    }
    assert row_status["h"] == "NOT_SHORTLISTED"
    assert row_status["i"] == "NOT_SHORTLISTED"

    prompt = json.loads(
        _prompt_payload(context, matrix, None, w_recall=0.5, w_precision=0.5)
    )
    assert [
        candidate["tool"]
        for candidate in prompt["required_categories"][0]["eligible_candidates"]
    ] == ["b", "d", "e", "f", "g"]


def test_under_evidenced_high_rate_candidate_does_not_consume_a_slot() -> None:
    context = _seven_candidate_context()
    matrix = build_action_evidence_matrix(
        context,
        budget(slots=8, runtime=20.0),
    )
    panel = matrix.ownership_panel["reentrancy"]

    assert "j" not in {
        candidate.tool for candidate in panel.eligible_candidates
    }
    assert panel.eligible_candidates[-1].tool == "g"
    assert next(
        candidate for candidate in panel.under_evidenced_candidates
        if candidate.tool == "j"
    ).n_eff == 14.99


def test_proposal_of_sixth_candidate_is_ignored_and_primary_is_retained() -> None:
    context = _seven_candidate_context()
    limit = budget(slots=8, runtime=20.0)
    matrix = build_action_evidence_matrix(context, limit)
    certificate = assemble_decision(
        {
            "complements": [
                {
                    "category": "reentrancy",
                    "tool": "h",
                    "evidence_refs": ["ev_rcov_h_reentrancy"],
                }
            ]
        },
        context,
        matrix,
        limit,
    )

    assert certificate.selected_action_id == "run_primary"
    assert certificate.selected_plan[0].tool == "a"
    assert certificate.category_assignments[0].owner_tools == ["a"]
    assert check_decision(certificate, context, matrix).status == "ACCEPT"


def test_checker_rejects_a_forged_overflow_complement() -> None:
    context = _seven_candidate_context()
    limit = budget(slots=8, runtime=20.0)
    matrix = build_action_evidence_matrix(context, limit)
    payload = assemble_decision({}, context, matrix, limit).model_dump(mode="json")
    payload.update(
        {
            "decision_type": "PLAN_COMPOSITION",
            "selected_action_id": "plan_composition",
            "selected_plan": [
                {
                    "tool": "a",
                    "role": "STARTER",
                    "execution_order": 1,
                    "reason_codes": ["STAGE1_PRIMARY"],
                },
                {
                    "tool": "h",
                    "role": "COMPLEMENT",
                    "execution_order": 1,
                    "reason_codes": ["CATEGORY_COMPLEMENT"],
                },
            ],
            "category_assignments": [
                {
                    "category": "reentrancy",
                    "owner_tools": ["a", "h"],
                    "complement_tool": "h",
                    "status": "COMPLEMENT_ADDED",
                    "for_claims": [
                        {
                            "claim": "Forge overflow candidate",
                            "evidence_refs": ["ev_rcov_h_reentrancy"],
                        }
                    ],
                }
            ],
        }
    )
    certificate = Step2DecisionCertificate.model_validate(payload)

    verdict = check_decision(certificate, context, matrix)

    assert verdict.status == "REJECT"
    assert (
        "COMPLEMENT_NOT_IN_ELIGIBLE_PANEL:reentrancy:h"
        in verdict.rule_failures
    )


def test_tied_candidates_use_tool_id_as_the_final_shortlist_key() -> None:
    context = _seven_candidate_context()
    rows = {
        row.tool: row
        for row in context.recall_coverage.matrix
        if row.category == "reentrancy"
    }
    rows["e"].R_hat = rows["d"].R_hat
    rows["e"].n_eff = rows["d"].n_eff

    panel = build_action_evidence_matrix(
        context,
        budget(slots=8, runtime=20.0),
    ).ownership_panel["reentrancy"]

    tools = [candidate.tool for candidate in panel.eligible_candidates]
    assert tools.index("d") < tools.index("e")


def test_schema_rejects_more_than_five_legal_candidates() -> None:
    context = _seven_candidate_context()
    matrix = build_action_evidence_matrix(
        context,
        budget(slots=8, runtime=20.0),
    )
    payload = matrix.model_dump(mode="json")
    panel = payload["ownership_panel"]["reentrancy"]
    sixth = panel["not_shortlisted_candidates"].pop(0)
    sixth["eligibility"] = "eligible"
    panel["eligible_candidates"].append(sixth)

    with pytest.raises(ValueError, match="at most 5"):
        type(matrix).model_validate(payload)


def test_schema_rejects_partition_and_matrix_row_mismatches() -> None:
    context = _seven_candidate_context()
    matrix = build_action_evidence_matrix(
        context,
        budget(slots=8, runtime=20.0),
    )

    partition_payload = matrix.model_dump(mode="json")
    partition_payload["ownership_panel"]["reentrancy"][
        "not_shortlisted_candidates"
    ][0]["eligibility"] = "eligible"
    with pytest.raises(ValueError, match="match its partition"):
        type(matrix).model_validate(partition_payload)

    ranking_payload = matrix.model_dump(mode="json")
    ranking_panel = ranking_payload["ownership_panel"]["reentrancy"]
    fifth = ranking_panel["eligible_candidates"].pop()
    sixth = ranking_panel["not_shortlisted_candidates"].pop(0)
    fifth["eligibility"] = "not_shortlisted"
    sixth["eligibility"] = "eligible"
    ranking_panel["eligible_candidates"].append(sixth)
    ranking_panel["not_shortlisted_candidates"].insert(0, fifth)
    with pytest.raises(ValueError, match="highest-ranked shortlist"):
        type(matrix).model_validate(ranking_payload)

    row_payload = matrix.model_dump(mode="json")
    row = next(
        item
        for item in row_payload["relevant_matrix_rows"]
        if item["category"] == "reentrancy" and item["tool"] == "h"
    )
    row["ownership_eligibility"] = "ELIGIBLE"
    with pytest.raises(ValueError, match="differs from its panel partition"):
        type(matrix).model_validate(row_payload)


def test_checker_rebuilds_the_canonical_shortlist_before_accepting() -> None:
    context = _seven_candidate_context()
    limit = budget(slots=8, runtime=20.0)
    matrix = build_action_evidence_matrix(context, limit)
    payload = matrix.model_dump(mode="json")
    panel = payload["ownership_panel"]["reentrancy"]

    highest = panel["eligible_candidates"].pop(0)
    promoted = panel["not_shortlisted_candidates"].pop(0)
    highest["eligibility"] = "ineligible"
    promoted["eligibility"] = "eligible"
    panel["eligible_candidates"].append(promoted)
    panel["rejected_candidates"].append(highest)
    for row in payload["relevant_matrix_rows"]:
        if row["category"] != "reentrancy":
            continue
        if row["tool"] == "b":
            row["ownership_eligibility"] = "INELIGIBLE"
        elif row["tool"] == "h":
            row["ownership_eligibility"] = "ELIGIBLE"

    forged_matrix = type(matrix).model_validate(payload)
    certificate = assemble_decision(
        {
            "complements": [
                {
                    "category": "reentrancy",
                    "tool": "h",
                    "evidence_refs": ["ev_rcov_h_reentrancy"],
                }
            ]
        },
        context,
        forged_matrix,
        limit,
    )

    verdict = check_decision(certificate, context, forged_matrix)

    assert verdict.status == "REJECT"
    assert "OWNERSHIP_PANEL_NOT_CANONICAL:reentrancy" in verdict.rule_failures
    assert (
        "COMPLEMENT_NOT_IN_ELIGIBLE_PANEL:reentrancy:h"
        in verdict.rule_failures
    )
