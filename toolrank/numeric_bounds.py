"""Numerical boundary helpers for normalized probability masses."""

from __future__ import annotations

import math


NORMALIZED_MASS_ABS_TOLERANCE = 1e-12


def clamp_normalized_mass(value: float) -> float:
    """Clamp only floating-point drift immediately outside ``[0, 1]``.

    Values materially outside the unit interval are returned unchanged so the
    schema that owns the bound still rejects them.
    """
    if not math.isfinite(value):
        return value
    if -NORMALIZED_MASS_ABS_TOLERANCE <= value < 0.0:
        return 0.0
    if 1.0 < value <= 1.0 + NORMALIZED_MASS_ABS_TOLERANCE:
        return 1.0
    return value
