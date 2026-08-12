"""Resolve one consistent static recommendation-knowledge snapshot."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path

from toolrank.dataset_kb import load_performance_db
from toolrank.passage_store import (
    load_passage_store,
    passage_store_sha256,
    validate_passage_index_binding,
)
from toolrank.scene_kde import load_profiles
from toolrank.vector_store import VectorIndex


PRIVATE_TOOLCARDS_DIRNAME = ".private"
PRIVATE_SNAPSHOT_WARNING = (
    "local-private knowledge snapshot active; using the ignored developer-only "
    "Performance/Profile/RAG knowledge"
)


@dataclass(frozen=True)
class StaticToolcardSnapshot:
    performance_db_path: Path
    contract_profiles_path: Path
    passage_store_path: Path
    vector_index_path: Path
    private_active: bool


def _read_object(path: Path, *, label: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"invalid {label}: root must be an object")
    return payload


def _performance_entries(payload: dict, *, label: str) -> dict[str, dict]:
    rows = payload.get("entries")
    if not isinstance(rows, list):
        raise ValueError(f"invalid {label}: entries must be a list")
    entries: dict[str, dict] = {}
    for row in rows:
        source_id = row.get("source_id") if isinstance(row, dict) else None
        if not isinstance(source_id, str) or not source_id or source_id in entries:
            raise ValueError(f"invalid {label}: source identities must be unique")
        entries[source_id] = row
    return entries


def _entry_dataset_name(entry: dict, *, label: str) -> str:
    profile = entry.get("dataset_profile")
    dataset_name = profile.get("dataset_name") if isinstance(profile, dict) else None
    if not isinstance(dataset_name, str) or not dataset_name:
        raise ValueError(f"invalid {label}: dataset identity is missing")
    return dataset_name


def _passage_rows(payload: dict, *, label: str) -> list[dict]:
    rows = payload.get("passages")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"invalid {label}: passages must be a list of objects")
    return rows


def _index_passage_ids(index: VectorIndex, *, label: str) -> list[str]:
    passage_ids = index.metadata.get("passage_ids")
    if (
        not isinstance(passage_ids, list)
        or any(
            not isinstance(passage_id, str) or not passage_id
            for passage_id in passage_ids
        )
        or len(passage_ids) != len(set(passage_ids))
    ):
        raise ValueError(
            f"invalid {label}: metadata.passage_ids must contain unique strings"
        )
    return passage_ids


def _embedding_matrix(
    payload: dict,
    index: VectorIndex,
    *,
    label: str,
) -> tuple[list[list[int | float]], int]:
    embeddings = payload.get("embeddings")
    if not isinstance(embeddings, list) or not embeddings:
        raise ValueError(f"invalid {label}: embeddings must be a non-empty list")
    if len(embeddings) != len(index):
        raise ValueError(f"invalid {label}: loaded vector count does not match payload")

    dimensions: set[int] = set()
    for embedding in embeddings:
        if not isinstance(embedding, list) or not embedding:
            raise ValueError(
                f"invalid {label}: every embedding must be a non-empty list"
            )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in embedding
        ):
            raise ValueError(
                f"invalid {label}: embedding values must be finite numbers"
            )
        dimensions.add(len(embedding))
    if len(dimensions) != 1:
        raise ValueError(f"invalid {label}: inconsistent embedding dimensions")
    dimension = next(iter(dimensions))
    metadata_dimension = index.metadata.get("embedding_dim")
    if (
        isinstance(metadata_dimension, bool)
        or not isinstance(metadata_dimension, int)
        or metadata_dimension != dimension
    ):
        raise ValueError(
            f"invalid {label}: metadata embedding dimension does not match vectors"
        )
    return embeddings, dimension


def _validate_private_rag_snapshot(
    *,
    public_passages: Path,
    public_index_path: Path,
    private_passages: Path,
    private_index_path: Path,
) -> None:
    public_store = load_passage_store(public_passages)
    private_store = load_passage_store(private_passages)
    if public_store is None or private_store is None:
        raise ValueError("PassageStore files must exist")

    public_index = VectorIndex.load(public_index_path)
    private_index = VectorIndex.load(private_index_path)
    validate_passage_index_binding(public_store, public_index)
    validate_passage_index_binding(private_store, private_index)

    public_payload = _read_object(public_passages, label="public PassageStore")
    private_payload = _read_object(private_passages, label="private PassageStore")
    public_rows = _passage_rows(public_payload, label="public PassageStore")
    private_rows = _passage_rows(private_payload, label="private PassageStore")
    if (
        len(private_rows) <= len(public_rows)
        or private_rows[: len(public_rows)] != public_rows
    ):
        raise ValueError(
            "private PassageStore must exactly extend the current public PassageStore"
        )

    private_only_passages = private_store.passages[len(public_store.passages) :]
    if any(
        passage.linked_evaluation_ids != []
        or passage.linked_performance_observation_ids
        or passage.performance_observation_refs
        for passage in private_only_passages
    ):
        raise ValueError(
            "private-only passages must be explicitly qualitative with no "
            "evaluation or performance-observation links"
        )

    public_index_payload = _read_object(
        public_index_path,
        label="public vector index",
    )
    private_index_payload = _read_object(
        private_index_path,
        label="private vector index",
    )
    public_embeddings, public_dimension = _embedding_matrix(
        public_index_payload,
        public_index,
        label="public vector index",
    )
    private_embeddings, private_dimension = _embedding_matrix(
        private_index_payload,
        private_index,
        label="private vector index",
    )
    if private_dimension != public_dimension:
        raise ValueError(
            "private vector index embedding dimension must match the public index"
        )

    public_ids = _index_passage_ids(public_index, label="public vector index")
    private_ids = _index_passage_ids(private_index, label="private vector index")
    public_store_ids = [passage.passage_id for passage in public_store.passages]
    private_store_ids = [passage.passage_id for passage in private_store.passages]
    if public_ids != public_store_ids or private_ids != private_store_ids:
        raise ValueError("vector index passage IDs do not match PassageStore order")
    if private_ids[: len(public_ids)] != public_ids:
        raise ValueError(
            "private vector index must exactly retain the public passage-ID prefix"
        )
    if private_embeddings[: len(public_embeddings)] != public_embeddings:
        raise ValueError(
            "private vector index must exactly retain the public embedding prefix"
        )
    if private_ids[len(public_ids) :] != [
        passage.passage_id for passage in private_only_passages
    ]:
        raise ValueError(
            "private-only passage IDs do not match private-only vector IDs"
        )

    for metadata_key in ("provider", "model"):
        public_value = public_index.metadata.get(metadata_key)
        private_value = private_index.metadata.get(metadata_key)
        if (
            not isinstance(public_value, str)
            or not public_value.strip()
            or private_value != public_value
        ):
            raise ValueError(
                f"private vector index {metadata_key} must match the public index"
            )
    validate_passage_index_binding(
        private_store,
        private_index,
        expected_store_sha256=passage_store_sha256(private_store),
    )


def _validate_private_snapshot(
    *,
    public_performance: Path,
    public_profiles: Path,
    public_passages: Path,
    public_index: Path,
    private_performance: Path,
    private_profiles: Path,
    private_passages: Path,
    private_index: Path,
) -> None:
    """Prove that all private artifacts form one current public extension."""
    try:
        load_performance_db(public_performance)
        load_performance_db(private_performance)
        load_profiles(public_profiles)
        load_profiles(private_profiles)
        _validate_private_rag_snapshot(
            public_passages=public_passages,
            public_index_path=public_index,
            private_passages=private_passages,
            private_index_path=private_index,
        )
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        RuntimeError,
        ValueError,
    ) as exc:
        raise ValueError(f"invalid local-private toolcards snapshot: {exc}") from exc

    public_kb = _read_object(public_performance, label="public Performance KB")
    private_kb = _read_object(private_performance, label="private Performance KB")
    public_entries = _performance_entries(
        public_kb,
        label="public Performance KB",
    )
    private_entries = _performance_entries(
        private_kb,
        label="private Performance KB",
    )
    public_non_entries = {
        key: value for key, value in public_kb.items() if key != "entries"
    }
    private_non_entries = {
        key: value for key, value in private_kb.items() if key != "entries"
    }
    if (
        public_non_entries != private_non_entries
        or not set(public_entries) < set(private_entries)
        or any(
            private_entries[source_id] != entry
            for source_id, entry in public_entries.items()
        )
    ):
        raise ValueError(
            "invalid local-private toolcards snapshot: private Performance KB "
            "must exactly extend the current public KB"
        )

    private_entry_ids = set(private_entries) - set(public_entries)
    private_dataset_names = [
        _entry_dataset_name(
            private_entries[source_id],
            label="private Performance KB",
        )
        for source_id in private_entry_ids
    ]
    if len(set(private_dataset_names)) != len(private_dataset_names):
        raise ValueError(
            "invalid local-private toolcards snapshot: private Performance "
            "dataset identities must be unique"
        )

    public_profile = _read_object(public_profiles, label="public profile artifact")
    private_profile = _read_object(
        private_profiles,
        label="private profile artifact",
    )
    public_datasets = public_profile.get("datasets")
    private_datasets = private_profile.get("datasets")
    public_coverage = public_profile.get("_coverage")
    private_coverage = private_profile.get("_coverage")
    public_counts = public_profile.get("_counts")
    private_counts = private_profile.get("_counts")
    if not all(
        isinstance(value, dict)
        for value in (
            public_datasets,
            private_datasets,
            public_coverage,
            private_coverage,
            public_counts,
            private_counts,
        )
    ):
        raise ValueError(
            "invalid local-private toolcards snapshot: profile dataset metadata "
            "must be objects"
        )
    if (
        not set(public_datasets) < set(private_datasets)
        or any(
            private_datasets[name] != samples
            or private_coverage.get(name) != public_coverage.get(name)
            or private_counts.get(name) != public_counts.get(name)
            for name, samples in public_datasets.items()
        )
    ):
        raise ValueError(
            "invalid local-private toolcards snapshot: private profile artifact "
            "must exactly extend the current public profile datasets"
        )

    profile_delta = set(private_datasets) - set(public_datasets)
    if profile_delta != set(private_dataset_names):
        raise ValueError(
            "invalid local-private toolcards snapshot: private Performance and "
            "profile dataset identities do not match"
        )


def resolve_static_toolcard_snapshot(
    toolcards_dir: str | Path,
) -> StaticToolcardSnapshot:
    """Select public knowledge or one complete ignored local-private snapshot."""
    root = Path(toolcards_dir)
    public_performance = root / "performance_db.json"
    public_profiles = root / "contract_profiles.json"
    public_passages = root / "passage_store.json"
    public_index = root / "vector_index" / "index.json"
    private_root = root / PRIVATE_TOOLCARDS_DIRNAME
    private_performance = private_root / "performance_db.json"
    private_profiles = private_root / "contract_profiles.json"
    private_passages = private_root / "passage_store.json"
    private_index = private_root / "vector_index" / "index.json"

    private_paths = (
        private_performance,
        private_profiles,
        private_passages,
        private_index,
    )
    present = [
        path for path in private_paths if path.exists() or path.is_symlink()
    ]
    missing = [
        path for path in private_paths if not (path.exists() or path.is_symlink())
    ]
    if present and missing:
        raise ValueError(
            "incomplete local-private toolcards snapshot: "
            f"found {', '.join(str(path) for path in present)}, but "
            f"{', '.join(str(path) for path in missing)} is missing"
        )
    if present:
        if any(path.is_symlink() or not path.is_file() for path in private_paths):
            raise ValueError(
                "invalid local-private toolcards snapshot: all snapshot paths "
                "must be regular files"
            )
        _validate_private_snapshot(
            public_performance=public_performance,
            public_profiles=public_profiles,
            public_passages=public_passages,
            public_index=public_index,
            private_performance=private_performance,
            private_profiles=private_profiles,
            private_passages=private_passages,
            private_index=private_index,
        )
        return StaticToolcardSnapshot(
            performance_db_path=private_performance,
            contract_profiles_path=private_profiles,
            passage_store_path=private_passages,
            vector_index_path=private_index,
            private_active=True,
        )
    return StaticToolcardSnapshot(
        performance_db_path=public_performance,
        contract_profiles_path=public_profiles,
        passage_store_path=public_passages,
        vector_index_path=public_index,
        private_active=False,
    )
