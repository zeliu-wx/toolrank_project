"""Build benchmark scene pools by Gower + KDE over per-contract profiles.

For a target contract, scene_kde weights every benchmark dataset by how densely
its contracts surround the target (design 4.2). Each weighted dataset is mapped
back to its performance-KB entry by dataset_name, so neighbors keep the same
shape (paper_id = perf-KB source_id) that certification, CEGO, and the evidence
packet already consume. Datasets without a per-contract profile simply do not
appear in the pool.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from toolrank import scene_kde
from toolrank.schemas import ContractFeatures, PerformanceEntry, PerformanceKnowledgeBase
from toolrank.schemas_v2 import SceneNeighbor, ScenePool

_DEFAULT_PROFILES_PATH = "toolcards/contract_profiles.json"


@lru_cache(maxsize=4)
def _load_profile_kb(path: str) -> scene_kde.ProfileKB:
    return scene_kde.load_profiles(path)


def _target_phi(features: ContractFeatures) -> dict | None:
    if features.loc_total <= 0:
        return None
    bucket = "unknown"
    if features.primary_solidity_version:
        m = re.match(r"(\d+)\.(\d+)", features.primary_solidity_version)
        if m:
            bucket = f"{m.group(1)}.{m.group(2)}.x"
    return {
        "solc": bucket,
        "loc": features.loc_total,
        "avg_cyc": features.cyclomatic_avg,
        "max_cyc": features.cyclomatic_max,
        "sum_cyc": features.cyclomatic_sum,
        "max_nest": features.max_nesting,
        "coupling": features.contract_coupling,
    }


def build_scene_pool(
    features: ContractFeatures,
    kb: PerformanceKnowledgeBase,
    profiles_path: str | Path | None = None,
) -> ScenePool:
    if not kb.entries:
        return ScenePool(neighbors=[])
    path = str(profiles_path or _DEFAULT_PROFILES_PATH)
    if not Path(path).exists():
        return ScenePool(neighbors=[])
    target = _target_phi(features)
    if target is None:
        return ScenePool(neighbors=[])

    weighted = scene_kde.scene_weights(target, _load_profile_kb(path))
    if not weighted:
        return ScenePool(neighbors=[])

    entry_by_name: dict[str, PerformanceEntry] = {}
    for entry in kb.entries:
        entry_by_name.setdefault(entry.dataset_profile.dataset_name, entry)

    # No top-K cutoff: every dataset keeps its Gower-KDE weight w_D; dissimilar
    # datasets carry ~0 weight and self-attenuate downstream (no arbitrary K).
    ranked = sorted(weighted.items(), key=lambda kv: -kv[1]["weight"])
    selected = [(name, info) for name, info in ranked if name in entry_by_name]
    if not selected:
        return ScenePool(neighbors=[])

    equal_w = os.environ.get("TOOLRANK_EQUAL_WEIGHTS", "").strip().lower() in {"1", "true", "yes", "on"}
    weight_total = sum(info["weight"] for _name, info in selected) or 1.0
    uniform = 1.0 / len(selected) if selected else 1.0
    neighbors = [
        SceneNeighbor(
            slice_id=f"{entry_by_name[name].source_id}_{name}",
            benchmark_family=_benchmark_family(name),
            paper_id=entry_by_name[name].source_id,
            weight=uniform if equal_w else info["weight"] / weight_total,
            kernel_density=uniform if equal_w else info["density"],
            distance=info["distance"],
            category_profile=_category_profile(entry_by_name[name]),
            provenance_refs=[entry_by_name[name].source_id],
        )
        for name, info in selected
    ]
    return ScenePool(neighbors=neighbors)


def _benchmark_family(dataset_name: str) -> str:
    parts = dataset_name.split()
    return parts[0] if parts else dataset_name


def _category_profile(entry: PerformanceEntry) -> dict[str, float]:
    profile = entry.dataset_profile
    categories = getattr(profile, "vulnerability_categories", None)
    if not categories and profile.complexity_stats is not None:
        categories = profile.complexity_stats.vulnerability_categories
    if not categories:
        return {}

    unique_categories = list(dict.fromkeys(categories))
    weight = 1.0 / len(unique_categories)
    return {category: weight for category in unique_categories}
