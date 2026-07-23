from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.test_kb_update_extract import _document, extraction_fixture
from tests.test_kb_update_validation import _card
from toolrank.kb_generation import (
    GenerationCommitError,
    GenerationValidationError,
    load_current_generation,
    recover_kb_root,
    validate_generation_directory,
    validate_kb_root,
)
from toolrank import kb_update_service
from toolrank.kb_update_service import DensePassageIndexBuilder, KbUpdateService
from toolrank.schemas import PerformanceKnowledgeBase
from toolrank.schemas_v2 import PassageStore
from toolrank.vector_store import VectorIndex


class FakeConverter:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def convert(self, _pdf: Path, _work_dir: Path):
        self.calls += 1
        if self.error:
            raise self.error
        return _document()


class FakeExtractor:
    def __init__(self, category: str = "reentrancy", *, conflict: bool = False) -> None:
        self.category = category
        self.conflict = conflict

    def extract(self, _document):
        extraction = extraction_fixture(category=self.category)
        if self.conflict:
            extraction.dataset_claims[0].detected = 7
            extraction.dataset_claims[1].value = 70.0
            extraction.dataset_claims[2].value = 0.5
            extraction.capability_claims[0].limitations_text = "Conflicting limitation."
        return extraction


class FakeIndexBuilder:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def build(self, store: PassageStore) -> VectorIndex:
        self.calls += 1
        if self.error:
            raise self.error
        embeddings = [[float(index + 1), 1.0] for index, _ in enumerate(store.passages)]
        return VectorIndex(embeddings=embeddings, metadata={"provider": "fixture", "model": "fixture"})


def _baseline(tmp_path: Path) -> tuple[Path, Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    performance_path = tmp_path / "baseline_performance.json"
    passage_path = tmp_path / "baseline_passages.json"
    index_path = tmp_path / "baseline_index.json"
    performance_path.write_text(
        PerformanceKnowledgeBase(
            knowledge_base_type="performance_context_db",
            criteria={"runtime_unit": "seconds", "runtime_basis_default": "per_contract"},
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )
    store = PassageStore()
    passage_path.write_text(store.model_dump_json(indent=2), encoding="utf-8")
    VectorIndex().save(
        index_path,
        metadata={
            "passage_ids": [],
            "passage_store_sha256": hashlib.sha256(
                (store.model_dump_json(indent=2) + "\n").encode()
            ).hexdigest(),
        },
    )
    return performance_path, passage_path, index_path


def _service(
    tmp_path: Path,
    *,
    fault_hook=None,
    index_builder=None,
    category: str = "reentrancy",
    conflict: bool = False,
) -> KbUpdateService:
    performance, passages, index = _baseline(tmp_path)
    return KbUpdateService(
        converter=FakeConverter(),
        extractor=FakeExtractor(category, conflict=conflict),
        index_builder=index_builder or FakeIndexBuilder(),
        toolcards=[_card()],
        profiled_dataset_names=set(),
        baseline_performance_path=performance,
        baseline_passage_path=passages,
        baseline_vector_index_path=index,
        clock=lambda: "2026-07-19T00:00:00Z",
        run_id_factory=lambda: "run_fixture",
        fault_hook=fault_hook,
    )


def test_commit_publishes_one_full_validated_generation(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF fixture")
    result = _service(tmp_path).update(pdf=pdf, kb_root=root)

    assert result.status == "COMMITTED"
    assert result.accepted_observations == 3
    assert result.accepted_passages == 1
    pointer = json.loads((root / "kb_current.json").read_text(encoding="utf-8"))
    generation = root / ".kb_generations" / pointer["generation_id"]
    assert {
        "performance_db.json",
        "passage_store.json",
        "vector_index.json",
        "manifest.json",
        "reject_log.json",
    }.issubset({path.name for path in generation.iterdir()})
    loaded = load_current_generation(root)
    assert loaded.pointer.generation_id == result.generation_id
    assert loaded.vector_index.metadata["passage_ids"] == [
        passage.passage_id for passage in loaded.passage_store.passages
    ]
    assert validate_kb_root(root).generation_id == result.generation_id


def test_dry_run_never_creates_pointer(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF fixture")
    result = _service(tmp_path).update(pdf=pdf, kb_root=root, dry_run=True)
    assert result.status == "DRY_RUN"
    assert not (root / "kb_current.json").exists()


def test_dry_run_uses_current_generation_without_changing_pointer(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF fixture")
    _service(tmp_path).update(pdf=pdf, kb_root=root)
    before = (root / "kb_current.json").read_bytes()
    service = _service(tmp_path / "second", category="access_control")

    dry_run = service.update(pdf=pdf, kb_root=root, dry_run=True)

    assert (root / "kb_current.json").read_bytes() == before
    committed = service.update(pdf=pdf, kb_root=root)
    assert dry_run.generation_id == committed.generation_id


def test_precommit_index_failure_preserves_pointer_bytes(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF fixture")
    service = _service(tmp_path)
    service.update(pdf=pdf, kb_root=root)
    before = (root / "kb_current.json").read_bytes()

    failing = _service(
        tmp_path / "second",
        index_builder=FakeIndexBuilder(error=RuntimeError("embedding failed")),
        category="access_control",
    )
    with pytest.raises(RuntimeError, match="embedding failed"):
        failing.update(pdf=pdf, kb_root=root)
    assert (root / "kb_current.json").read_bytes() == before


def test_post_flip_verification_failure_restores_exact_pointer(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF fixture")
    _service(tmp_path).update(pdf=pdf, kb_root=root)
    before = (root / "kb_current.json").read_bytes()

    def fail(stage: str) -> None:
        if stage == "after_pointer_replace":
            raise RuntimeError("post flip fault")

    with pytest.raises(GenerationCommitError, match="rolled back"):
        _service(
            tmp_path / "second",
            fault_hook=fail,
            category="access_control",
        ).update(pdf=pdf, kb_root=root)
    assert (root / "kb_current.json").read_bytes() == before
    load_current_generation(root)


def test_reader_resolves_pointer_exactly_once(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "kb"
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF fixture")
    _service(tmp_path).update(pdf=pdf, kb_root=root)
    original = Path.read_bytes
    reads = 0

    def counted(path: Path) -> bytes:
        nonlocal reads
        if path == root / "kb_current.json":
            reads += 1
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", counted)
    loaded = load_current_generation(root)
    assert loaded.performance_kb.entries
    assert loaded.passage_store.passages
    assert reads == 1


def test_engine_resolves_one_generation_pointer_for_performance_and_retrieval(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "kb"
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF fixture")
    _service(tmp_path).update(pdf=pdf, kb_root=root)
    cards = tmp_path / "cards"
    cards.mkdir()
    (cards / "Slither.json").write_text(
        json.dumps(_card().model_dump(mode="json")), encoding="utf-8"
    )
    original = Path.read_bytes
    reads = 0

    def counted(path: Path) -> bytes:
        nonlocal reads
        if path == root / "kb_current.json":
            reads += 1
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", counted)
    from toolrank.engine import run_recommendation

    result = run_recommendation(
        target_path=None,
        toolcards_dir=str(cards),
        kb_root=str(root),
        enable_retrieval=False,
        emit_stderr=False,
    )
    assert result.status.value == "PRIMARY_NOT_SELECTED"
    assert reads == 1


def test_same_input_is_generation_noop_and_dataset_scene_is_not_duplicated(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF fixture")
    service = _service(tmp_path)
    first = service.update(pdf=pdf, kb_root=root)
    second = service.update(pdf=pdf, kb_root=root)
    assert second.status == "NOOP"
    assert second.accepted_observations == 3
    assert second.accepted_passages == 1
    assert second.generation_id == first.generation_id
    loaded = load_current_generation(root)
    matching = [
        entry
        for entry in loaded.performance_kb.entries
        if entry.dataset_profile.dataset_name == "Benchmark A"
    ]
    assert len(matching) == 1
    assert len(matching[0].performance_observations) == 3


def test_all_merge_conflicts_are_rejected_and_do_not_publish(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF fixture")
    _service(tmp_path).update(pdf=pdf, kb_root=root)
    before = (root / "kb_current.json").read_bytes()

    result = _service(tmp_path / "conflict", conflict=True).update(
        pdf=pdf, kb_root=root
    )

    assert result.status == "REJECTED"
    assert result.accepted_observations == 0
    assert result.accepted_passages == 0
    assert result.rejected_candidates == 4
    assert (root / "kb_current.json").read_bytes() == before
    assert result.reject_log_path is not None


def test_manifest_validates_stage1_ineligible_count(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF fixture")
    _service(tmp_path).update(pdf=pdf, kb_root=root)
    generation_dir = load_current_generation(root).generation_dir
    manifest_path = generation_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["stage1_ineligible_observations"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(
        GenerationValidationError,
        match="Stage 1 ineligible count mismatch",
    ):
        validate_generation_directory(generation_dir)


def test_dynamic_index_builder_disables_curl_credential_fallback(monkeypatch) -> None:
    captured: dict = {}

    def fake_build(store, **kwargs):
        captured.update(kwargs)
        return VectorIndex(embeddings=[])

    monkeypatch.setattr(kb_update_service, "build_passage_vector_index", fake_build)

    DensePassageIndexBuilder().build(PassageStore())

    assert captured["allow_curl_fallback"] is False


def test_recovery_restores_last_verified_pointer_from_journal(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF fixture")
    first = _service(tmp_path).update(pdf=pdf, kb_root=root)
    _service(tmp_path / "second", category="access_control").update(
        pdf=pdf, kb_root=root
    )
    pointer = json.loads((root / "kb_current.json").read_text(encoding="utf-8"))
    pointer["manifest_sha256"] = "0" * 64
    (root / "kb_current.json").write_text(json.dumps(pointer), encoding="utf-8")

    recovered = recover_kb_root(root)
    assert recovered.status == "RESTORED"
    assert recovered.generation_id == first.generation_id
    assert load_current_generation(root).pointer.generation_id == first.generation_id
