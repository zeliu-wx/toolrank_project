"""Scene-pool weighting (design 4.2): rank benchmark datasets by how densely
their contracts surround a target contract.

Group-balanced Gower distance over phi=(solc, loc, +5 complexity): ½ weight on
the version group, ½ on the 6-dim structure group (each structural dim 1/12),
with log(1+x), range-normalized numeric dims; Gaussian KDE density per dataset;
normalize to weights. A single global bandwidth (leave-one-out CV, subsampled)
is shared across datasets and precomputed offline. Pure stdlib.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

from toolrank._complexity import NUM_DIMS


@dataclass
class ProfileKB:
    rlog: dict[str, float]            # log-range per numeric dim
    contracts: list[dict]             # each: {ds, solc, g:[6]}
    bandwidth: float
    dataset_names: list[str]


def _rlog(ranges: dict) -> dict[str, float]:
    out = {}
    for dim in NUM_DIMS:
        lo, hi = ranges[dim]
        r = math.log1p(hi) - math.log1p(lo)
        out[dim] = r if r > 0 else 1.0
    return out


def normalize(phi: dict, rlog: dict[str, float]) -> list[float]:
    return [math.log1p(phi[dim]) / rlog[dim] for dim in NUM_DIMS]


def gower(solc_a: str, g_a: list[float], solc_b: str, g_b: list[float]) -> float:
    # Group-balanced Gower: ½ on the version group, ½ on the structure group.
    # num = Σ_{6 dim} |ĝ−ĝ_x|/R_j (g already log1p/range-normalized), so the
    # structural term is (1/12)·num and each structural dim carries 1/12.
    cat = 0.0 if solc_a == solc_b else 1.0
    num = sum(abs(x - y) for x, y in zip(g_a, g_b))
    return 0.5 * cat + num / 12.0


def fit_bandwidth(contracts: list[dict], sample_size: int = 300, seed: int = 0) -> float:
    rnd = random.Random(seed)
    n = len(contracts)
    if n < 2:
        return 0.18
    idx = rnd.sample(range(n), min(sample_size, n))
    cache = [
        (i, [gower(contracts[i]["solc"], contracts[i]["g"], contracts[j]["solc"], contracts[j]["g"]) ** 2
             for j in range(n)])
        for i in idx
    ]
    best_h, best_ll = 0.18, -1e18
    for h in [0.01, 0.02, 0.03, 0.05, 0.08, 0.12, 0.18, 0.25, 0.35]:
        denom = 2 * h * h
        norm = 1.0 / (h * math.sqrt(2 * math.pi))
        ll = 0.0
        for i, d2 in cache:
            s = sum(norm * math.exp(-v / denom) for j, v in enumerate(d2) if j != i)
            dens = s / (n - 1)
            ll += math.log(dens) if dens > 0 else -50.0
        if ll > best_ll:
            best_ll, best_h = ll, h
    return best_h


def load_profiles(path: str | Path) -> ProfileKB:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    rlog = _rlog(d["_ranges"])
    contracts = []
    for ds, samples in d["datasets"].items():
        for s in samples:
            contracts.append({"ds": ds, "solc": s["solc"], "g": normalize(s, rlog)})
    bandwidth = d.get("_bandwidth") or fit_bandwidth(contracts)
    return ProfileKB(rlog=rlog, contracts=contracts, bandwidth=bandwidth,
                     dataset_names=list(d["datasets"].keys()))


def scene_weights(target_phi: dict, kb: ProfileKB) -> dict[str, dict[str, float]]:
    """Return {dataset_name: {"weight": w, "distance": mean_gower}} over all datasets."""
    h = kb.bandwidth
    denom = 2 * h * h
    tg = normalize(target_phi, kb.rlog)
    tsolc = target_phi["solc"]
    acc: dict[str, float] = {}
    dist_sum: dict[str, float] = {}
    cnt: dict[str, int] = {}
    for c in kb.contracts:
        d = gower(tsolc, tg, c["solc"], c["g"])
        acc[c["ds"]] = acc.get(c["ds"], 0.0) + math.exp(-(d * d) / denom)
        dist_sum[c["ds"]] = dist_sum.get(c["ds"], 0.0) + d
        cnt[c["ds"]] = cnt.get(c["ds"], 0) + 1
    density = {ds: acc[ds] / cnt[ds] for ds in acc}
    total = sum(density.values())
    return {
        ds: {
            "weight": (density[ds] / total) if total > 0 else 0.0,
            "density": density[ds],
            "distance": dist_sum[ds] / cnt[ds],
        }
        for ds in density
    }
