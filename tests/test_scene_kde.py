from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from toolrank import _complexity, scene_kde


def _artifact() -> dict:
    samples = [
        {
            "id": f"Dataset::{name}.sol",
            "path": f"{name}.sol",
            "engine": _complexity.CANONICAL_PROFILE_ENGINE,
            "solc": "0.8.x",
            "profiling_compiler": "0.8.30",
            "loc": value,
            "avg_cyc": float(value),
            "max_cyc": value,
            "sum_cyc": value,
            "max_nest": value,
            "coupling": value,
            "n_func": value,
        }
        for name, value in (("A", 1), ("B", 2))
    ]
    datasets = {"Dataset": samples}
    coverage = {
        "Dataset": {
            "root": "dataset",
            "attempted": 2,
            "succeeded": 2,
            "skipped": 0,
            "failure_classes": {},
            "skipped_samples": [],
            "unsafe_paths_excluded": 0,
            "source_digest": "c" * 64,
            "corpus_digest": "d" * 64,
        }
    }
    ranges = {dimension: [1, 2] for dimension in _complexity.NUM_DIMS}
    profiles_digest = scene_kde.profiles_digest(datasets)
    bandwidth = 0.08
    bandwidth_meta = {
        "method": scene_kde.BANDWIDTH_METHOD,
        "seed": scene_kde.BANDWIDTH_SEED,
        "sample_size": scene_kde.BANDWIDTH_SAMPLE_SIZE,
        "grid": list(scene_kde.BANDWIDTH_GRID),
    }
    bandwidth_meta["fit_digest"] = scene_kde.bandwidth_fit_digest(
        profiles_digest=profiles_digest,
        ranges=ranges,
        bandwidth=bandwidth,
        provenance=bandwidth_meta,
    )
    return {
        "_meta": {
            "schema_version": _complexity.PROFILE_ARTIFACT_SCHEMA,
            "engine": _complexity.CANONICAL_PROFILE_ENGINE,
            "generated_at": "2026-07-17T00:00:00Z",
            "sample_unit": _complexity.PROFILE_SAMPLE_UNIT,
            "dimensions": ["solc", *_complexity.NUM_DIMS],
            "range_dimensions": list(_complexity.NUM_DIMS),
            "canonical_compilers": dict(_complexity.CANONICAL_PROFILING_COMPILERS),
            "compiler_selection": {
                "constrained_bucket_order": list(
                    _complexity.CANONICAL_PROFILING_BUCKET_ORDER
                ),
                "no_pragma_bucket_order": list(
                    _complexity.NO_PRAGMA_PROFILING_BUCKET_ORDER
                ),
            },
            "normalizations": list(_complexity.PROFILE_NORMALIZATIONS),
            "failure_classes": list(_complexity.PROFILE_FAILURE_CLASSES),
            "manifest_version": _complexity.PROFILE_MANIFEST_SCHEMA,
            "manifest_digest": "a" * 64,
            "source_digest": scene_kde.coverage_source_digest(coverage),
            "profiles_digest": profiles_digest,
            "dataset_names": ["Dataset"],
            "excluded_datasets": [],
            "compiler_usage": {"0.8.30": 2},
            "sample_counts": {"attempted": 2, "succeeded": 2, "skipped": 0},
            "bandwidth": bandwidth_meta,
        },
        "_counts": {"Dataset": 2},
        "_coverage": coverage,
        "_ranges": ranges,
        "_bandwidth": bandwidth,
        "datasets": datasets,
    }


def _write(tmp_path: Path, artifact: dict) -> Path:
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return path


def test_strict_loader_accepts_canonical_artifact_without_runtime_refit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        scene_kde,
        "fit_bandwidth",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("runtime must not refit bandwidth")
        ),
    )

    loaded = scene_kde.load_profiles(_write(tmp_path, _artifact()))

    assert loaded.dataset_names == ["Dataset"]
    assert loaded.bandwidth == 0.08
    assert len(loaded.contracts) == 2


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["_meta"].__setitem__("engine", "source_scanner_v1"),
        lambda value: value["_meta"].__setitem__("schema_version", "legacy"),
        lambda value: value["_meta"].__setitem__("dimensions", ["solc", "loc"]),
        lambda value: value["_meta"].pop("compiler_selection"),
        lambda value: value["_meta"]["compiler_selection"].__setitem__(
            "no_pragma_bucket_order", list(_complexity.CANONICAL_PROFILING_BUCKET_ORDER)
        ),
        lambda value: value.__setitem__("_bandwidth", None),
        lambda value: value.__setitem__("_bandwidth", 0.0),
        lambda value: value.__setitem__("_bandwidth", 0.12),
        lambda value: value["_meta"].__setitem__("manifest_digest", "z" * 64),
        lambda value: value["_meta"].__setitem__("source_digest", "f" * 64),
        lambda value: value["_coverage"]["Dataset"].__setitem__("root", "../dataset"),
        lambda value: value["_coverage"]["Dataset"].__setitem__(
            "source_digest", "not-a-sha256"
        ),
        lambda value: value["_counts"].__setitem__("Dataset", True),
        lambda value: value["datasets"]["Dataset"][0].__setitem__(
            "path", "renamed.sol"
        ),
        lambda value: value["datasets"]["Dataset"].__setitem__(slice(None), []),
        lambda value: value["datasets"]["Dataset"][1].__setitem__(
            "id", value["datasets"]["Dataset"][0]["id"]
        ),
        lambda value: value["datasets"]["Dataset"][0].__setitem__(
            "engine", "other_ast_engine"
        ),
        lambda value: value["datasets"]["Dataset"][0].__setitem__(
            "profiling_compiler", "0.8.20"
        ),
        lambda value: value["_ranges"].__setitem__("loc", [0, 2]),
        lambda value: value["datasets"]["Dataset"][0].__setitem__("loc", float("nan")),
    ],
)
def test_strict_loader_rejects_legacy_mixed_malformed_or_stale_artifacts(
    tmp_path: Path,
    mutate,
) -> None:
    artifact = deepcopy(_artifact())
    mutate(artifact)

    with pytest.raises(scene_kde.ProfileArtifactError):
        scene_kde.load_profiles(_write(tmp_path, artifact))
