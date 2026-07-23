from __future__ import annotations

from toolrank.cego import assemble_decision
from toolrank.checker import check_decision
from toolrank.composition import composition_from_certificate
from toolrank.dace_rag import build_action_evidence_matrix
from toolrank.evidence_packet import build_stage2_context
from toolrank.fusion import fuse_reports
from toolrank.scene_scoring import compute_scene_scores, select_primary
from toolrank.schemas import Finding
from toolrank.schemas_v2 import BudgetProfile, Stage1EvidencePacket
from tests.stage1_fixtures import entry, knowledge_base, observation, scene_pool, tool_entry


def test_primary_and_owner_sets_survive_every_boundary() -> None:
    kb = knowledge_base(
        [
            entry(
                "d1",
                [
                    observation("a", recall=0.9, precision=0.9, detected=1, total=5),
                    observation("b", recall=0.8, precision=0.8, detected=12, total=15),
                ],
            )
        ]
    )
    pool = scene_pool(("d1", 1.0, 1.0))
    table = [tool_entry("a", runtime=2.0), tool_entry("b", runtime=8.0)]
    scores = compute_scene_scores(pool, kb, ["a", "b"], 0.5, 0.5)
    selection = select_primary(pool, scores, table)
    stage1 = Stage1EvidencePacket(
        tool_table=table,
        scene_pool=pool,
        score_panel=scores,
        primary_selection=selection,
    )
    context = build_stage2_context(stage1, kb, ["reentrancy"])
    limit = BudgetProfile(tool_slots=2, runtime_cap_minutes=10.0)
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
    verdict = check_decision(certificate, context, matrix)
    composition = composition_from_certificate(certificate)
    report = fuse_reports(
        {
            "a": [Finding(source_tool="a", category="reentrancy", location="A.sol:1")],
            "b": [Finding(source_tool="b", category="reentrancy", location="A.sol:1")],
        },
        composition,
    )

    assert stage1.score_panel.benchmark_weights == {"d1_slice": 1.0}
    assert stage1.primary_selection.primary_tool == "a"
    assert context.stage1.primary_selection.primary_tool == "a"
    assert certificate.primary_tool == "a"
    assert verdict.status == "ACCEPT"
    assert composition.category_owners == {"reentrancy": ["a", "b"]}
    assert report.findings[0].source_tools == ["a", "b"]
