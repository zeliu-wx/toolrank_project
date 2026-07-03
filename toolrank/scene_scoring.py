"""Compute scene-conditioned nominal tool scores.

Per dataset (scene-pool neighbor), tools are rank-normalized separately by
recall and by precision; the two ranks combine with ROC preference weights
(w_recall, w_precision) into a per-dataset preference score, then aggregate
across datasets by scene-pool weight w_D into S_scene.
"""

from __future__ import annotations

import re

from toolrank.recall_ci import bootstrap_recall_ci
from toolrank.schemas import PerformanceKnowledgeBase
from toolrank.schemas_v2 import NominalToolScore, ScenePool


def _tool_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _rank_scores(raw_scores: dict[str, float]) -> dict[str, float]:
    """Rank tools by value (desc); normalize rank to (n-index)/n in (0, 1].

    A single tool gets 0.0 (no contrast to establish a relative rank)."""
    if not raw_scores:
        return {}
    if len(raw_scores) == 1:
        return {next(iter(raw_scores)): 0.0}
    ranked = sorted(raw_scores.items(), key=lambda item: (-item[1], item[0]))
    return {tool: (len(ranked) - index) / len(ranked) for index, (tool, _score) in enumerate(ranked)}


def _weighted_average(values: list[tuple[float, float]]) -> float | None:
    total_weight = sum(weight for weight, _value in values)
    if total_weight <= 0.0:
        return None
    return sum(weight * value for weight, value in values) / total_weight


def _evidence_level(rows: list[tuple[float, int, int]], epsilon_r: float) -> tuple[str, float | None, float | None]:
    ci = bootstrap_recall_ci(rows)
    if ci is None:
        return "unsupported", None, None
    _point, low, high = ci
    level = "local_strong" if (high - low) / 2.0 <= epsilon_r else "local_weak"
    return level, low, high


def compute_scene_scores(
    scene_pool: ScenePool,
    kb: PerformanceKnowledgeBase,
    tool_ids: list[str],
    w_recall: float,
    w_precision: float,
    epsilon_r: float = 0.15,
) -> tuple[list[NominalToolScore], dict[str, dict[str, float]]]:
    entries_by_source = {entry.source_id: entry for entry in kb.entries}
    requested_by_key = {_tool_key(tool): tool for tool in tool_ids}

    score_values: dict[str, list[tuple[float, float]]] = {tool: [] for tool in tool_ids}
    precision_values: dict[str, list[tuple[float, float]]] = {tool: [] for tool in tool_ids}
    recall_values: dict[str, list[tuple[float, float]]] = {tool: [] for tool in tool_ids}
    f1_values: dict[str, list[tuple[float, float]]] = {tool: [] for tool in tool_ids}
    effective_totals: dict[str, float] = {tool: 0.0 for tool in tool_ids}
    ci_rows: dict[str, list[tuple[float, int, int]]] = {tool: [] for tool in tool_ids}
    tool_slice_scores: dict[str, dict[str, float]] = {tool: {} for tool in tool_ids}

    for neighbor in scene_pool.neighbors:
        if neighbor.paper_id is None:
            continue
        entry = entries_by_source.get(neighbor.paper_id)
        if entry is None:
            continue

        recall_by_tool: dict[str, float] = {}
        precision_by_tool: dict[str, float] = {}
        metrics_by_tool = {}
        total_by_tool: dict[str, float] = {}
        detected_by_tool: dict[str, int] = {}
        for observation in entry.tool_performance_data:
            tool = requested_by_key.get(_tool_key(observation.tool_name))
            if tool is None:
                continue
            metric = observation.metrics
            metrics_by_tool[tool] = metric
            counts = observation.vulnerability_score_counts
            total_by_tool[tool] = float(sum(c.total for c in counts.values())) if counts else 0.0
            detected_by_tool[tool] = int(sum(c.detected for c in counts.values())) if counts else 0
            if metric.recall is not None:
                recall_by_tool[tool] = metric.recall
            if metric.precision is not None:
                precision_by_tool[tool] = metric.precision

        recall_rank = _rank_scores(recall_by_tool)
        precision_rank = _rank_scores(precision_by_tool)

        for tool in set(recall_rank) | set(precision_rank):
            s_dataset = w_recall * recall_rank.get(tool, 0.0) + w_precision * precision_rank.get(tool, 0.0)
            tool_slice_scores[tool][neighbor.slice_id] = s_dataset
            score_values[tool].append((neighbor.weight, s_dataset))
            total_sum = int(total_by_tool.get(tool, 0.0))
            effective_totals[tool] += neighbor.kernel_density * total_sum
            if total_sum > 0:
                detected_sum = detected_by_tool.get(tool, 0)
                ci_rows[tool].append((neighbor.kernel_density, detected_sum, total_sum))
            metric = metrics_by_tool[tool]
            if metric.precision is not None:
                precision_values[tool].append((neighbor.weight, metric.precision))
            if metric.recall is not None:
                recall_values[tool].append((neighbor.weight, metric.recall))
            if metric.f1 is not None:
                f1_values[tool].append((neighbor.weight, metric.f1))

    nominal_scores: list[NominalToolScore] = []
    for tool in tool_ids:
        s_scene = _weighted_average(score_values[tool]) or 0.0
        ev_level, ci_low, ci_high = _evidence_level(ci_rows[tool], epsilon_r)
        nominal_scores.append(
            NominalToolScore(
                tool=tool,
                S_scene=s_scene,
                rank=1,
                P_scene=_weighted_average(precision_values[tool]),
                R_scene=_weighted_average(recall_values[tool]),
                F1_scene=_weighted_average(f1_values[tool]),
                effective_total=effective_totals[tool],
                R_scene_ci_low=ci_low,
                R_scene_ci_high=ci_high,
                evidence_level=ev_level,
            )
        )

    nominal_scores.sort(key=lambda item: (-item.S_scene, item.tool))
    ranked_scores = [
        item.model_copy(update={"rank": rank})
        for rank, item in enumerate(nominal_scores, start=1)
    ]
    return ranked_scores, tool_slice_scores
