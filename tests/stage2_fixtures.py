from __future__ import annotations

from toolrank.schemas_v2 import (
    BenchmarkToolScore,
    BudgetProfile,
    NominalToolScore,
    PerformanceDBEvidenceRow,
    PrimaryAttention,
    PrimarySelection,
    RecallCoverageEntry,
    RecallCoverageMatrix,
    ScorePanel,
    Stage1EvidencePacket,
    Stage1Status,
    Stage2EvidenceContext,
    stage1_evaluation_id,
)
from tests.stage1_fixtures import scene_pool, tool_entry
from toolrank.evidence_packet import decide_primary_categories


def stage2_context(
    *,
    b_runtime: float | None = 8.0,
    c_runtime: float | None = 3.0,
    primary_rate: float | None = 0.0,
    primary_n_eff: float | None = 15.0,
    peer_rate: float | None = 0.8,
    peer_n_eff: float | None = 15.0,
) -> Stage2EvidenceContext:
    stage1 = Stage1EvidencePacket(
        target_contract={
            "features": {
                "primary_solidity_version": "0.8.20",
                "solidity_version_constraints": ["^0.8.20"],
                "gower_solc_bucket": "0.8.x",
                "present_input_kinds": ["sol"],
                "loc_total": 100,
            }
        },
        tool_table=[
            tool_entry("a", runtime=2.0),
            tool_entry("b", runtime=b_runtime),
            tool_entry("c", runtime=c_runtime),
        ],
        scene_pool=scene_pool(("d1", 1.0, 1.0)),
        score_panel=ScorePanel(
            benchmark_weights={"d1_slice": 1.0},
            benchmark_scores=[
                BenchmarkToolScore(
                    evaluation_id=stage1_evaluation_id(tool, "d1_slice"),
                    tool=tool,
                    benchmark_id="d1_slice",
                    source_id="d1",
                    dataset_id="d1",
                    weight=1.0,
                    recall=value,
                    precision=value,
                    recall_rank=rank,
                    precision_rank=rank,
                    score=score,
                )
                for tool, value, rank, score in (
                    ("a", 0.9, 1.0, 1.0),
                    ("b", 0.8, 2.0, 2.0 / 3.0),
                    ("c", 0.7, 3.0, 1.0 / 3.0),
                )
            ],
            nominal_scores=[
                NominalToolScore(
                    tool=tool,
                    S_scene=score,
                    rank=rank,
                    support_mass=1.0,
                )
                for tool, score, rank in (
                    ("a", 1.0, 1),
                    ("b", 2.0 / 3.0, 2),
                    ("c", 1.0 / 3.0, 3),
                )
            ],
        ),
        primary_selection=PrimarySelection(
            status=Stage1Status.PRIMARY_SELECTED,
            primary_tool="a",
            eligible_tools=["a", "b", "c"],
        ),
    )
    decisions = decide_primary_categories(
        [
            RecallCoverageEntry(
                tool="a",
                category="reentrancy",
                R_hat=primary_rate,
                n_eff=primary_n_eff,
            ),
            RecallCoverageEntry(
                tool="b",
                category="reentrancy",
                R_hat=peer_rate,
                n_eff=peer_n_eff,
            ),
        ],
        primary_tool="a",
        required_categories=["reentrancy"],
    )
    return Stage2EvidenceContext(
        stage1=stage1,
        required_categories=["reentrancy"],
        recall_coverage=RecallCoverageMatrix(
            matrix=[
                RecallCoverageEntry(
                    tool="a",
                    category="reentrancy",
                    detected=1,
                    total=5,
                    R_hat=primary_rate,
                    n_eff=primary_n_eff,
                    support_level=(
                        "eligible"
                        if primary_rate and primary_n_eff is not None and primary_n_eff >= 15
                        else "under_evidenced"
                    ),
                ),
                RecallCoverageEntry(
                    tool="b",
                    category="reentrancy",
                    detected=12,
                    total=15,
                    R_hat=peer_rate,
                    n_eff=peer_n_eff,
                    support_level=(
                        "eligible"
                        if peer_rate and peer_n_eff is not None and peer_n_eff >= 15
                        else "under_evidenced"
                    ),
                ),
                RecallCoverageEntry(
                    tool="c",
                    category="reentrancy",
                    detected=10,
                    total=14,
                    R_hat=10 / 14,
                    n_eff=14.0,
                    support_level="under_evidenced",
                ),
            ]
        ),
        performance_db_view=[
            PerformanceDBEvidenceRow(
                evidence_id=f"ev_dataset_d1_d1_{tool}_reentrancy",
                source_id="d1",
                dataset_name="d1",
                tool=tool,
                category="reentrancy",
                detected=detected,
                total=total,
                R_hat=rate,
                n_eff=n_eff,
            )
            for tool, detected, total, rate, n_eff in (
                ("a", 1, 5, primary_rate, primary_n_eff),
                ("b", 12, 15, peer_rate, peer_n_eff),
                ("c", 10, 14, 10 / 14, 14.0),
            )
            if rate is not None
        ],
        primary_category_decisions=decisions,
        primary_attention=PrimaryAttention(
            primary_tool="a",
            required_categories=["reentrancy"],
            confirmed_weak_categories=[
                item.category
                for item in decisions
                if item.evidence_classification == "confirmed_weak"
            ],
            under_evidenced_categories=[
                item.category
                for item in decisions
                if item.evidence_classification == "under_evidenced"
            ],
        ),
    )


def budget(*, slots: int = 2, runtime: float = 10.0) -> BudgetProfile:
    return BudgetProfile(tool_slots=slots, runtime_cap_minutes=runtime, alert_cap="medium")
