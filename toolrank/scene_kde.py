"""Scene-pool weighting (design 4.2): rank benchmark datasets by how densely
their contracts surround a target contract.

Group-balanced Gower distance over phi=(solc, loc, +5 complexity): ½ weight on
the version group, ½ on the 6-dim structure group (each structural dim 1/12),
with log(1+x), range-normalized numeric dims; Gaussian KDE density per dataset;
normalize to weights. A single global bandwidth (leave-one-out CV, subsampled)
is shared across datasets and precomputed offline. Pure stdlib.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from toolrank._complexity import (
    CANONICAL_PROFILE_ENGINE,
    CANONICAL_PROFILING_BUCKET_ORDER,
    CANONICAL_PROFILING_COMPILERS,
    NO_PRAGMA_PROFILING_BUCKET_ORDER,
    NUM_DIMS,
    PROFILE_ARTIFACT_SCHEMA,
    PROFILE_FAILURE_CLASSES,
    PROFILE_MANIFEST_SCHEMA,
    PROFILE_NORMALIZATIONS,
    PROFILE_SAMPLE_UNIT,
)


BANDWIDTH_GRID = (0.01, 0.02, 0.03, 0.05, 0.08, 0.12, 0.18, 0.25, 0.35)
BANDWIDTH_SEED = 0
BANDWIDTH_SAMPLE_SIZE = 300
BANDWIDTH_METHOD = "seeded_leave_one_out_gaussian_grid_v1"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class ProfileArtifactError(ValueError):
    """Raised when a packaged contract-profile artifact is not comparable."""


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


def fit_bandwidth(
    contracts: list[dict],
    sample_size: int = BANDWIDTH_SAMPLE_SIZE,
    seed: int = BANDWIDTH_SEED,
    grid: tuple[float, ...] = BANDWIDTH_GRID,
) -> float:
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
    for h in grid:
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


def profiles_digest(datasets: dict[str, list[dict]]) -> str:
    encoded = json.dumps(
        datasets,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def coverage_source_digest(coverage: dict[str, dict]) -> str:
    """Bind global source provenance to each ordered dataset inventory digest."""
    encoded = json.dumps(
        {name: item["source_digest"] for name, item in coverage.items()},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def bandwidth_fit_digest(
    *,
    profiles_digest: str,
    ranges: dict,
    bandwidth: float,
    provenance: dict,
) -> str:
    """Bind a fitted bandwidth to its exact samples, ranges, and search policy.

    Runtime validates this linkage without fitting a replacement bandwidth.
    Deterministic builder tests independently verify that the linked value is
    the seeded grid-search result.
    """
    material = {
        "profiles_digest": profiles_digest,
        "ranges": ranges,
        "bandwidth": bandwidth,
        "method": provenance.get("method"),
        "seed": provenance.get("seed"),
        "sample_size": provenance.get("sample_size"),
        "grid": provenance.get("grid"),
    }
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _safe_relative_path(value: object) -> bool:
    if not isinstance(value, str) or not value or "\x00" in value:
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def _finite_number(value, *, label: str, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProfileArtifactError(f"{label} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric) or (nonnegative and numeric < 0):
        raise ProfileArtifactError(f"{label} has an invalid numeric value")
    return numeric


def _validate_artifact(data: object) -> tuple[dict, dict[str, list[dict]]]:
    if not isinstance(data, dict):
        raise ProfileArtifactError("profile artifact must be a JSON object")
    meta = data.get("_meta")
    datasets = data.get("datasets")
    ranges = data.get("_ranges")
    counts = data.get("_counts")
    coverage = data.get("_coverage")
    if not all(isinstance(value, dict) for value in (meta, datasets, ranges, counts, coverage)):
        raise ProfileArtifactError("profile artifact metadata sections are missing or malformed")
    if meta.get("schema_version") != PROFILE_ARTIFACT_SCHEMA:
        raise ProfileArtifactError("profile artifact schema is incompatible")
    if meta.get("engine") != CANONICAL_PROFILE_ENGINE:
        raise ProfileArtifactError("profile artifact engine is incompatible")
    if meta.get("sample_unit") != PROFILE_SAMPLE_UNIT:
        raise ProfileArtifactError("profile artifact sample unit is incompatible")
    if meta.get("dimensions") != ["solc", *NUM_DIMS]:
        raise ProfileArtifactError("profile artifact dimensions are incompatible")
    if meta.get("range_dimensions") != NUM_DIMS:
        raise ProfileArtifactError("profile artifact range dimensions are incompatible")
    if meta.get("canonical_compilers") != CANONICAL_PROFILING_COMPILERS:
        raise ProfileArtifactError("profile artifact compiler map is incompatible")
    if meta.get("compiler_selection") != {
        "constrained_bucket_order": list(CANONICAL_PROFILING_BUCKET_ORDER),
        "no_pragma_bucket_order": list(NO_PRAGMA_PROFILING_BUCKET_ORDER),
    }:
        raise ProfileArtifactError("profile artifact compiler selection is incompatible")
    if meta.get("normalizations") != PROFILE_NORMALIZATIONS:
        raise ProfileArtifactError("profile artifact source normalization is incompatible")
    if meta.get("failure_classes") != PROFILE_FAILURE_CLASSES:
        raise ProfileArtifactError("profile artifact failure classes are incompatible")
    if meta.get("manifest_version") != PROFILE_MANIFEST_SCHEMA:
        raise ProfileArtifactError("profile artifact manifest schema is incompatible")
    for digest_name in ("manifest_digest", "source_digest", "profiles_digest"):
        digest = meta.get(digest_name)
        if not _valid_sha256(digest):
            raise ProfileArtifactError(f"profile artifact {digest_name} is invalid")
    if not isinstance(meta.get("generated_at"), str) or not meta["generated_at"]:
        raise ProfileArtifactError("profile artifact generation timestamp is missing")
    if not datasets:
        raise ProfileArtifactError("profile artifact contains no datasets")
    if list(datasets) != meta.get("dataset_names"):
        raise ProfileArtifactError("profile artifact dataset order does not match metadata")
    if set(datasets) != set(counts) or set(datasets) != set(coverage):
        raise ProfileArtifactError("profile artifact dataset metadata is incomplete")
    if set(ranges) != set(NUM_DIMS):
        raise ProfileArtifactError("profile artifact range metadata is incomplete")
    if any(not _nonnegative_int(value) or value == 0 for value in counts.values()):
        raise ProfileArtifactError("profile artifact dataset counts are malformed")

    excluded = meta.get("excluded_datasets")
    if not isinstance(excluded, list):
        raise ProfileArtifactError("profile artifact exclusions are malformed")
    excluded_names: set[str] = set()
    for row in excluded:
        if not isinstance(row, dict):
            raise ProfileArtifactError("profile artifact exclusions are malformed")
        expected_keys = {"name", "path", "reason"}
        if "duplicate_of" in row:
            expected_keys.add("duplicate_of")
        if (
            set(row) != expected_keys
            or not isinstance(row.get("name"), str)
            or not row["name"]
            or row["name"] in excluded_names
            or row["name"] in datasets
            or not _safe_relative_path(row.get("path"))
            or not isinstance(row.get("reason"), str)
            or not row["reason"]
            or (
                "duplicate_of" in row
                and (
                    not isinstance(row["duplicate_of"], str)
                    or row["duplicate_of"] not in datasets
                )
            )
        ):
            raise ProfileArtifactError("profile artifact exclusions are malformed")
        excluded_names.add(row["name"])

    bandwidth = _finite_number(data.get("_bandwidth"), label="_bandwidth")
    if bandwidth <= 0:
        raise ProfileArtifactError("profile artifact bandwidth must be positive")
    bandwidth_meta = meta.get("bandwidth")
    if not isinstance(bandwidth_meta, dict):
        raise ProfileArtifactError("profile artifact bandwidth provenance is missing")
    if (
        set(bandwidth_meta)
        != {"method", "seed", "sample_size", "grid", "fit_digest"}
        or bandwidth_meta.get("method") != BANDWIDTH_METHOD
        or bandwidth_meta.get("seed") != BANDWIDTH_SEED
        or bandwidth_meta.get("sample_size") != BANDWIDTH_SAMPLE_SIZE
        or bandwidth_meta.get("grid") != list(BANDWIDTH_GRID)
        or bandwidth not in BANDWIDTH_GRID
        or not _valid_sha256(bandwidth_meta.get("fit_digest"))
    ):
        raise ProfileArtifactError("profile artifact bandwidth provenance is incompatible")

    observed: dict[str, list[float]] = {dimension: [] for dimension in NUM_DIMS}
    sample_ids: set[str] = set()
    compiler_usage: Counter[str] = Counter()
    total_samples = 0
    for dataset_name, samples in datasets.items():
        if not isinstance(dataset_name, str) or not dataset_name:
            raise ProfileArtifactError("profile artifact has an invalid dataset name")
        if not isinstance(samples, list) or not samples:
            raise ProfileArtifactError(f"profile dataset {dataset_name!r} is empty")
        if counts[dataset_name] != len(samples):
            raise ProfileArtifactError(f"profile dataset {dataset_name!r} count is stale")
        dataset_coverage = coverage[dataset_name]
        if not isinstance(dataset_coverage, dict):
            raise ProfileArtifactError(f"profile dataset {dataset_name!r} coverage is malformed")
        attempted = dataset_coverage.get("attempted")
        succeeded = dataset_coverage.get("succeeded")
        skipped = dataset_coverage.get("skipped")
        failures = dataset_coverage.get("failure_classes")
        skipped_samples = dataset_coverage.get("skipped_samples")
        if (
            not all(_nonnegative_int(value) for value in (attempted, succeeded, skipped))
            or attempted != succeeded + skipped
            or succeeded != len(samples)
            or not isinstance(failures, dict)
            or any(
                key not in PROFILE_FAILURE_CLASSES
                or not _nonnegative_int(value)
                or value == 0
                for key, value in failures.items()
            )
            or sum(failures.values()) != skipped
            or not isinstance(skipped_samples, list)
            or len(skipped_samples) != skipped
            or not _safe_relative_path(dataset_coverage.get("root"))
            or not _nonnegative_int(dataset_coverage.get("unsafe_paths_excluded"))
            or not _valid_sha256(dataset_coverage.get("source_digest"))
            or not _valid_sha256(dataset_coverage.get("corpus_digest"))
        ):
            raise ProfileArtifactError(f"profile dataset {dataset_name!r} coverage is inconsistent")
        observed_skip_classes: dict[str, int] = {}
        for skipped_sample in skipped_samples:
            if not isinstance(skipped_sample, dict):
                raise ProfileArtifactError(f"profile dataset {dataset_name!r} skip ledger is malformed")
            skipped_id = skipped_sample.get("id")
            failure_class = skipped_sample.get("failure_class")
            if (
                not isinstance(skipped_id, str)
                or not skipped_id
                or skipped_id in sample_ids
                or failure_class not in PROFILE_FAILURE_CLASSES
                or not skipped_id.startswith(f"{dataset_name}::")
                or not _safe_relative_path(skipped_id.split("::", 1)[1])
            ):
                raise ProfileArtifactError(f"profile dataset {dataset_name!r} skip ledger is malformed")
            sample_ids.add(skipped_id)
            observed_skip_classes[failure_class] = observed_skip_classes.get(failure_class, 0) + 1
        if observed_skip_classes != failures:
            raise ProfileArtifactError(f"profile dataset {dataset_name!r} skip ledger is inconsistent")
        for sample in samples:
            if not isinstance(sample, dict):
                raise ProfileArtifactError("profile sample must be an object")
            sample_id = sample.get("id")
            sample_path = sample.get("path")
            if (
                not isinstance(sample_id, str)
                or not sample_id
                or sample_id in sample_ids
                or not _safe_relative_path(sample_path)
                or sample_id != f"{dataset_name}::{sample_path}"
            ):
                raise ProfileArtifactError("profile sample IDs must be nonempty and globally unique")
            sample_ids.add(sample_id)
            if sample.get("engine") != CANONICAL_PROFILE_ENGINE:
                raise ProfileArtifactError(f"profile sample {sample_id!r} has a mixed engine")
            bucket = sample.get("solc")
            if bucket not in CANONICAL_PROFILING_COMPILERS:
                raise ProfileArtifactError(f"profile sample {sample_id!r} has an invalid compiler bucket")
            expected_compiler = CANONICAL_PROFILING_COMPILERS[bucket]
            if sample.get("profiling_compiler") != expected_compiler:
                raise ProfileArtifactError(f"profile sample {sample_id!r} has a mixed compiler")
            compiler_usage[expected_compiler] += 1
            if not _nonnegative_int(sample.get("n_func")):
                raise ProfileArtifactError(f"profile sample {sample_id!r} has invalid function metadata")
            for dimension in NUM_DIMS:
                observed[dimension].append(
                    _finite_number(
                        sample.get(dimension),
                        label=f"{sample_id}.{dimension}",
                        nonnegative=True,
                    )
                )
            total_samples += 1

    expected_sample_counts = {
        "attempted": sum(item["attempted"] for item in coverage.values()),
        "succeeded": total_samples,
        "skipped": sum(item["skipped"] for item in coverage.values()),
    }
    sample_counts = meta.get("sample_counts")
    if (
        not isinstance(sample_counts, dict)
        or set(sample_counts) != set(expected_sample_counts)
        or not all(_nonnegative_int(value) for value in sample_counts.values())
        or sample_counts != expected_sample_counts
    ):
        raise ProfileArtifactError("profile artifact global counts are inconsistent")
    if meta.get("compiler_usage") != dict(sorted(compiler_usage.items())):
        raise ProfileArtifactError("profile artifact compiler usage is stale")
    if coverage_source_digest(coverage) != meta["source_digest"]:
        raise ProfileArtifactError("profile artifact source digest is stale")
    for dimension in NUM_DIMS:
        bounds = ranges.get(dimension)
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise ProfileArtifactError(f"profile range {dimension!r} is malformed")
        low = _finite_number(bounds[0], label=f"_ranges.{dimension}[0]", nonnegative=True)
        high = _finite_number(bounds[1], label=f"_ranges.{dimension}[1]", nonnegative=True)
        if low > high or [low, high] != [min(observed[dimension]), max(observed[dimension])]:
            raise ProfileArtifactError(f"profile range {dimension!r} is stale")
    if profiles_digest(datasets) != meta["profiles_digest"]:
        raise ProfileArtifactError("profile artifact sample digest is stale")
    expected_fit_digest = bandwidth_fit_digest(
        profiles_digest=meta["profiles_digest"],
        ranges=ranges,
        bandwidth=bandwidth,
        provenance=bandwidth_meta,
    )
    if bandwidth_meta["fit_digest"] != expected_fit_digest:
        raise ProfileArtifactError("profile artifact bandwidth fit is stale")
    return meta, datasets


def load_profiles(path: str | Path) -> ProfileKB:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProfileArtifactError(f"unable to read profile artifact: {exc}") from exc
    _meta, datasets = _validate_artifact(d)
    rlog = _rlog(d["_ranges"])
    contracts = []
    for ds, samples in datasets.items():
        for s in samples:
            contracts.append({"ds": ds, "solc": s["solc"], "g": normalize(s, rlog)})
    bandwidth = d["_bandwidth"]
    return ProfileKB(rlog=rlog, contracts=contracts, bandwidth=bandwidth,
                     dataset_names=list(datasets))


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
