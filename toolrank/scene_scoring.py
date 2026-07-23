"""Paper-faithful Stage 1 benchmark ranking and primary selection."""

from __future__ import annotations

import math
import re

from toolrank.numeric_bounds import clamp_normalized_mass
from toolrank.schemas import PerformanceKnowledgeBase
from toolrank.schemas_v2 import (
    BenchmarkToolScore,
    NominalToolScore,
    PrimarySelection,
    ScenePool,
    ScorePanel,
    Stage1Status,
    ToolTableEntry,
    stage1_evaluation_id,
)


def _tool_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def average_ranks(raw_scores: dict[str, float]) -> dict[str, float]:
    """Return descending 1-based ranks, averaging the positions of exact ties."""
    ranked = sorted(raw_scores.items(), key=lambda item: (-item[1], item[0]))
    result: dict[str, float] = {}
    index = 0
    while index < len(ranked):
        end = index + 1
        while end < len(ranked) and ranked[end][1] == ranked[index][1]:
            end += 1
        average = ((index + 1) + end) / 2.0
        for tool, _value in ranked[index:end]:
            result[tool] = average
        index = end
    return result


def phi(rank: float, tool_count: int) -> float:
    """Normalize a paper rank with ``(n-r+1)/n``."""
    if tool_count <= 0:
        raise ValueError("tool_count must be positive")
    if rank < 1.0 or rank > tool_count:
        raise ValueError("rank must lie within the comparison pool")
    return (tool_count - rank + 1.0) / tool_count


def _weighted_average(values: list[tuple[float, float]]) -> float | None:
    denominator = math.fsum(weight for weight, _value in values)
    if denominator <= 0.0:
        return None
    return math.fsum(weight * value for weight, value in values) / denominator


def compute_scene_scores(
    scene_pool: ScenePool,
    kb: PerformanceKnowledgeBase,
    tool_ids: list[str],
    w_recall: float,
    w_precision: float,
) -> ScorePanel:
    """Compute ``s_t,D`` and ``S_t`` using only comparable overall metrics.

    Category-level ``detected/total`` fields are deliberately never read here.
    The caller supplies the feasible tool IDs, matching the paper's feasible
    comparison domain.
    """
    entries_by_source = {entry.source_id: entry for entry in kb.entries}
    requested_by_key: dict[str, str] = {}
    for tool_id in tool_ids:
        requested_by_key.setdefault(_tool_key(tool_id), tool_id)

    benchmark_weights = {neighbor.slice_id: neighbor.weight for neighbor in scene_pool.neighbors}
    benchmark_scores: list[BenchmarkToolScore] = []
    scores_by_tool: dict[str, list[tuple[float, float]]] = {tool: [] for tool in tool_ids}
    precision_by_tool: dict[str, list[tuple[float, float]]] = {tool: [] for tool in tool_ids}
    recall_by_tool: dict[str, list[tuple[float, float]]] = {tool: [] for tool in tool_ids}

    for neighbor in scene_pool.neighbors:
        if neighbor.paper_id is None:
            continue
        entry = entries_by_source.get(neighbor.paper_id)
        if entry is None:
            continue

        comparable: dict[str, tuple[float, float]] = {}
        for observation in entry.tool_performance_data:
            tool = requested_by_key.get(_tool_key(observation.tool_name))
            if tool is None:
                continue
            recall = observation.metrics.recall
            precision = observation.metrics.precision
            if recall is None or precision is None:
                continue
            comparable[tool] = (recall, precision)

        if not comparable:
            continue
        recall_ranks = average_ranks({tool: values[0] for tool, values in comparable.items()})
        precision_ranks = average_ranks({tool: values[1] for tool, values in comparable.items()})
        tool_count = len(comparable)

        for tool in sorted(comparable):
            recall, precision = comparable[tool]
            recall_rank = recall_ranks[tool]
            precision_rank = precision_ranks[tool]
            score = (
                w_recall * phi(recall_rank, tool_count)
                + w_precision * phi(precision_rank, tool_count)
            )
            benchmark_scores.append(
                BenchmarkToolScore(
                    evaluation_id=stage1_evaluation_id(tool, neighbor.slice_id),
                    tool=tool,
                    benchmark_id=neighbor.slice_id,
                    source_id=entry.source_id,
                    dataset_id=entry.dataset_profile.dataset_name,
                    weight=neighbor.weight,
                    recall=recall,
                    precision=precision,
                    recall_rank=recall_rank,
                    precision_rank=precision_rank,
                    score=score,
                )
            )
            scores_by_tool[tool].append((neighbor.weight, score))
            recall_by_tool[tool].append((neighbor.weight, recall))
            precision_by_tool[tool].append((neighbor.weight, precision))

    nominal_scores: list[NominalToolScore] = []
    for tool in tool_ids:
        values = scores_by_tool[tool]
        support_mass = clamp_normalized_mass(
            math.fsum(weight for weight, _value in values)
        )
        scene_score = _weighted_average(values) or 0.0
        recall_value = _weighted_average(recall_by_tool[tool])
        precision_value = _weighted_average(precision_by_tool[tool])
        if w_recall > w_precision:
            preferred_value = recall_value
        elif w_precision > w_recall:
            preferred_value = precision_value
        else:
            preferred_value = None
        nominal_scores.append(
            NominalToolScore(
                tool=tool,
                S_scene=scene_score,
                rank=1,
                support_mass=support_mass,
                preferred_metric_value=preferred_value,
                P_scene=precision_value,
                R_scene=recall_value,
            )
        )

    nominal_scores.sort(
        key=lambda item: (
            -item.S_scene,
            item.preferred_metric_value is None,
            -(item.preferred_metric_value or 0.0),
            item.tool,
        )
    )
    nominal_scores = [
        item.model_copy(update={"rank": rank})
        for rank, item in enumerate(nominal_scores, start=1)
    ]
    return ScorePanel(
        benchmark_weights=benchmark_weights,
        benchmark_scores=benchmark_scores,
        nominal_scores=nominal_scores,
    )


def _selection_key(
    score: NominalToolScore,
    table: dict[str, ToolTableEntry],
) -> tuple[float, bool, float, bool, float, str]:
    runtime = table[score.tool].tool_cost.expected_runtime_minutes
    return (
        -score.S_scene,
        score.preferred_metric_value is None,
        -(score.preferred_metric_value or 0.0),
        runtime is None,
        runtime if runtime is not None else math.inf,
        score.tool,
    )


def rank_nominal_scores(
    score_panel: ScorePanel,
    tool_table: list[ToolTableEntry],
) -> ScorePanel:
    """Assign visible ranks with the exact primary-selection comparator."""
    table = {entry.tool: entry for entry in tool_table}
    ordered = sorted(
        score_panel.nominal_scores,
        key=lambda score: _selection_key(score, table),
    )
    score_panel.nominal_scores = [
        score.model_copy(update={"rank": rank})
        for rank, score in enumerate(ordered, start=1)
    ]
    return score_panel


def select_primary(
    scene_pool: ScenePool,
    score_panel: ScorePanel,
    tool_table: list[ToolTableEntry],
    tau: float = 0.2,
) -> PrimarySelection:
    """Directly select the highest-ranked feasible, support-qualified tool."""
    rank_nominal_scores(score_panel, tool_table)
    if not scene_pool.neighbors:
        return PrimarySelection(
            status=Stage1Status.NO_SCENE_EVIDENCE,
            tau=tau,
            reason_codes=["NO_SCENE_EVIDENCE"],
        )

    table = {entry.tool: entry for entry in tool_table}
    feasible = {entry.tool for entry in tool_table if entry.feasible}
    if not feasible:
        return PrimarySelection(
            status=Stage1Status.NO_FEASIBLE_TOOL,
            tau=tau,
            reason_codes=["NO_FEASIBLE_TOOL"],
        )

    qualified = [
        score
        for score in score_panel.nominal_scores
        if score.tool in feasible and score.support_mass >= tau
    ]
    if not qualified:
        return PrimarySelection(
            status=Stage1Status.NO_PRIMARY_WITH_SUFFICIENT_SUPPORT,
            tau=tau,
            reason_codes=["NO_PRIMARY_WITH_SUFFICIENT_SUPPORT"],
        )

    ordered = sorted(qualified, key=lambda score: _selection_key(score, table))
    return PrimarySelection(
        status=Stage1Status.PRIMARY_SELECTED,
        primary_tool=ordered[0].tool,
        tau=tau,
        eligible_tools=[score.tool for score in ordered],
        reason_codes=["FEASIBLE", "SUPPORT_AT_LEAST_TAU", "HIGHEST_STAGE1_SCORE"],
    )
