"""Build the canonical AST benchmark-profile artifact.

Dataset paths come from a tracked manifest and are resolved beneath an
explicit corpus root.  One sample is attempted per safe Solidity file and is
compiled together with its safe in-corpus import closure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from toolrank import scene_kde
from toolrank._complexity import (
    AstExtractionError,
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
    profile_sources,
)
from toolrank.source_project import dependency_closure


MANIFEST_SCHEMA = PROFILE_MANIFEST_SCHEMA
_VCS_DIRECTORIES = {".git", ".svn"}
_FAILURE_CLASSES = set(PROFILE_FAILURE_CLASSES)


class ProfileBuildError(RuntimeError):
    """Raised when a complete auditable profile artifact cannot be built."""


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    relative_path: str
    include: bool
    reason: str | None = None
    duplicate_of: str | None = None


@dataclass(frozen=True)
class LoadedManifest:
    version: str
    digest: str
    datasets: tuple[DatasetSpec, ...]


@dataclass(frozen=True)
class DatasetInventory:
    spec: DatasetSpec
    root: Path
    files: tuple[Path, ...]
    unsafe_paths: int
    source_digest: str
    corpus_digest: str


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_manifest(path: str | Path) -> LoadedManifest:
    manifest_path = Path(path)
    try:
        raw_bytes = manifest_path.read_bytes()
        raw = json.loads(raw_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProfileBuildError(f"unable to read profile manifest: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != MANIFEST_SCHEMA:
        raise ProfileBuildError("profile manifest schema is incompatible")
    if raw.get("sample_unit") != PROFILE_SAMPLE_UNIT:
        raise ProfileBuildError("profile manifest sample unit is incompatible")
    rows = raw.get("datasets")
    if not isinstance(rows, list) or not rows:
        raise ProfileBuildError("profile manifest must declare datasets")

    specs: list[DatasetSpec] = []
    names: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ProfileBuildError("profile manifest dataset rows must be objects")
        name = row.get("name")
        relative_path = row.get("path")
        include = row.get("include")
        if (
            not isinstance(name, str)
            or not name
            or name in names
            or not isinstance(relative_path, str)
            or not relative_path
            or not isinstance(include, bool)
        ):
            raise ProfileBuildError("profile manifest contains an invalid dataset row")
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ProfileBuildError(f"dataset path for {name!r} must stay below the corpus root")
        reason = row.get("reason")
        duplicate_of = row.get("duplicate_of")
        if not include and (not isinstance(reason, str) or not reason):
            raise ProfileBuildError(f"excluded dataset {name!r} needs a reason")
        if duplicate_of is not None and (not isinstance(duplicate_of, str) or not duplicate_of):
            raise ProfileBuildError(f"dataset {name!r} has an invalid duplicate target")
        names.add(name)
        specs.append(
            DatasetSpec(
                name=name,
                relative_path=relative_path,
                include=include,
                reason=reason,
                duplicate_of=duplicate_of,
            )
        )
    included_names = {spec.name for spec in specs if spec.include}
    for spec in specs:
        if spec.duplicate_of is not None and spec.duplicate_of not in included_names:
            raise ProfileBuildError(
                f"excluded duplicate {spec.name!r} names an unknown canonical dataset"
            )
    return LoadedManifest(
        version=MANIFEST_SCHEMA,
        digest=_sha256_bytes(raw_bytes),
        datasets=tuple(specs),
    )


def _resolve_dataset_root(corpus_root: Path, spec: DatasetSpec) -> Path:
    root = corpus_root.resolve()
    candidate = (root / spec.relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ProfileBuildError(f"dataset root for {spec.name!r} escapes the corpus root") from exc
    return candidate


def discover_solidity_files(root: Path) -> tuple[tuple[Path, ...], int]:
    files: list[Path] = []
    unsafe_paths = 0
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        base = Path(directory)
        safe_directories: list[str] = []
        for name in sorted(directory_names):
            candidate = base / name
            if name in _VCS_DIRECTORIES or candidate.is_symlink():
                if candidate.is_symlink():
                    unsafe_paths += 1
                continue
            safe_directories.append(name)
        directory_names[:] = safe_directories
        for name in sorted(file_names):
            if not name.lower().endswith(".sol"):
                continue
            candidate = base / name
            if candidate.is_symlink():
                unsafe_paths += 1
                continue
            try:
                candidate.resolve(strict=True).relative_to(root.resolve())
            except (OSError, ValueError):
                unsafe_paths += 1
                continue
            if candidate.is_file():
                files.append(candidate)
    return tuple(sorted(files, key=lambda item: item.relative_to(root).as_posix())), unsafe_paths


def _inventory(spec: DatasetSpec, corpus_root: Path) -> DatasetInventory:
    root = _resolve_dataset_root(corpus_root, spec)
    if not root.is_dir():
        raise ProfileBuildError(f"required dataset root is missing: {spec.name!r} -> {spec.relative_path}")
    files, unsafe_paths = discover_solidity_files(root)
    if not files:
        raise ProfileBuildError(f"required dataset {spec.name!r} has no safe Solidity samples")

    source_hasher = hashlib.sha256()
    content_digests: list[str] = []
    for source in files:
        relative = source.relative_to(root).as_posix()
        try:
            content = source.read_bytes()
        except OSError as exc:
            raise ProfileBuildError(f"unable to inventory {source}: {exc}") from exc
        digest = _sha256_bytes(content)
        content_digests.append(digest)
        source_hasher.update(relative.encode("utf-8"))
        source_hasher.update(b"\0")
        source_hasher.update(content)
        source_hasher.update(b"\0")
    corpus_digest = _sha256_bytes("\n".join(sorted(content_digests)).encode("ascii"))
    return DatasetInventory(
        spec=spec,
        root=root,
        files=files,
        unsafe_paths=unsafe_paths,
        source_digest=source_hasher.hexdigest(),
        corpus_digest=corpus_digest,
    )


def _validate_inventories(
    manifest: LoadedManifest,
    corpus_root: Path,
) -> tuple[DatasetInventory, ...]:
    inventories = tuple(
        _inventory(spec, corpus_root) for spec in manifest.datasets if spec.include
    )
    by_name = {inventory.spec.name: inventory for inventory in inventories}
    roots: dict[Path, str] = {}
    corpora: dict[str, str] = {}
    for inventory in inventories:
        resolved = inventory.root.resolve()
        if resolved in roots:
            raise ProfileBuildError(
                f"undeclared duplicate dataset root: {roots[resolved]!r} and {inventory.spec.name!r}"
            )
        if inventory.corpus_digest in corpora:
            raise ProfileBuildError(
                f"undeclared duplicate corpus: {corpora[inventory.corpus_digest]!r} and {inventory.spec.name!r}"
            )
        roots[resolved] = inventory.spec.name
        corpora[inventory.corpus_digest] = inventory.spec.name

    for spec in manifest.datasets:
        if spec.duplicate_of is None:
            continue
        alias_root = _resolve_dataset_root(corpus_root, spec)
        canonical = by_name[spec.duplicate_of]
        if alias_root.resolve() == canonical.root.resolve():
            continue
        if not alias_root.is_dir():
            raise ProfileBuildError(f"declared duplicate root is missing: {spec.name!r}")
        alias_inventory = _inventory(spec, corpus_root)
        if alias_inventory.corpus_digest != canonical.corpus_digest:
            raise ProfileBuildError(
                f"declared duplicate {spec.name!r} does not match {spec.duplicate_of!r}"
            )
    return inventories


def _sample_sources(sample: Path, dataset_root: Path) -> dict[str, str]:
    closure = dependency_closure(sample, dataset_root)
    if not closure or sample.resolve() not in closure:
        raise ValueError("sample is outside its safe import closure")
    return {
        source.relative_to(dataset_root).as_posix(): source.read_text(encoding="utf-8")
        for source in closure
    }


def profile_file(path: str | Path, *, dataset_root: str | Path | None = None) -> dict:
    """Profile one file with its safe import closure for parity tests and tools."""
    sample = Path(path).resolve()
    root = Path(dataset_root).resolve() if dataset_root is not None else sample.parent
    return profile_sources(_sample_sources(sample, root))


def _failure_class(exc: Exception) -> str:
    if isinstance(exc, UnicodeError):
        return "source_encoding"
    if isinstance(exc, OSError):
        return "source_io"
    if isinstance(exc, ValueError):
        return "unsafe_import_closure"
    message = str(exc).lower()
    if "no supported intersection" in message:
        return "pragma_constraint"
    if "source" in message and ("not found" in message or "import" in message):
        return "unresolved_import"
    return "compilation_error"


def _is_environment_failure(exc: AstExtractionError) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "py-solc-x is unavailable",
            "no solc versions are installed",
            "canonical profiling compiler",
        )
    )


def _ranges(datasets: dict[str, list[dict]]) -> dict[str, list[float | int]]:
    return {
        dimension: [
            min(sample[dimension] for samples in datasets.values() for sample in samples),
            max(sample[dimension] for samples in datasets.values() for sample in samples),
        ]
        for dimension in NUM_DIMS
    }


def build_artifact(
    *,
    corpus_root: str | Path,
    manifest_path: str | Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    corpus = Path(corpus_root)
    if not corpus.is_dir():
        raise ProfileBuildError(f"corpus root is missing: {corpus}")
    manifest = load_manifest(manifest_path)
    inventories = _validate_inventories(manifest, corpus)

    datasets: dict[str, list[dict]] = {}
    coverage: dict[str, dict[str, Any]] = {}
    sample_ids: set[str] = set()
    compiler_usage: Counter[str] = Counter()
    for inventory in inventories:
        samples: list[dict] = []
        failures: Counter[str] = Counter()
        skipped_samples: list[dict[str, str]] = []
        for source in inventory.files:
            relative = source.relative_to(inventory.root).as_posix()
            sample_id = f"{inventory.spec.name}::{relative}"
            if sample_id in sample_ids:
                raise ProfileBuildError(f"duplicate profile sample ID: {sample_id}")
            sample_ids.add(sample_id)
            try:
                profile = profile_file(source, dataset_root=inventory.root)
            except AstExtractionError as exc:
                if _is_environment_failure(exc):
                    raise ProfileBuildError(str(exc)) from exc
                failure_class = _failure_class(exc)
                failures[failure_class] += 1
                skipped_samples.append(
                    {"id": sample_id, "failure_class": failure_class}
                )
                continue
            except (UnicodeError, OSError, ValueError) as exc:
                failure_class = _failure_class(exc)
                failures[failure_class] += 1
                skipped_samples.append(
                    {"id": sample_id, "failure_class": failure_class}
                )
                continue
            if any(
                not isinstance(profile.get(dimension), (int, float))
                or isinstance(profile.get(dimension), bool)
                or not math.isfinite(float(profile[dimension]))
                or float(profile[dimension]) < 0
                for dimension in NUM_DIMS
            ):
                raise ProfileBuildError(f"canonical extractor returned an invalid profile for {sample_id}")
            compiler = str(profile["profiling_compiler"])
            compiler_usage[compiler] += 1
            samples.append(
                {
                    "id": sample_id,
                    "path": relative,
                    "engine": CANONICAL_PROFILE_ENGINE,
                    **profile,
                }
            )
        attempted = len(inventory.files)
        skipped = sum(failures.values())
        if attempted != len(samples) + skipped:
            raise ProfileBuildError(f"silent sample loss detected in {inventory.spec.name!r}")
        if not samples:
            raise ProfileBuildError(f"required dataset {inventory.spec.name!r} emitted no profiles")
        if not set(failures).issubset(_FAILURE_CLASSES):
            raise ProfileBuildError(f"unbounded failure class in {inventory.spec.name!r}")
        datasets[inventory.spec.name] = samples
        coverage[inventory.spec.name] = {
            "root": inventory.spec.relative_path,
            "attempted": attempted,
            "succeeded": len(samples),
            "skipped": skipped,
            "failure_classes": dict(sorted(failures.items())),
            "skipped_samples": skipped_samples,
            "unsafe_paths_excluded": inventory.unsafe_paths,
            "source_digest": inventory.source_digest,
            "corpus_digest": inventory.corpus_digest,
        }

    ranges = _ranges(datasets)
    range_log = scene_kde._rlog(ranges)
    normalized = [
        {"solc": sample["solc"], "g": scene_kde.normalize(sample, range_log)}
        for samples in datasets.values()
        for sample in samples
    ]
    bandwidth = scene_kde.fit_bandwidth(
        normalized,
        sample_size=scene_kde.BANDWIDTH_SAMPLE_SIZE,
        seed=scene_kde.BANDWIDTH_SEED,
        grid=scene_kde.BANDWIDTH_GRID,
    )
    global_source_digest = scene_kde.coverage_source_digest(coverage)
    profile_digest = scene_kde.profiles_digest(datasets)
    bandwidth_meta = {
        "method": scene_kde.BANDWIDTH_METHOD,
        "seed": scene_kde.BANDWIDTH_SEED,
        "sample_size": scene_kde.BANDWIDTH_SAMPLE_SIZE,
        "grid": list(scene_kde.BANDWIDTH_GRID),
    }
    bandwidth_meta["fit_digest"] = scene_kde.bandwidth_fit_digest(
        profiles_digest=profile_digest,
        ranges=ranges,
        bandwidth=bandwidth,
        provenance=bandwidth_meta,
    )
    counts = {name: len(samples) for name, samples in datasets.items()}
    sample_counts = {
        "attempted": sum(item["attempted"] for item in coverage.values()),
        "succeeded": sum(counts.values()),
        "skipped": sum(item["skipped"] for item in coverage.values()),
    }
    excluded = [
        {
            "name": spec.name,
            "path": spec.relative_path,
            "reason": spec.reason,
            **({"duplicate_of": spec.duplicate_of} if spec.duplicate_of else {}),
        }
        for spec in manifest.datasets
        if not spec.include
    ]
    timestamp = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "_meta": {
            "schema_version": PROFILE_ARTIFACT_SCHEMA,
            "engine": CANONICAL_PROFILE_ENGINE,
            "generated_at": timestamp,
            "sample_unit": PROFILE_SAMPLE_UNIT,
            "dimensions": ["solc", *NUM_DIMS],
            "range_dimensions": list(NUM_DIMS),
            "canonical_compilers": dict(CANONICAL_PROFILING_COMPILERS),
            "compiler_selection": {
                "constrained_bucket_order": list(CANONICAL_PROFILING_BUCKET_ORDER),
                "no_pragma_bucket_order": list(NO_PRAGMA_PROFILING_BUCKET_ORDER),
            },
            "normalizations": list(PROFILE_NORMALIZATIONS),
            "failure_classes": list(PROFILE_FAILURE_CLASSES),
            "compiler_usage": dict(sorted(compiler_usage.items())),
            "manifest_version": manifest.version,
            "manifest_digest": manifest.digest,
            "source_digest": global_source_digest,
            "profiles_digest": profile_digest,
            "dataset_names": list(datasets),
            "excluded_datasets": excluded,
            "sample_counts": sample_counts,
            "bandwidth": bandwidth_meta,
        },
        "_counts": counts,
        "_coverage": coverage,
        "_ranges": ranges,
        "_bandwidth": bandwidth,
        "datasets": datasets,
    }


def write_artifact_atomic(payload: dict[str, Any], output: str | Path) -> None:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def build_and_write(
    *,
    corpus_root: str | Path,
    manifest_path: str | Path,
    output: str | Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    payload = build_artifact(
        corpus_root=corpus_root,
        manifest_path=manifest_path,
        generated_at=generated_at,
    )
    write_artifact_atomic(payload, output)
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lakes-profile-builder",
        description="Build the canonical LAKES AST benchmark-profile artifact.",
    )
    parser.add_argument("--corpus-root", required=True, type=Path)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("toolcards/contract_profile_manifest.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("toolcards/contract_profiles.json"),
    )
    parser.add_argument("--generated-at", help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = build_and_write(
            corpus_root=args.corpus_root,
            manifest_path=args.manifest,
            output=args.output,
            generated_at=args.generated_at,
        )
    except ProfileBuildError as exc:
        _parser().exit(2, f"lakes-profile-builder: error: {exc}\n")
    summary = {
        "output": str(args.output),
        "counts": payload["_meta"]["sample_counts"],
        "ranges": payload["_ranges"],
        "bandwidth": payload["_bandwidth"],
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
