"""Build Stage 2 category recall evidence from benchmark counts."""

from __future__ import annotations

import math
import re

from toolrank.assignment_evidence import complement_count_eligible
from toolrank.schemas import PerformanceKnowledgeBase
from toolrank.schemas_v2 import RecallCoverageEntry, RecallCoverageMatrix


def _tool_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _normalized_scene_weights(
    kb: PerformanceKnowledgeBase,
    scene_weights: dict[str, float] | None,
) -> dict[str, float]:
    """Return one normalized relevance mass over benchmark sources.

    Omitting weights means equal relevance across every source in the
    knowledge base. Explicit weights may include zero-mass sources, but must
    otherwise be finite, non-negative, and contain positive total mass.
    """
    if scene_weights is None:
        source_ids = list(dict.fromkeys(entry.source_id for entry in kb.entries))
        if not source_ids:
            return {}
        uniform_weight = 1.0 / len(source_ids)
        return {source_id: uniform_weight for source_id in source_ids}

    validated: dict[str, float] = {}
    for source_id, value in scene_weights.items():
        weight = float(value)
        if not math.isfinite(weight) or weight < 0.0:
            raise ValueError("scene weights must be finite and non-negative")
        validated[source_id] = weight
    total_weight = math.fsum(validated.values())
    if total_weight <= 0.0:
        raise ValueError("scene weights must contain positive total mass")
    return {
        source_id: weight / total_weight
        for source_id, weight in validated.items()
    }


def build_recall_coverage(
    kb: PerformanceKnowledgeBase,
    tool_ids: list[str],
    *,
    scene_weights: dict[str, float] | None = None,
) -> RecallCoverageMatrix:
    """Aggregate category evidence with normalized scene relevance ``w_D``.

    ``detected`` and ``total`` retain raw evidence volume for audit. Explicit
    weights are normalized at this boundary; omitted weights mean uniform
    relevance across knowledge-base sources. ``R_hat`` and ``n_eff`` use
    normalized similarity-effective counts:

    ``R_hat = sum(w_D * detected_D) / sum(w_D * total_D)``
    ``n_eff = sum(w_D * total_D)``.
    """
    normalized_weights = _normalized_scene_weights(kb, scene_weights)
    requested_by_key: dict[str, str] = {}
    for tool_id in tool_ids:
        requested_by_key.setdefault(_tool_key(tool_id), tool_id)

    selected_sources = set(normalized_weights)
    count_totals: dict[tuple[str, str], tuple[int, int, float, float]] = {}
    score_totals: dict[tuple[str, str], tuple[float, float]] = {}
    observed_categories: set[str] = set()

    for entry in kb.entries:
        if entry.source_id not in selected_sources:
            continue
        scene_weight = normalized_weights[entry.source_id]
        for observation in entry.tool_performance_data:
            tool = requested_by_key.get(_tool_key(observation.tool_name))
            if tool is None:
                continue
            counts = observation.vulnerability_score_counts or {}
            scores = observation.vulnerability_scores or {}
            observed_categories.update(counts)
            observed_categories.update(scores)
            for category, count in counts.items():
                raw_detected, raw_total, weighted_detected, weighted_total = count_totals.get(
                    (tool, category),
                    (0, 0, 0.0, 0.0),
                )
                count_totals[(tool, category)] = (
                    raw_detected + count.detected,
                    raw_total + count.total,
                    weighted_detected + scene_weight * count.detected,
                    weighted_total + scene_weight * count.total,
                )
            for category, score in scores.items():
                if (tool, category) in count_totals:
                    continue
                weighted_score, accumulated_weight = score_totals.get(
                    (tool, category),
                    (0.0, 0.0),
                )
                score_totals[(tool, category)] = (
                    weighted_score + scene_weight * float(score),
                    accumulated_weight + scene_weight,
                )

    rows: list[RecallCoverageEntry] = []
    for tool in tool_ids:
        for category in sorted(observed_categories):
            raw = count_totals.get((tool, category))
            score = score_totals.get((tool, category))
            detected: int | None = None
            total: int | None = None
            rate: float | None = None
            n_eff: float | None = None
            if raw is not None:
                detected, total, weighted_detected, weighted_total = raw
                n_eff = weighted_total
                rate = weighted_detected / weighted_total if weighted_total > 0.0 else None
            elif score is not None:
                weighted_score, weight = score
                rate = weighted_score / weight if weight > 0.0 else None

            if complement_count_eligible(rate=rate, n_eff=n_eff):
                support_level = "eligible"
            elif rate is not None and rate > 0.0:
                support_level = "under_evidenced"
            else:
                support_level = "unsupported"
            rows.append(
                RecallCoverageEntry(
                    tool=tool,
                    category=category,
                    detected=detected,
                    total=total,
                    R_hat=rate,
                    n_eff=n_eff,
                    support_level=support_level,
                )
            )

    return RecallCoverageMatrix(taxonomy_level="parent", matrix=rows)
