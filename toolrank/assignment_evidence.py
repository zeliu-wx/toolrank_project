"""Hard quantitative eligibility rule for Stage 2 complements."""

from __future__ import annotations

from toolrank.recall_ci import newcombe_diff_interval
from toolrank.schemas_v2 import ComplementStrengthResult


MIN_N_EFF = 15.0


def complement_count_eligible(
    *,
    rate: float | None,
    n_eff: float | None,
) -> bool:
    """Require positive category recall evidence and ``n_eff >= 15``.

    This rule never certifies, rejects, or replaces the Stage 1 primary tool.
    """
    return rate is not None and rate > 0.0 and n_eff is not None and n_eff >= MIN_N_EFF


def complement_strength_against_primary(
    *,
    candidate_rate: float | None,
    candidate_n_eff: float | None,
    primary_rate: float | None,
    primary_n_eff: float | None,
) -> ComplementStrengthResult:
    """Decide whether candidate category evidence is stronger than the primary.

    A reliable positive primary baseline requires the candidate-minus-primary
    Newcombe Recall-gap lower bound to be strictly positive.  Missing,
    non-positive, or under-evidenced primary statistics do not support a
    fabricated numeric comparison; a positive count-qualified candidate is
    evidence-stronger in that case.
    """
    candidate_qualified = complement_count_eligible(
        rate=candidate_rate,
        n_eff=candidate_n_eff,
    )
    primary_qualified = complement_count_eligible(
        rate=primary_rate,
        n_eff=primary_n_eff,
    )
    if not candidate_qualified:
        return ComplementStrengthResult(
            candidate_count_qualified=False,
            primary_count_qualified_positive=primary_qualified,
            evidence_stronger=False,
            basis="CANDIDATE_COUNT_INELIGIBLE",
            reason_code="CANDIDATE_COUNT_EVIDENCE_INELIGIBLE",
        )
    if not primary_qualified:
        return ComplementStrengthResult(
            candidate_count_qualified=True,
            primary_count_qualified_positive=False,
            evidence_stronger=True,
            basis="PRIMARY_BASELINE_UNRELIABLE",
            reason_code="COUNT_QUALIFIED_CANDIDATE_WITHOUT_RELIABLE_POSITIVE_PRIMARY",
        )

    assert candidate_rate is not None and candidate_n_eff is not None
    assert primary_rate is not None and primary_n_eff is not None
    gap, low, high = newcombe_diff_interval(
        candidate_rate * candidate_n_eff,
        candidate_n_eff,
        primary_rate * primary_n_eff,
        primary_n_eff,
    )
    stronger = low > 0.0
    return ComplementStrengthResult(
        candidate_count_qualified=True,
        primary_count_qualified_positive=True,
        evidence_stronger=stronger,
        basis="NEWCOMBE_CANDIDATE_MINUS_PRIMARY",
        reason_code=(
            "CANDIDATE_RECALL_CREDIBLY_STRONGER"
            if stronger
            else "CANDIDATE_RECALL_NOT_CREDIBLY_STRONGER"
        ),
        recall_gap=gap,
        recall_gap_low=low,
        recall_gap_high=high,
    )
