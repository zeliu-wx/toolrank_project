"""Immutable dynamic-KB generations and the single atomic visibility pointer."""

from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
from typing import Callable, Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field

from toolrank.dataset_kb import load_performance_db
from toolrank.kb_update_models import RejectRecord, canonical_json_bytes
from toolrank.passage_store import load_passage_store
from toolrank.schemas import PerformanceKnowledgeBase
from toolrank.schemas_v2 import PassageStore
from toolrank.vector_store import VECTOR_INDEX_SCHEMA_VERSION, VectorIndex


POINTER_FILE = "kb_current.json"
GENERATIONS_DIR = ".kb_generations"
TRANSACTIONS_DIR = ".kb_transactions"
REJECTS_DIR = "kb_rejects"
GENERATION_FILES = (
    "performance_db.json",
    "passage_store.json",
    "vector_index.json",
    "reject_log.json",
)


class GenerationValidationError(RuntimeError):
    pass


class GenerationCommitError(RuntimeError):
    pass


class RecoveryRequiredError(RuntimeError):
    pass


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GenerationFileRecord(_StrictModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)


class KbGenerationManifest(_StrictModel):
    schema_version: Literal["lakes_kb_generation.v1"] = "lakes_kb_generation.v1"
    generation_id: str = Field(pattern=r"^kbgen_[0-9a-f]{32}$")
    created_at: str
    files: dict[str, GenerationFileRecord]
    performance_entries: int = Field(ge=0)
    performance_observations: int = Field(ge=0)
    passages: int = Field(ge=0)
    rejected_candidates: int = Field(ge=0)
    stage1_ineligible_observations: int = Field(ge=0)


class KbPointer(_StrictModel):
    schema_version: Literal["lakes_kb_pointer.v1"] = "lakes_kb_pointer.v1"
    generation_id: str = Field(pattern=r"^kbgen_[0-9a-f]{32}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class LoadedKnowledgeGeneration:
    root: Path
    generation_dir: Path
    pointer: KbPointer
    pointer_bytes: bytes
    manifest: KbGenerationManifest
    performance_kb: PerformanceKnowledgeBase
    passage_store: PassageStore
    vector_index: VectorIndex
    rejects: tuple[RejectRecord, ...]


@dataclass(frozen=True)
class PublishResult:
    status: Literal["COMMITTED", "NOOP"]
    generation: LoadedKnowledgeGeneration


@dataclass(frozen=True)
class RecoveryResult:
    status: Literal["VALID", "RESTORED", "NO_POINTER"]
    generation_id: str | None = None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_bytes_fsync(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def atomic_replace_bytes(path: Path, data: bytes) -> None:
    """Atomically replace one file and clean its private temporary on failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def performance_bytes(kb: PerformanceKnowledgeBase) -> bytes:
    return canonical_json_bytes(kb.model_dump(mode="json", by_alias=True))


def passage_bytes(store: PassageStore) -> bytes:
    return canonical_json_bytes(store.model_dump(mode="json"))


def reject_bytes(rejects: list[RejectRecord]) -> bytes:
    ordered = sorted(
        rejects,
        key=lambda item: (
            item.channel,
            item.candidate_digest,
            item.reason_code.value,
            item.field_path,
        ),
    )
    return canonical_json_bytes(
        {
            "schema_version": "lakes_kb_reject_log.v1",
            "rejects": [item.model_dump(mode="json") for item in ordered],
        }
    )


def _file_record(data: bytes) -> GenerationFileRecord:
    return GenerationFileRecord(sha256=sha256_bytes(data), size_bytes=len(data))


def _read_json_bytes(path: Path) -> tuple[bytes, object]:
    try:
        raw = path.read_bytes()
        return raw, json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenerationValidationError(f"invalid JSON artifact {path.name}: {exc}") from exc


def _validate_vector_payload(
    path: Path,
    store: PassageStore,
    store_digest: str,
) -> VectorIndex:
    _raw, payload = _read_json_bytes(path)
    if not isinstance(payload, dict):
        raise GenerationValidationError("vector index must be a JSON object")
    if payload.get("schema_version") != VECTOR_INDEX_SCHEMA_VERSION:
        raise GenerationValidationError("vector index schema mismatch")
    metadata = payload.get("metadata")
    embeddings = payload.get("embeddings")
    if not isinstance(metadata, dict) or not isinstance(embeddings, list):
        raise GenerationValidationError("vector index metadata/embeddings are malformed")
    expected_ids = [passage.passage_id for passage in store.passages]
    if metadata.get("passage_ids") != expected_ids:
        raise GenerationValidationError("vector index passage IDs do not match the store")
    if metadata.get("passage_store_sha256") != store_digest:
        raise GenerationValidationError("vector index passage-store digest mismatch")
    if len(embeddings) != len(expected_ids):
        raise GenerationValidationError("vector index size does not match the passage store")
    dimensions: set[int] = set()
    for row in embeddings:
        if not isinstance(row, list):
            raise GenerationValidationError("vector embedding row must be a list")
        dimensions.add(len(row))
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in row
        ):
            raise GenerationValidationError("vector embedding contains a non-finite value")
    if len(dimensions) > 1:
        raise GenerationValidationError("vector embedding dimensions are inconsistent")
    return VectorIndex.load(path)


def _validate_cross_store_links(
    performance_kb: PerformanceKnowledgeBase,
    passage_store: PassageStore,
) -> None:
    observations = {}
    for entry in performance_kb.entries:
        for observation in entry.performance_observations:
            prior = observations.setdefault(observation.observation_id, observation)
            if prior != observation:
                raise GenerationValidationError(
                    f"conflicting performance observation ID: {observation.observation_id}"
                )
    for passage in passage_store.passages:
        for reference in passage.performance_observation_refs:
            observation = observations.get(reference.observation_id)
            if observation is None:
                raise GenerationValidationError(
                    f"passage link endpoint missing: {reference.observation_id}"
                )
            if observation.to_ref() != reference:
                raise GenerationValidationError(
                    f"passage link endpoint mismatch: {reference.observation_id}"
                )
            if (
                observation.paper_id != passage.paper_id
                or observation.tool != passage.owner_tool
                or observation.category != passage.category
            ):
                raise GenerationValidationError(
                    f"passage link violates paper/tool/category identity: {reference.observation_id}"
                )


def validate_generation_directory(
    generation_dir: Path,
    *,
    pointer: KbPointer | None = None,
    pointer_bytes: bytes = b"",
    root: Path | None = None,
) -> LoadedKnowledgeGeneration:
    manifest_raw, manifest_payload = _read_json_bytes(generation_dir / "manifest.json")
    try:
        manifest = KbGenerationManifest.model_validate(manifest_payload)
    except Exception as exc:
        raise GenerationValidationError(f"generation manifest is invalid: {exc}") from exc
    if (
        not generation_dir.name.startswith(".staging-")
        and generation_dir.name != manifest.generation_id
    ):
        raise GenerationValidationError("generation directory and manifest identity differ")
    if pointer is not None:
        if pointer.generation_id != manifest.generation_id:
            raise GenerationValidationError("pointer and manifest generation differ")
        if pointer.manifest_sha256 != sha256_bytes(manifest_raw):
            raise GenerationValidationError("pointer manifest digest mismatch")
    if set(manifest.files) != set(GENERATION_FILES):
        raise GenerationValidationError("generation manifest file set is incomplete")
    file_bytes: dict[str, bytes] = {}
    for name in GENERATION_FILES:
        try:
            data = (generation_dir / name).read_bytes()
        except OSError as exc:
            raise GenerationValidationError(f"generation file missing: {name}") from exc
        file_bytes[name] = data
        record = manifest.files[name]
        if len(data) != record.size_bytes or sha256_bytes(data) != record.sha256:
            raise GenerationValidationError(f"generation file digest mismatch: {name}")
    try:
        performance_kb = load_performance_db(generation_dir / "performance_db.json")
        passage_store = load_passage_store(generation_dir / "passage_store.json")
    except Exception as exc:
        raise GenerationValidationError(f"knowledge store validation failed: {exc}") from exc
    if passage_store is None:
        raise GenerationValidationError("passage store is missing")
    vector_index = _validate_vector_payload(
        generation_dir / "vector_index.json",
        passage_store,
        sha256_bytes(file_bytes["passage_store.json"]),
    )
    try:
        reject_payload = json.loads(file_bytes["reject_log.json"].decode("utf-8"))
        if reject_payload.get("schema_version") != "lakes_kb_reject_log.v1":
            raise ValueError("unsupported reject log schema")
        rejects = tuple(
            RejectRecord.model_validate(item) for item in reject_payload.get("rejects", [])
        )
    except Exception as exc:
        raise GenerationValidationError(f"reject log is invalid: {exc}") from exc
    _validate_cross_store_links(performance_kb, passage_store)
    if manifest.performance_entries != len(performance_kb.entries):
        raise GenerationValidationError("manifest performance-entry count mismatch")
    observation_count = sum(
        len(entry.performance_observations) for entry in performance_kb.entries
    )
    if manifest.performance_observations != observation_count:
        raise GenerationValidationError("manifest observation count mismatch")
    ineligible_count = sum(
        not observation.stage1_eligible
        for entry in performance_kb.entries
        for observation in entry.performance_observations
    )
    if manifest.stage1_ineligible_observations != ineligible_count:
        raise GenerationValidationError("manifest Stage 1 ineligible count mismatch")
    if manifest.passages != len(passage_store.passages):
        raise GenerationValidationError("manifest passage count mismatch")
    if manifest.rejected_candidates != len(rejects):
        raise GenerationValidationError("manifest reject count mismatch")
    effective_pointer = pointer or KbPointer(
        generation_id=manifest.generation_id,
        manifest_sha256=sha256_bytes(manifest_raw),
    )
    return LoadedKnowledgeGeneration(
        root=root or generation_dir.parent.parent,
        generation_dir=generation_dir,
        pointer=effective_pointer,
        pointer_bytes=pointer_bytes,
        manifest=manifest,
        performance_kb=performance_kb,
        passage_store=passage_store,
        vector_index=vector_index,
        rejects=rejects,
    )


def load_current_generation(kb_root: str | Path) -> LoadedKnowledgeGeneration:
    """Resolve ``kb_current.json`` once, then load every artifact beneath it."""
    root = Path(kb_root)
    pointer_path = root / POINTER_FILE
    try:
        pointer_bytes = pointer_path.read_bytes()
        pointer_payload = json.loads(pointer_bytes.decode("utf-8"))
        pointer = KbPointer.model_validate(pointer_payload)
    except Exception as exc:
        raise GenerationValidationError(f"current KB pointer is invalid: {exc}") from exc
    generation_dir = root / GENERATIONS_DIR / pointer.generation_id
    return validate_generation_directory(
        generation_dir,
        pointer=pointer,
        pointer_bytes=pointer_bytes,
        root=root,
    )


def validate_kb_root(kb_root: str | Path) -> KbGenerationManifest:
    return load_current_generation(kb_root).manifest


@contextmanager
def kb_writer_lock(kb_root: Path, run_id: str) -> Iterator[None]:
    lock_dir = kb_root / ".kb_writer.lock"
    kb_root.mkdir(parents=True, exist_ok=True)
    try:
        lock_dir.mkdir()
    except FileExistsError as exc:
        raise GenerationCommitError("another KB update writer holds the lock") from exc
    try:
        write_bytes_fsync(
            lock_dir / "owner.json",
            canonical_json_bytes({"run_id": run_id, "pid": os.getpid()}),
        )
        _fsync_directory(kb_root)
        yield
    finally:
        try:
            (lock_dir / "owner.json").unlink()
        except FileNotFoundError:
            pass
        try:
            lock_dir.rmdir()
        except FileNotFoundError:
            pass
        _fsync_directory(kb_root)


def _journal_bytes(
    *,
    run_id: str,
    state: str,
    old_pointer_bytes: bytes | None,
    new_generation_id: str | None,
    error: str = "",
) -> bytes:
    return canonical_json_bytes(
        {
            "schema_version": "lakes_kb_transaction.v1",
            "run_id": run_id,
            "state": state,
            "old_pointer_base64": (
                base64.b64encode(old_pointer_bytes).decode("ascii")
                if old_pointer_bytes is not None
                else None
            ),
            "new_generation_id": new_generation_id,
            "error": error[:240],
        }
    )


def _call_fault(fault_hook: Callable[[str], None] | None, stage: str) -> None:
    if fault_hook is not None:
        fault_hook(stage)


def _write_index(
    index: VectorIndex,
    path: Path,
    store: PassageStore,
    store_digest: str,
) -> bytes:
    expected_ids = [passage.passage_id for passage in store.passages]
    metadata = dict(index.metadata)
    for key, expected in (
        ("passage_ids", expected_ids),
        ("passage_store_sha256", store_digest),
    ):
        if key in metadata and metadata[key] != expected:
            raise GenerationValidationError(f"index builder returned conflicting {key}")
        metadata[key] = expected
    index.save(path, metadata=metadata)
    data = path.read_bytes()
    with path.open("rb") as handle:
        os.fsync(handle.fileno())
    return data


def publish_generation(
    *,
    kb_root: Path,
    performance_kb: PerformanceKnowledgeBase,
    passage_store: PassageStore,
    vector_index: VectorIndex,
    rejects: list[RejectRecord],
    created_at: str,
    run_id: str,
    old_pointer_bytes: bytes | None,
    fault_hook: Callable[[str], None] | None = None,
) -> PublishResult:
    """Publish complete immutable files, then make them visible with one replace."""
    generations = kb_root / GENERATIONS_DIR
    transactions = kb_root / TRANSACTIONS_DIR / run_id
    generations.mkdir(parents=True, exist_ok=True)
    transactions.mkdir(parents=True, exist_ok=False)
    journal_path = transactions / "journal.json"
    atomic_replace_bytes(
        journal_path,
        _journal_bytes(
            run_id=run_id,
            state="PREPARED",
            old_pointer_bytes=old_pointer_bytes,
            new_generation_id=None,
        ),
    )
    staging = generations / f".staging-{run_id}"
    staging.mkdir()
    pointer_replaced = False
    final_dir: Path | None = None
    try:
        perf_data = performance_bytes(performance_kb)
        passage_data = passage_bytes(passage_store)
        rejects_data = reject_bytes(rejects)
        write_bytes_fsync(staging / "performance_db.json", perf_data)
        _call_fault(fault_hook, "after_performance_write")
        write_bytes_fsync(staging / "passage_store.json", passage_data)
        _call_fault(fault_hook, "after_passage_write")
        index_data = _write_index(
            vector_index,
            staging / "vector_index.json",
            passage_store,
            sha256_bytes(passage_data),
        )
        _call_fault(fault_hook, "after_index_write")
        write_bytes_fsync(staging / "reject_log.json", rejects_data)
        _call_fault(fault_hook, "after_reject_write")
        content_records = {
            "performance_db.json": _file_record(perf_data),
            "passage_store.json": _file_record(passage_data),
            "vector_index.json": _file_record(index_data),
            "reject_log.json": _file_record(rejects_data),
        }
        generation_id = "kbgen_" + sha256_bytes(
            canonical_json_bytes(
                {name: record.sha256 for name, record in sorted(content_records.items())}
            )
        )[:32]
        observation_count = sum(
            len(entry.performance_observations) for entry in performance_kb.entries
        )
        manifest = KbGenerationManifest(
            generation_id=generation_id,
            created_at=created_at,
            files=content_records,
            performance_entries=len(performance_kb.entries),
            performance_observations=observation_count,
            passages=len(passage_store.passages),
            rejected_candidates=len(rejects),
            stage1_ineligible_observations=sum(
                not observation.stage1_eligible
                for entry in performance_kb.entries
                for observation in entry.performance_observations
            ),
        )
        manifest_data = canonical_json_bytes(manifest.model_dump(mode="json"))
        write_bytes_fsync(staging / "manifest.json", manifest_data)
        _fsync_directory(staging)
        _call_fault(fault_hook, "after_manifest_write")
        validate_generation_directory(staging)
        final_dir = generations / generation_id
        if final_dir.exists():
            existing = validate_generation_directory(final_dir)
            for name, record in manifest.files.items():
                if existing.manifest.files[name] != record:
                    raise GenerationValidationError(
                        "existing generation identity has different content"
                    )
            shutil.rmtree(staging)
        else:
            os.replace(staging, final_dir)
            _fsync_directory(generations)
        atomic_replace_bytes(
            journal_path,
            _journal_bytes(
                run_id=run_id,
                state="GENERATION_PUBLISHED",
                old_pointer_bytes=old_pointer_bytes,
                new_generation_id=generation_id,
            ),
        )
        _call_fault(fault_hook, "after_generation_publish")
        new_pointer = KbPointer(
            generation_id=generation_id,
            manifest_sha256=sha256_bytes((final_dir / "manifest.json").read_bytes()),
        )
        pointer_data = canonical_json_bytes(new_pointer.model_dump(mode="json"))
        if old_pointer_bytes == pointer_data:
            atomic_replace_bytes(
                journal_path,
                _journal_bytes(
                    run_id=run_id,
                    state="COMMITTED",
                    old_pointer_bytes=old_pointer_bytes,
                    new_generation_id=generation_id,
                ),
            )
            loaded = load_current_generation(kb_root)
            return PublishResult(status="NOOP", generation=loaded)
        _call_fault(fault_hook, "before_pointer_replace")
        atomic_replace_bytes(kb_root / POINTER_FILE, pointer_data)
        pointer_replaced = True
        _call_fault(fault_hook, "after_pointer_replace")
        loaded = load_current_generation(kb_root)
        _call_fault(fault_hook, "after_postflip_verify")
        atomic_replace_bytes(
            journal_path,
            _journal_bytes(
                run_id=run_id,
                state="COMMITTED",
                old_pointer_bytes=old_pointer_bytes,
                new_generation_id=generation_id,
            ),
        )
        return PublishResult(status="COMMITTED", generation=loaded)
    except Exception as exc:
        if staging.exists():
            shutil.rmtree(staging)
        if not pointer_replaced:
            atomic_replace_bytes(
                journal_path,
                _journal_bytes(
                    run_id=run_id,
                    state="ABORTED",
                    old_pointer_bytes=old_pointer_bytes,
                    new_generation_id=final_dir.name if final_dir else None,
                    error=str(exc),
                ),
            )
            if isinstance(exc, GenerationCommitError):
                raise
            raise GenerationCommitError(
                f"generation publication failed before pointer commit: {exc}"
            ) from exc
        try:
            pointer_path = kb_root / POINTER_FILE
            if old_pointer_bytes is None:
                pointer_path.unlink(missing_ok=True)
                _fsync_directory(kb_root)
            else:
                atomic_replace_bytes(pointer_path, old_pointer_bytes)
                load_current_generation(kb_root)
            atomic_replace_bytes(
                journal_path,
                _journal_bytes(
                    run_id=run_id,
                    state="ROLLED_BACK",
                    old_pointer_bytes=old_pointer_bytes,
                    new_generation_id=final_dir.name if final_dir else None,
                    error=str(exc),
                ),
            )
        except Exception as rollback_exc:
            raise RecoveryRequiredError(
                f"post-commit verification failed and rollback requires recovery: {rollback_exc}"
            ) from rollback_exc
        raise GenerationCommitError(
            f"post-commit verification failed; prior pointer was rolled back: {exc}"
        ) from exc


def recover_kb_root(kb_root: str | Path) -> RecoveryResult:
    root = Path(kb_root)
    pointer = root / POINTER_FILE
    if not pointer.exists():
        return RecoveryResult(status="NO_POINTER")
    try:
        loaded = load_current_generation(root)
        return RecoveryResult(status="VALID", generation_id=loaded.pointer.generation_id)
    except GenerationValidationError as current_error:
        journals = sorted((root / TRANSACTIONS_DIR).glob("*/journal.json"), reverse=True)
        for journal in journals:
            try:
                payload = json.loads(journal.read_text(encoding="utf-8"))
                encoded = payload.get("old_pointer_base64")
                if not encoded:
                    continue
                old_pointer = base64.b64decode(encoded, validate=True)
                atomic_replace_bytes(pointer, old_pointer)
                loaded = load_current_generation(root)
                return RecoveryResult(
                    status="RESTORED", generation_id=loaded.pointer.generation_id
                )
            except Exception:
                continue
        raise RecoveryRequiredError(
            f"current pointer is invalid and no verified rollback target exists: {current_error}"
        ) from current_error
