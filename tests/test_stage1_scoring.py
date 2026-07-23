from __future__ import annotations

import math

import pytest

from toolrank.scene_scoring import average_ranks, compute_scene_scores, phi
from tests.stage1_fixtures import entry, knowledge_base, observation, scene_pool


def test_phi_single_tool_is_one() -> None:
    assert phi(1.0, 1) == 1.0


def test_metric_ties_receive_average_ranks() -> None:
    assert average_ranks({"a": 0.9, "b": 0.9, "c": 0.2}) == {
        "a": 1.5,
        "b": 1.5,
        "c": 3.0,
    }


def test_scoring_keeps_benchmark_rows_and_weights() -> None:
    kb = knowledge_base(
        [
            entry(
                "d1",
                [
                    observation("a", recall=0.9, precision=0.8),
                    observation("b", recall=0.5, precision=0.6),
                ],
            ),
            entry(
                "d2",
                [
                    observation("a", recall=0.4, precision=0.4),
                    observation("b", recall=0.8, precision=0.9),
                ],
            ),
        ]
    )
    pool = scene_pool(("d1", 0.75, 0.8), ("d2", 0.25, 0.3))

    panel = compute_scene_scores(pool, kb, ["a", "b"], w_recall=0.75, w_precision=0.25)

    assert panel.benchmark_weights == {"d1_slice": 0.75, "d2_slice": 0.25}
    assert len(panel.benchmark_scores) == 4
    by_pair = {(row.tool, row.benchmark_id): row for row in panel.benchmark_scores}
    assert by_pair[("a", "d1_slice")].score == 1.0
    assert by_pair[("b", "d1_slice")].score == 0.5
    assert by_pair[("a", "d2_slice")].score == 0.5
    assert by_pair[("b", "d2_slice")].score == 1.0

    by_tool = {score.tool: score for score in panel.nominal_scores}
    assert by_tool["a"].support_mass == 1.0
    assert by_tool["a"].S_scene == pytest.approx(0.875)
    assert by_tool["b"].S_scene == pytest.approx(0.625)
    assert by_tool["a"].preferred_metric_value == pytest.approx(0.775)


def test_tool_participates_only_when_both_metrics_are_comparable() -> None:
    kb = knowledge_base(
        [
            entry(
                "d1",
                [
                    observation("complete", recall=0.7, precision=0.8),
                    observation("recall_only", recall=0.99, precision=None),
                    observation("precision_only", recall=None, precision=0.99),
                ],
            )
        ]
    )
    panel = compute_scene_scores(
        scene_pool(("d1", 1.0, 1.0)),
        kb,
        ["complete", "recall_only", "precision_only", "missing"],
        w_recall=0.5,
        w_precision=0.5,
    )

    assert [(row.tool, row.score) for row in panel.benchmark_scores] == [("complete", 1.0)]
    by_tool = {score.tool: score for score in panel.nominal_scores}
    assert by_tool["complete"].support_mass == 1.0
    assert by_tool["complete"].S_scene == 1.0
    assert by_tool["recall_only"].support_mass == 0.0
    assert by_tool["precision_only"].support_mass == 0.0
    assert by_tool["missing"].support_mass == 0.0


def test_normalized_scene_mass_roundoff_is_clamped_before_schema_validation() -> None:
    weights = [
        8.865377593922667e-05,
        0.07628632428272755,
        0.9236250219413333,
    ]
    assert math.fsum(weights) == 1.0000000000000002
    kb = knowledge_base(
        [
            entry(
                f"d{index}",
                [observation("a", recall=0.8, precision=0.9)],
            )
            for index in range(len(weights))
        ]
    )
    pool = scene_pool(
        *[
            (f"d{index}", weight, 0.1)
            for index, weight in enumerate(weights)
        ]
    )

    panel = compute_scene_scores(pool, kb, ["a"], w_recall=0.5, w_precision=0.5)

    assert panel.nominal_scores[0].support_mass == 1.0


def test_materially_invalid_scene_mass_is_not_hidden_by_roundoff_clamp() -> None:
    kb = knowledge_base(
        [
            entry("d1", [observation("a", recall=0.8, precision=0.9)]),
            entry("d2", [observation("a", recall=0.8, precision=0.9)]),
        ]
    )

    with pytest.raises(ValueError):
        compute_scene_scores(
            scene_pool(("d1", 0.501, 0.1), ("d2", 0.5, 0.1)),
            kb,
            ["a"],
            w_recall=0.5,
            w_precision=0.5,
        )
