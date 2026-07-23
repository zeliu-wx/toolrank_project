"""Build Stage 2 category recall evidence from benchmark counts."""

from __future__ import annotations

import re

from toolrank.assignment_evidence import complement_count_eligible
from toolrank.schemas import PerformanceKnowledgeBase
from toolrank.schemas_v2 import RecallCoverageEntry, RecallCoverageMatrix


def _tool_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def build_recall_coverage(
    kb: PerformanceKnowledgeBase,
    tool_ids: list[str],
    *,
    scene_densities: dict[str, float] | None = None,
) -> RecallCoverageMatrix:
    """Aggregate category evidence with raw KDE density ``p_hat_D``.

    ``detected`` and ``total`` retain raw evidence volume for audit. ``R_hat``
    and ``n_eff`` use the similarity-effective counts:

    ``R_hat = sum(p_hat_D * detected_D) / sum(p_hat_D * total_D)``
    ``n_eff = sum(p_hat_D * total_D)``.
    """
    requested_by_key: dict[str, str] = {}
    for tool_id in tool_ids:
        requested_by_key.setdefault(_tool_key(tool_id), tool_id)

    selected_sources = set(scene_densities) if scene_densities is not None else None
    count_totals: dict[tuple[str, str], tuple[int, int, float, float]] = {}
    score_totals: dict[tuple[str, str], tuple[float, float]] = {}
    observed_categories: set[str] = set()

    for entry in kb.entries:
        if selected_sources is not None and entry.source_id not in selected_sources:
            continue
        density = scene_densities.get(entry.source_id, 0.0) if scene_densities is not None else 1.0
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
                    weighted_detected + density * count.detected,
                    weighted_total + density * count.total,
                )
            for category, score in scores.items():
                if (tool, category) in count_totals:
                    continue
                weighted_score, weight = score_totals.get((tool, category), (0.0, 0.0))
                score_totals[(tool, category)] = (
                    weighted_score + density * float(score),
                    weight + density,
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
