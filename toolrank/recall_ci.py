"""Confidence-interval helpers for Stage 1 scene-conditioned recall gates.

Sufficiency = recall 95% CI half-width <= epsilon_r; weakness = (peer - primary)
recall-gap 95% CI lower bound > 0. Single-dataset proportions use Wilson /
Newcombe (closed-form); KDE-weighted cross-dataset aggregates use a
Jeffreys-posterior (Beta) resampling. All randomized CIs are seeded for reproducibility.
"""
from __future__ import annotations

import math

import numpy as np

from toolrank.schemas import PerformanceKnowledgeBase
from toolrank.schemas_v2 import ScenePool

Z_95 = 1.96  # 95% two-sided normal quantile (CONSORT convention)
N_BOOTSTRAP = 2000  # percentile-bootstrap resamples; numerical-precision knob
BOOTSTRAP_SEED = 0  # fixed seed -> reproducible CIs


def wilson_interval(detected: float, total: float, z: float = Z_95) -> tuple[float, float, float]:
    # detected/total may be kernel-density-effective (non-integer) counts.
    if total <= 0:
        raise ValueError("wilson_interval requires total > 0")
    p = detected / total
    denom = 1.0 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return p, max(0.0, center - half), min(1.0, center + half)


def wilson_half_width(detected: float, total: float, z: float = Z_95) -> float:
    _, low, high = wilson_interval(detected, total, z)
    return (high - low) / 2.0


def newcombe_diff_interval(
    d1: float, n1: float, d2: float, n2: float, z: float = Z_95
) -> tuple[float, float, float]:
    """95% CI for p1 - p2 (Newcombe method 10, from each Wilson interval)."""
    p1, l1, u1 = wilson_interval(d1, n1, z)
    p2, l2, u2 = wilson_interval(d2, n2, z)
    diff = p1 - p2
    low = diff - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    high = diff + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return diff, low, high


Row = tuple[float, int, int]  # (p_hat weight, detected, total)


def weighted_recall(rows: list[Row]) -> float | None:
    num = sum(w * d for w, d, _ in rows)
    den = sum(w * m for w, _, m in rows)
    return num / den if den > 0 else None


def _bootstrap_weighted_recalls(rows: list[Row], n_boot: int, rng: np.random.Generator) -> np.ndarray:
    # Jeffreys posterior on the similarity-EFFECTIVE sample: n_eff = sum(p_hat*m),
    # d_eff = sum(p_hat*d). CI width reflects n_eff, so dissimilar datasets (small
    # p_hat -> small n_eff) widen the CI -> insufficient, matching the n_eff gate.
    # Robust at p in {0,1} (Beta never degenerates).
    d_eff = sum(w * d for w, d, _ in rows)
    n_eff = sum(w * m for w, _, m in rows)
    if n_eff <= 0:
        return np.zeros(n_boot)
    return rng.beta(d_eff + 0.5, (n_eff - d_eff) + 0.5, size=n_boot)


def bootstrap_recall_ci(
    rows: list[Row], conf: float = 0.95, n_boot: int = N_BOOTSTRAP, seed: int = BOOTSTRAP_SEED
) -> tuple[float, float, float] | None:
    rows = [(w, d, m) for w, d, m in rows if m > 0]
    point = weighted_recall(rows)
    if point is None:
        return None
    rng = np.random.default_rng(seed)
    samples = _bootstrap_weighted_recalls(rows, n_boot, rng)
    low = float(np.percentile(samples, (1 - conf) / 2 * 100))
    high = float(np.percentile(samples, (1 + conf) / 2 * 100))
    return point, low, high


def bootstrap_gap_ci(
    primary_rows: list[Row],
    peer_rows: list[Row],
    conf: float = 0.95,
    n_boot: int = N_BOOTSTRAP,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float, float] | None:
    """95% CI for (peer recall - primary recall); LCB > 0 means primary is weaker."""
    pr = [(w, d, m) for w, d, m in primary_rows if m > 0]
    pe = [(w, d, m) for w, d, m in peer_rows if m > 0]
    r_p = weighted_recall(pr)
    r_e = weighted_recall(pe)
    if r_p is None or r_e is None:
        return None
    rng = np.random.default_rng(seed)
    sp = _bootstrap_weighted_recalls(pr, n_boot, rng)
    se = _bootstrap_weighted_recalls(pe, n_boot, rng)
    gap_samples = se - sp
    gap = r_e - r_p
    low = float(np.percentile(gap_samples, (1 - conf) / 2 * 100))
    high = float(np.percentile(gap_samples, (1 + conf) / 2 * 100))
    return gap, low, high


def filter_scene_pool_to_count_bearing(
    scene_pool: ScenePool, kb: PerformanceKnowledgeBase
) -> ScenePool:
    """Drop neighbors whose dataset has no count-bearing observations; renormalize weight."""
    count_bearing = {
        entry.source_id
        for entry in kb.entries
        if any((obs.vulnerability_score_counts or {}) for obs in entry.tool_performance_data)
    }
    kept = [n for n in scene_pool.neighbors if n.paper_id in count_bearing]
    total_w = sum(n.weight for n in kept)
    neighbors = [
        n.model_copy(update={"weight": (n.weight / total_w if total_w > 0 else 0.0)})
        for n in kept
    ]
    return scene_pool.model_copy(update={"neighbors": neighbors})
