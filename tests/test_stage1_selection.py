from __future__ import annotations

import pytest

from toolrank.scene_scoring import select_primary
from toolrank.schemas_v2 import NominalToolScore, ScenePool, ScorePanel, Stage1Status
from tests.stage1_fixtures import scene_pool, tool_entry


def score(
    tool: str,
    value: float,
    support: float,
    *,
    preferred: float | None = None,
) -> NominalToolScore:
    return NominalToolScore(
        tool=tool,
        S_scene=value,
        rank=1,
        support_mass=support,
        preferred_metric_value=preferred,
    )


@pytest.mark.parametrize(
    ("support", "expected_status"),
    [
        (0.199999, Stage1Status.NO_PRIMARY_WITH_SUFFICIENT_SUPPORT),
        (0.2, Stage1Status.PRIMARY_SELECTED),
        (0.200001, Stage1Status.PRIMARY_SELECTED),
    ],
)
def test_support_threshold_is_inclusive(support: float, expected_status: Stage1Status) -> None:
    selection = select_primary(
        scene_pool(("d1", 1.0, 1.0)),
        ScorePanel(nominal_scores=[score("a", 0.8, support)]),
        [tool_entry("a")],
        tau=0.2,
    )
    assert selection.status == expected_status


def test_primary_tie_order_is_score_preferred_metric_runtime_then_tool_id() -> None:
    panel = ScorePanel(
        nominal_scores=[
            score("z", 0.8, 1.0, preferred=0.7),
            score("b", 0.8, 1.0, preferred=0.8),
            score("a", 0.8, 1.0, preferred=0.8),
        ]
    )
    selection = select_primary(
        scene_pool(("d1", 1.0, 1.0)),
        panel,
        [tool_entry("z", runtime=1.0), tool_entry("b", runtime=3.0), tool_entry("a", runtime=3.0)],
    )
    assert selection.primary_tool == "a"
    assert selection.eligible_tools == ["a", "b", "z"]


def test_known_runtime_wins_runtime_tie() -> None:
    panel = ScorePanel(
        nominal_scores=[score("unknown", 0.8, 1.0), score("known", 0.8, 1.0)]
    )
    selection = select_primary(
        scene_pool(("d1", 1.0, 1.0)),
        panel,
        [tool_entry("unknown", runtime=None), tool_entry("known", runtime=20.0)],
    )
    assert selection.primary_tool == "known"


def test_explicit_early_outcomes() -> None:
    no_scene = select_primary(ScenePool(), ScorePanel(), [tool_entry("a")])
    assert no_scene.status == Stage1Status.NO_SCENE_EVIDENCE

    no_feasible = select_primary(
        scene_pool(("d1", 1.0, 1.0)),
        ScorePanel(nominal_scores=[score("a", 1.0, 1.0)]),
        [tool_entry("a", feasible=False)],
    )
    assert no_feasible.status == Stage1Status.NO_FEASIBLE_TOOL

    no_support = select_primary(
        scene_pool(("d1", 1.0, 1.0)),
        ScorePanel(nominal_scores=[score("a", 1.0, 0.0)]),
        [tool_entry("a")],
    )
    assert no_support.status == Stage1Status.NO_PRIMARY_WITH_SUFFICIENT_SUPPORT
    assert no_support.primary_tool is None
