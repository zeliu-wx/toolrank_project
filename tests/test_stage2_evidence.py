from __future__ import annotations

import pytest

from toolrank.evidence_packet import build_stage2_context
from toolrank.rcov import build_recall_coverage
from toolrank.schemas_v2 import (
    PrimarySelection,
    ScorePanel,
    Stage1EvidencePacket,
    Stage1Status,
)
from tests.stage1_fixtures import entry, knowledge_base, observation, scene_pool, tool_entry


def test_category_statistics_use_raw_density_not_normalized_weight() -> None:
    kb = knowledge_base(
        [
            entry("d1", [observation("a", recall=0.8, precision=0.7, detected=8, total=10)]),
            entry("d2", [observation("a", recall=0.8, precision=0.7, detected=4, total=20)]),
        ]
    )
    matrix = build_recall_coverage(
        kb,
        ["a"],
        scene_densities={"d1": 0.5, "d2": 0.25},
    )

    row = next(item for item in matrix.matrix if item.tool == "a" and item.category == "reentrancy")
    assert row.detected == 12
    assert row.total == 30
    assert row.n_eff == pytest.approx(10.0)
    assert row.R_hat == pytest.approx(0.5)


def test_low_primary_neff_marks_diagnostic_without_changing_primary() -> None:
    pool = scene_pool(("d1", 1.0, 1.0))
    stage1 = Stage1EvidencePacket(
        target_contract={"features": {}},
        tool_table=[tool_entry("a", runtime=2.0), tool_entry("b", runtime=3.0)],
        scene_pool=pool,
        score_panel=ScorePanel(),
        primary_selection=PrimarySelection(
            status=Stage1Status.PRIMARY_SELECTED,
            primary_tool="a",
            eligible_tools=["a", "b"],
        ),
    )
    kb = knowledge_base(
        [
            entry(
                "d1",
                [
                    observation("a", recall=0.8, precision=0.8, detected=2, total=14),
                    observation("b", recall=0.7, precision=0.7, detected=12, total=15),
                ],
            )
        ]
    )

    context = build_stage2_context(stage1, kb, ["reentrancy"])

    assert context.stage1.primary_selection.primary_tool == "a"
    assert context.primary_attention.primary_tool == "a"
    assert context.primary_attention.under_evidenced_categories == ["reentrancy"]
    assert context.required_categories == ["reentrancy"]
    assert [(item.tool, item.category) for item in context.dace_rag_focus] == [
        ("b", "reentrancy")
    ]


def test_no_required_categories_builds_empty_category_context() -> None:
    stage1 = Stage1EvidencePacket(
        tool_table=[tool_entry("a")],
        scene_pool=scene_pool(("d1", 1.0, 1.0)),
        score_panel=ScorePanel(),
        primary_selection=PrimarySelection(
            status=Stage1Status.PRIMARY_SELECTED,
            primary_tool="a",
            eligible_tools=["a"],
        ),
    )
    context = build_stage2_context(stage1, knowledge_base([]), [])
    assert context.required_categories == []
    assert context.primary_attention.under_evidenced_categories == []
    assert context.dace_rag_focus == []


@pytest.mark.parametrize(
    ("detected", "total", "expected_confirmed", "expected_under"),
    [
        (None, None, [], ["reentrancy"]),
        (0, 14, [], ["reentrancy"]),
        (0, 15, ["reentrancy"], []),
    ],
)
def test_primary_attention_separates_under_evidenced_from_confirmed_weak(
    detected: int | None,
    total: int | None,
    expected_confirmed: list[str],
    expected_under: list[str],
) -> None:
    pool = scene_pool(("d1", 1.0, 1.0))
    stage1 = Stage1EvidencePacket(
        tool_table=[tool_entry("a")],
        scene_pool=pool,
        score_panel=ScorePanel(),
        primary_selection=PrimarySelection(
            status=Stage1Status.PRIMARY_SELECTED,
            primary_tool="a",
            eligible_tools=["a"],
        ),
    )
    if detected is None:
        primary = observation("a", recall=0.8, precision=0.8)
        primary.vulnerability_scores = {"reentrancy": 0.0}
    else:
        primary = observation(
            "a",
            recall=0.8,
            precision=0.8,
            detected=detected,
            total=total,
        )
    context = build_stage2_context(
        stage1,
        knowledge_base([entry("d1", [primary])]),
        ["reentrancy"],
    )

    assert context.primary_attention.confirmed_weak_categories == expected_confirmed
    assert context.primary_attention.under_evidenced_categories == expected_under
