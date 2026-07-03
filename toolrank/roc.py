"""Rank-Order Centroid weights for recall/precision preferences (n=2).

The two preference dimensions (recall, precision) are ranked by their
{Best, Prefer, Default} labels; ROC with n=2 gives the higher-ranked dim 3/4
and the lower 1/4, with a tie splitting 1/2 each. Weights sum to 1.

The general Rank-Order Centroid formula for n ranked items is
    w_i = (1/n) * sum_{j=i}^{n} (1/j)
where i is the 1-based rank of the item. For n=2 this yields rank-1 = 0.75
and rank-2 = 0.25; a tie averages the two ranks -> 0.5 each.
"""
from __future__ import annotations

from typing import Literal

PreferenceLevel = Literal["Best", "Prefer", "Default"]

_ORDER = {"Best": 3, "Prefer": 2, "Default": 1}


def roc_centroid_weights(n: int) -> list[float]:
    """Rank-Order Centroid weights for n ranked items: w_i = (1/n) sum_{j=i}^n 1/j."""
    return [sum(1.0 / j for j in range(i, n + 1)) / n for i in range(1, n + 1)]


def roc_weights(recall: PreferenceLevel, precision: PreferenceLevel) -> tuple[float, float]:
    """Return (w_recall, w_precision), summing to 1."""
    r, p = _ORDER[recall], _ORDER[precision]
    w_rank1, w_rank2 = roc_centroid_weights(2)
    if r > p:
        return (w_rank1, w_rank2)
    if r < p:
        return (w_rank2, w_rank1)
    tie = (w_rank1 + w_rank2) / 2.0
    return (tie, tie)
