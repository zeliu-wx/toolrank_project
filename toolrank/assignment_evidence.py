"""Shared assignment-evidence rules for tool category ownership."""

from __future__ import annotations

import os

from toolrank.recall_ci import newcombe_diff_interval, wilson_half_width, wilson_interval


EPSILON_R = 0.15  # CI half-width tolerance (estimate-precision); shared with the stage-1/2 weakness CI


MIN_N_EFF = 15.0  # pure effective-sample floor; replaces Wilson CI half-width gate


def is_strong_eligible(
    detected: int | None,
    effective_total: float | None,
    rate: float | None,
    *,
    epsilon_r: float = EPSILON_R,
) -> bool:
    """Ownership eligibility: rate > 0 and enough effective evidence.

    Uses a pure effective-sample floor (MIN_N_EFF) instead of Wilson CI half-width.
    Override at runtime via TOOLRANK_MIN_NEFF env var.
    """
    _ = detected
    if rate is None or effective_total is None or effective_total <= 0:
        return False
    raw = os.getenv("TOOLRANK_MIN_NEFF", "").strip()
    if raw.lower() == "wilson":
        d_eff = rate * effective_total
        _p, low, high = wilson_interval(d_eff, effective_total)
        return low > 0.0 and (high - low) / 2.0 <= epsilon_r
    threshold = float(raw) if raw else MIN_N_EFF
    return rate > 0 and effective_total >= threshold


is_assignment_eligible = is_strong_eligible


def is_recall_ci_sufficient(
    detected: int | None,
    effective_total: float | None,
    rate: float | None,
    *,
    epsilon_r: float = 0.15,
) -> bool:
    # Stage-2 per-ownership recall gate (paper III.B): precision-of-estimate test,
    # accept iff the recall 95% CI half-width <= epsilon_r. Mirrors the Stage-1 call
    # in evidence_packet.py (d_eff = rate*n_eff, n_eff = effective_total).
    _ = detected
    return (
        rate is not None
        and effective_total is not None
        and effective_total > 0
        and wilson_half_width(rate * effective_total, effective_total) <= epsilon_r
    )


def is_weak_eligible(
    detected: int | None,
    total: int | None,
    rate: float | None,
    feasible: bool,
) -> bool:
    _ = (detected, total)
    return feasible and rate is not None and rate > 0.0


def count_text(detected: int | None, total: int | None) -> str:
    if detected is None or total is None:
        return "unknown"
    return f"{detected}/{total}"


def rate_text(rate: float | None) -> str:
    if rate is None:
        return "None"
    return f"{rate:.4f}"


def is_close_local_margin(
    rate_a: float | None,
    effective_total_a: float | None,
    rate_b: float | None,
    effective_total_b: float | None,
) -> bool:
    """Two local candidates are statistically tied when the Newcombe 95% CI for the
    recall difference straddles 0 (no fixed margin). The CI is computed on the
    similarity-effective sample (d_eff = rate*effective_total), matching is_strong_eligible;
    passing the raw detected count against a kernel-density-weighted effective_total would
    yield p>1 and crash wilson_interval."""
    if (
        rate_a is None or effective_total_a is None or effective_total_a <= 0
        or rate_b is None or effective_total_b is None or effective_total_b <= 0
    ):
        return False
    _diff, low, high = newcombe_diff_interval(
        rate_a * effective_total_a, effective_total_a,
        rate_b * effective_total_b, effective_total_b,
    )
    return low <= 0.0 <= high
