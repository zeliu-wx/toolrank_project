from __future__ import annotations

import json

import pytest

from toolrank.cego import _prompt_payload, assemble_decision
from toolrank.checker import check_decision
from toolrank.dace_rag import build_action_evidence_matrix
from toolrank.evidence_packet import decide_primary_categories
from toolrank.schemas_v2 import (
    NominalToolScore,
    PrimaryAttention,
    PrimarySelection,
    RecallCoverageEntry,
    RecallCoverageMatrix,
    ScorePanel,
    Stage1EvidencePacket,
    Stage1Status,
    Stage2EvidenceContext,
)
from tests.stage1_fixtures import scene_pool, tool_entry
from tests.stage2_fixtures import budget, stage2_context


def _row(tool: str, rate: float | None, n_eff: float | None) -> RecallCoverageEntry:
    return RecallCoverageEntry(
        tool=tool,
        category="reentrancy",
        R_hat=rate,
        n_eff=n_eff,
        support_level="eligible" if rate and n_eff is not None and n_eff >= 15 else "under_evidenced",
    )


@pytest.mark.parametrize(
    ("primary_rows", "reason"),
    [
        ([], "PRIMARY_CATEGORY_ROW_MISSING"),
        ([_row("a", None, 15.0)], "PRIMARY_CATEGORY_RATE_MISSING"),
        ([_row("a", 0.0, 15.0)], "PRIMARY_CATEGORY_RATE_NON_POSITIVE"),
        ([_row("a", 0.5, 14.999)], "PRIMARY_N_EFF_BELOW_15"),
    ],
)
def test_primary_evidence_failures_open_search(primary_rows, reason: str) -> None:
    decision = decide_primary_categories(
        primary_rows,
        primary_tool="a",
        required_categories=["reentrancy"],
    )[0]

    assert decision.status == "SEARCH_REQUIRED"
    assert reason in decision.reason_codes


@pytest.mark.parametrize(
    ("n_eff", "classification", "reason"),
    [
        (None, "under_evidenced", "PRIMARY_N_EFF_MISSING"),
        (14.0, "under_evidenced", "PRIMARY_N_EFF_BELOW_15"),
        (15.0, "confirmed_weak", "PRIMARY_CATEGORY_RATE_NON_POSITIVE"),
    ],
)
def test_zero_rate_respects_evidence_strength_before_weakness(
    n_eff: float | None,
    classification: str,
    reason: str,
) -> None:
    decision = decide_primary_categories(
        [_row("a", 0.0, n_eff)],
        primary_tool="a",
        required_categories=["reentrancy"],
    )[0]

    assert decision.status == "SEARCH_REQUIRED"
    assert decision.evidence_classification == classification
    assert decision.reason_codes == [reason]


def test_n_eff_equal_to_15_is_primary_sufficient_without_credible_peer_gap() -> None:
    decision = decide_primary_categories(
        [_row("a", 0.8, 15.0), _row("b", 0.81, 15.0)],
        primary_tool="a",
        required_categories=["reentrancy"],
    )[0]

    assert decision.status == "PRIMARY_SUFFICIENT"
    assert decision.evidence_classification == "sufficient"


def test_count_qualified_credible_peer_gap_opens_search() -> None:
    decision = decide_primary_categories(
        [_row("a", 0.2, 100.0), _row("b", 0.8, 100.0)],
        primary_tool="a",
        required_categories=["reentrancy"],
    )[0]

    assert decision.status == "SEARCH_REQUIRED"
    assert decision.evidence_classification == "confirmed_weak"
    assert decision.credible_peer_tool == "b"
    assert "PEER_RECALL_CREDIBLY_HIGHER" in decision.reason_codes


def test_credible_stronger_candidate_remains_eligible_and_is_checked() -> None:
    context = stage2_context(
        primary_rate=0.2,
        primary_n_eff=100.0,
        peer_rate=0.8,
        peer_n_eff=100.0,
    )
    limit = budget()
    matrix = build_action_evidence_matrix(context, limit)

    candidate = matrix.ownership_panel["reentrancy"].eligible_candidates[0]
    assert candidate.tool == "b"
    assert candidate.strength.evidence_stronger is True
    assert candidate.strength.recall_gap_low is not None
    assert candidate.strength.recall_gap_low > 0.0

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


def test_primary_sufficient_category_exposes_no_complement_to_assembly() -> None:
    context = stage2_context(primary_rate=0.8, primary_n_eff=100.0, peer_rate=0.81, peer_n_eff=100.0)
    matrix = build_action_evidence_matrix(context, budget())

    panel = matrix.ownership_panel["reentrancy"]
    assert panel.primary_decision.status == "PRIMARY_SUFFICIENT"
    assert panel.assignment_status == "PRIMARY_SUFFICIENT"
    assert panel.eligible_candidates == []

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
        budget(),
    )
    assert certificate.category_assignments[0].owner_tools == ["a"]


def test_search_without_qualified_complement_retains_primary_explicitly() -> None:
    context = stage2_context(b_runtime=None)
    matrix = build_action_evidence_matrix(context, budget())

    panel = matrix.ownership_panel["reentrancy"]
    assert panel.primary_decision.status == "SEARCH_REQUIRED"
    assert panel.assignment_status == "PRIMARY_ONLY_NO_COMPLEMENT"
    assert panel.primary_only_reason


def test_under_evidenced_primary_opens_search_but_exposes_no_legal_complement() -> None:
    context = stage2_context(
        primary_rate=0.2,
        primary_n_eff=14.999,
        peer_rate=0.8,
        peer_n_eff=100.0,
    )
    limit = budget()
    matrix = build_action_evidence_matrix(context, limit)
    panel = matrix.ownership_panel["reentrancy"]

    assert panel.primary_decision.status == "SEARCH_REQUIRED"
    assert panel.assignment_status == "PRIMARY_ONLY_NO_COMPLEMENT"
    assert panel.primary_only_reason == "PRIMARY_COMPARISON_BASELINE_UNRELIABLE"
    assert panel.eligible_candidates == []
    candidate = next(item for item in panel.rejected_candidates if item.tool == "b")
    assert candidate.strength.primary_baseline_reliable is False
    assert candidate.strength.evidence_stronger is False

    payload = json.loads(
        _prompt_payload(context, matrix, None, w_recall=0.5, w_precision=0.5)
    )
    assert payload["required_categories"][0]["eligible_candidates"] == []

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
    assert certificate.category_assignments[0].owner_tools == ["a"]
    assert check_decision(certificate, context, matrix).status == "ACCEPT"


def _real_arithmetic_context() -> Stage2EvidenceContext:
    category = "arithmetic"
    rows = [
        RecallCoverageEntry(
            tool="slither",
            category=category,
            R_hat=0.005064,
            n_eff=662.0,
            support_level="eligible",
        ),
        RecallCoverageEntry(
            tool="osiris",
            category=category,
            R_hat=0.08,
            n_eff=662.0,
            support_level="eligible",
        ),
        RecallCoverageEntry(
            tool="smartcheck",
            category=category,
            R_hat=0.000696,
            n_eff=662.0,
            support_level="eligible",
        ),
        RecallCoverageEntry(
            tool="conkas",
            category=category,
            R_hat=0.8,
            n_eff=1.944,
            support_level="under_evidenced",
        ),
    ]
    decisions = decide_primary_categories(
        rows,
        primary_tool="slither",
        required_categories=[category],
    )
    tools = ["slither", "osiris", "smartcheck", "conkas"]
    stage1 = Stage1EvidencePacket(
        tool_table=[
            tool_entry("slither", runtime=1.0),
            tool_entry("osiris", feasible=False, runtime=1.0),
            tool_entry("smartcheck", runtime=1.0),
            tool_entry("conkas", runtime=1.0),
        ],
        scene_pool=scene_pool(("d1", 1.0, 1.0)),
        score_panel=ScorePanel(
            nominal_scores=[
                NominalToolScore(
                    tool=tool,
                    S_scene=1.0 - index / 10.0,
                    rank=index + 1,
                    support_mass=1.0,
                )
                for index, tool in enumerate(tools)
            ]
        ),
        primary_selection=PrimarySelection(
            status=Stage1Status.PRIMARY_SELECTED,
            primary_tool="slither",
            eligible_tools=tools,
        ),
    )
    return Stage2EvidenceContext(
        stage1=stage1,
        required_categories=[category],
        recall_coverage=RecallCoverageMatrix(matrix=rows),
        primary_category_decisions=decisions,
        primary_attention=PrimaryAttention(
            primary_tool="slither",
            required_categories=[category],
            confirmed_weak_categories=[category],
        ),
    )


def test_infeasible_stronger_peer_does_not_qualify_weaker_smartcheck() -> None:
    context = _real_arithmetic_context()
    limit = budget(slots=4, runtime=10.0)
    matrix = build_action_evidence_matrix(context, limit)
    panel = matrix.ownership_panel["arithmetic"]

    assert panel.primary_decision.credible_peer_tool == "osiris"
    assert panel.assignment_status == "PRIMARY_ONLY_NO_COMPLEMENT"
    assert panel.eligible_candidates == []
    assert next(item for item in panel.rejected_candidates if item.tool == "smartcheck").strength.evidence_stronger is False
    conkas = panel.under_evidenced_candidates[0]
    assert conkas.tool == "conkas"
    assert conkas.n_eff == pytest.approx(1.944)

    payload = json.loads(
        _prompt_payload(context, matrix, None, w_recall=0.5, w_precision=0.5)
    )
    assert payload["required_categories"][0]["eligible_candidates"] == []

    certificate = assemble_decision(
        {
            "complements": [
                {
                    "category": "arithmetic",
                    "tool": "smartcheck",
                    "evidence_refs": ["ev_rcov_smartcheck_arithmetic"],
                }
            ]
        },
        context,
        matrix,
        limit,
    )
    assert certificate.category_assignments[0].owner_tools == ["slither"]
    assert certificate.decision_type == "RUN_PRIMARY"
    assert [entry.tool for entry in certificate.selected_plan] == ["slither"]
    verdict = check_decision(certificate, context, matrix)
    assert verdict.status == "ACCEPT"
