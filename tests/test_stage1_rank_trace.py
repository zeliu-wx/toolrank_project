from __future__ import annotations

from toolrank.scene_scoring import select_primary
from toolrank.schemas_v2 import NominalToolScore, ScorePanel
from tests.stage1_fixtures import scene_pool, tool_entry


def test_visible_rank_and_primary_share_runtime_tie_break() -> None:
    panel = ScorePanel(
        nominal_scores=[
            NominalToolScore(tool="a", S_scene=0.8, rank=1, support_mass=1.0),
            NominalToolScore(tool="b", S_scene=0.8, rank=2, support_mass=1.0),
        ]
    )
    table = [tool_entry("a", runtime=2.0), tool_entry("b", runtime=1.0)]

    selection = select_primary(scene_pool(("paper", 1.0, 1.0)), panel, table)

    assert panel.nominal_scores[0].tool == "b"
    assert panel.nominal_scores[0].rank == 1
    assert selection.primary_tool == "b"
