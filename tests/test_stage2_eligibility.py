from __future__ import annotations

import pytest

from toolrank.assignment_evidence import (
    MIN_N_EFF,
    complement_count_eligible,
    complement_strength_against_primary,
)


@pytest.mark.parametrize(
    ("n_eff", "expected"),
    [(14.999999, False), (15.0, True), (15.000001, True)],
)
def test_complement_neff_threshold_is_hard_and_inclusive(n_eff: float, expected: bool) -> None:
    assert MIN_N_EFF == 15.0
    assert complement_count_eligible(rate=0.5, n_eff=n_eff) is expected


def test_complement_requires_positive_category_recall() -> None:
    assert complement_count_eligible(rate=0.0, n_eff=100.0) is False
    assert complement_count_eligible(rate=None, n_eff=100.0) is False
    assert complement_count_eligible(rate=0.5, n_eff=None) is False


def test_real_smartcheck_shape_is_not_stronger_than_slither() -> None:
    result = complement_strength_against_primary(
        candidate_rate=0.000696,
        candidate_n_eff=662.0,
        primary_rate=0.005064,
        primary_n_eff=662.0,
    )

    assert result.candidate_count_qualified is True
    assert result.primary_count_qualified_positive is True
    assert result.evidence_stronger is False
    assert result.basis == "NEWCOMBE_CANDIDATE_MINUS_PRIMARY"
    assert result.recall_gap == pytest.approx(-0.004368)
    assert result.recall_gap_low == pytest.approx(-0.013346624890933943)


def test_credible_newcombe_gap_accepts_a_stronger_candidate() -> None:
    result = complement_strength_against_primary(
        candidate_rate=0.8,
        candidate_n_eff=100.0,
        primary_rate=0.2,
        primary_n_eff=100.0,
    )

    assert result.evidence_stronger is True
    assert result.recall_gap_low == pytest.approx(0.47437404888489243)
    assert result.reason_code == "CANDIDATE_RECALL_CREDIBLY_STRONGER"


def test_higher_point_estimate_is_rejected_when_newcombe_lower_bound_is_not_positive() -> None:
    result = complement_strength_against_primary(
        candidate_rate=0.6,
        candidate_n_eff=15.0,
        primary_rate=0.5,
        primary_n_eff=15.0,
    )

    assert result.recall_gap == pytest.approx(0.1)
    assert result.recall_gap_low is not None and result.recall_gap_low < 0.0
    assert result.evidence_stronger is False
    assert result.reason_code == "CANDIDATE_RECALL_NOT_CREDIBLY_STRONGER"


@pytest.mark.parametrize(
    ("primary_rate", "primary_n_eff"),
    [
        (None, None),
        (None, 100.0),
        (0.0, 100.0),
        (0.2, 14.999999),
    ],
)
def test_positive_count_qualified_candidate_is_stronger_without_reliable_primary_baseline(
    primary_rate: float | None,
    primary_n_eff: float | None,
) -> None:
    result = complement_strength_against_primary(
        candidate_rate=0.5,
        candidate_n_eff=15.0,
        primary_rate=primary_rate,
        primary_n_eff=primary_n_eff,
    )

    assert result.candidate_count_qualified is True
    assert result.primary_count_qualified_positive is False
    assert result.evidence_stronger is True
    assert result.basis == "PRIMARY_BASELINE_UNRELIABLE"
    assert result.recall_gap is None
    assert result.recall_gap_low is None
    assert result.recall_gap_high is None
