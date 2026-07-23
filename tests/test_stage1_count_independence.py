from __future__ import annotations

from toolrank.scene_scoring import compute_scene_scores, select_primary
from tests.stage1_fixtures import entry, knowledge_base, observation, scene_pool, tool_entry


def _kb_with_counts(a_counts: tuple[int, int], b_counts: tuple[int, int]):
    return knowledge_base(
        [
            entry(
                "d1",
                [
                    observation(
                        "a",
                        recall=0.9,
                        precision=0.8,
                        detected=a_counts[0],
                        total=a_counts[1],
                    ),
                    observation(
                        "b",
                        recall=0.6,
                        precision=0.7,
                        detected=b_counts[0],
                        total=b_counts[1],
                    ),
                ],
            )
        ]
    )


def test_category_counts_cannot_change_stage1() -> None:
    pool = scene_pool(("d1", 1.0, 0.2))
    tools = [tool_entry("a", runtime=4.0), tool_entry("b", runtime=1.0)]

    first_panel = compute_scene_scores(
        pool,
        _kb_with_counts((1, 1000), (1000, 1000)),
        ["a", "b"],
        0.5,
        0.5,
    )
    second_panel = compute_scene_scores(
        pool,
        _kb_with_counts((1000, 1000), (1, 1000)),
        ["a", "b"],
        0.5,
        0.5,
    )

    assert first_panel == second_panel
    assert select_primary(pool, first_panel, tools).primary_tool == "a"
    assert select_primary(pool, second_panel, tools).primary_tool == "a"
