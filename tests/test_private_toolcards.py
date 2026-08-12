from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import toolrank.contract_profile as contract_profile
import toolrank.engine as engine
import toolrank.kb_generation as kb_generation
import toolrank.scene_pool as scene_pool_module
import toolrank.toolcard_snapshot as snapshot_module
from toolrank.passage_store import passage_store_sha256
from toolrank.schemas import ContractFeatures, PerformanceKnowledgeBase
from toolrank.schemas_v2 import Passage, PassageStore, PipelineStatus, ScenePool, ScorePanel
from toolrank.toolcard_snapshot import (
    PRIVATE_SNAPSHOT_WARNING,
    resolve_static_toolcard_snapshot,
)
from toolrank.vector_store import VectorIndex
from tests.stage1_fixtures import scene_pool, tool_entry


ROOT = Path(__file__).resolve().parents[1]


def _touch_snapshot(root: Path) -> tuple[Path, Path, Path, Path]:
    private = root / ".private"
    private.mkdir(parents=True)
    performance = private / "performance_db.json"
    profiles = private / "contract_profiles.json"
    passage_store = private / "passage_store.json"
    vector_index = private / "vector_index" / "index.json"
    for path in (performance, profiles, passage_store, vector_index):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    return performance, profiles, passage_store, vector_index


def _bypass_snapshot_content_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        snapshot_module,
        "_validate_private_snapshot",
        lambda **_kwargs: None,
    )


def _passage(
    passage_id: str,
    *,
    claim: str,
    linked_evaluation_ids: list[str] | None,
) -> Passage:
    return Passage(
        passage_id=passage_id,
        source_id=f"source_{passage_id}",
        owner_tool="osiris",
        category="arithmetic",
        knowledge_kind="category_capability",
        action_scope=["PLAN_COMPOSITION"],
        applicability_tags=[],
        relation_to_owner="supports_owner",
        evidence_basis="manual_curation",
        source_reliability="manual_curated",
        claim_text=claim,
        source_excerpt=f"Curated source excerpt: {claim}",
        linked_evaluation_ids=linked_evaluation_ids,
    )


def _write_rag_snapshot_fixture(root: Path) -> tuple[PassageStore, PassageStore]:
    public_store = PassageStore(
        passages=[
            _passage(
                "p_public_arithmetic",
                claim="Public evidence describes arithmetic analysis behavior.",
                linked_evaluation_ids=None,
            )
        ]
    )
    private_store = PassageStore(
        passages=[
            public_store.passages[0],
            _passage(
                "p_private_osiris_arithmetic",
                claim="Local qualitative evidence describes arithmetic analysis.",
                linked_evaluation_ids=[],
            ),
        ]
    )
    private_root = root / ".private"
    private_root.mkdir(parents=True, exist_ok=True)
    (root / "passage_store.json").write_text(
        json.dumps(public_store.model_dump(mode="json")),
        encoding="utf-8",
    )
    (private_root / "passage_store.json").write_text(
        json.dumps(private_store.model_dump(mode="json")),
        encoding="utf-8",
    )
    VectorIndex(
        embeddings=[[1.0, 0.0]],
    ).save(
        root / "vector_index" / "index.json",
        metadata={
            "provider": "test-provider",
            "model": "test-embedding-model",
            "passage_ids": [
                passage.passage_id for passage in public_store.passages
            ],
        },
    )
    VectorIndex(
        embeddings=[[1.0, 0.0], [0.0, 1.0]],
    ).save(
        private_root / "vector_index" / "index.json",
        metadata={
            "provider": "test-provider",
            "model": "test-embedding-model",
            "passage_ids": [
                passage.passage_id for passage in private_store.passages
            ],
            "passage_store_sha256": passage_store_sha256(private_store),
        },
    )
    return public_store, private_store


def _write_snapshot_fixture(
    root: Path,
    *,
    private_performance_dataset: str,
    private_profile_dataset: str,
    stale_public_entry: bool = False,
) -> None:
    public_entry = {
        "source_id": "public-source",
        "dataset_profile": {"dataset_name": "public-dataset"},
    }
    public_kb = {
        "knowledge_base_type": "performance",
        "criteria": {},
        "entries": [public_entry],
    }
    private_public_entry = dict(public_entry)
    if stale_public_entry:
        private_public_entry["publication_date"] = "stale"
    private_kb = {
        "knowledge_base_type": "performance",
        "criteria": {},
        "entries": [
            private_public_entry,
            {
                "source_id": "private-source",
                "dataset_profile": {
                    "dataset_name": private_performance_dataset,
                },
            },
        ],
    }
    public_profiles = {
        "_counts": {"public-dataset": 1},
        "_coverage": {"public-dataset": {"attempted": 1}},
        "datasets": {"public-dataset": [{"id": "public-dataset::one.sol"}]},
    }
    private_profiles = {
        "_counts": {"public-dataset": 1, private_profile_dataset: 1},
        "_coverage": {
            "public-dataset": {"attempted": 1},
            private_profile_dataset: {"attempted": 1},
        },
        "datasets": {
            "public-dataset": [{"id": "public-dataset::one.sol"}],
            private_profile_dataset: [
                {"id": f"{private_profile_dataset}::one.sol"},
            ],
        },
    }
    _write_rag_snapshot_fixture(root)
    private_root = root / ".private"
    for path, payload in (
        (root / "performance_db.json", public_kb),
        (root / "contract_profiles.json", public_profiles),
        (private_root / "performance_db.json", private_kb),
        (private_root / "contract_profiles.json", private_profiles),
    ):
        path.write_text(json.dumps(payload), encoding="utf-8")


def _empty_kb() -> PerformanceKnowledgeBase:
    return PerformanceKnowledgeBase(knowledge_base_type="performance", entries=[])


def _configure_terminal_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    seen_profiles: list[Path],
) -> None:
    monkeypatch.setattr(
        contract_profile,
        "analyze_target",
        lambda _path: ContractFeatures(
            target_path="fake.sol",
            source_kind="sol",
            primary_solidity_version="0.8.20",
            loc_total=1,
        ),
    )

    def fake_scene_pool(_features, _kb, *, profiles_path):
        seen_profiles.append(Path(profiles_path))
        return ScenePool(neighbors=[])

    monkeypatch.setattr(scene_pool_module, "build_scene_pool", fake_scene_pool)


def _configure_ready_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        contract_profile,
        "analyze_target",
        lambda _path: ContractFeatures(
            target_path="fake.sol",
            source_kind="sol",
            primary_solidity_version="0.8.20",
            loc_total=1,
        ),
    )
    monkeypatch.setattr(
        scene_pool_module,
        "build_scene_pool",
        lambda *_args, **_kwargs: scene_pool(("d1", 1.0, 1.0)),
    )
    monkeypatch.setattr(engine, "load_toolcards", lambda _path: [])
    monkeypatch.setattr(
        engine,
        "build_tool_table",
        lambda *_args, **_kwargs: [tool_entry("a", runtime=2.0)],
    )
    monkeypatch.setattr(
        engine,
        "compute_scene_scores",
        lambda *_args, **_kwargs: ScorePanel(
            nominal_scores=[
                {
                    "tool": "a",
                    "S_scene": 1.0,
                    "rank": 1,
                    "support_mass": 1.0,
                }
            ]
        ),
    )
    monkeypatch.setattr(engine, "load_performance_db", lambda _path: _empty_kb())


def test_static_snapshot_defaults_to_public_knowledge(tmp_path: Path) -> None:
    resolved = resolve_static_toolcard_snapshot(tmp_path)

    assert resolved.private_active is False
    assert resolved.performance_db_path == tmp_path / "performance_db.json"
    assert resolved.contract_profiles_path == tmp_path / "contract_profiles.json"
    assert resolved.passage_store_path == tmp_path / "passage_store.json"
    assert (
        resolved.vector_index_path
        == tmp_path / "vector_index" / "index.json"
    )


def test_recovery_source_alone_is_not_a_runtime_artifact(
    tmp_path: Path,
) -> None:
    private = tmp_path / ".private"
    private.mkdir()
    (private / "recovery_source.json").write_text(
        '{"passages": []}\n',
        encoding="utf-8",
    )

    resolved = resolve_static_toolcard_snapshot(tmp_path)

    assert resolved.private_active is False
    assert resolved.passage_store_path == tmp_path / "passage_store.json"


def test_public_profile_metadata_contains_only_release_datasets() -> None:
    manifest_path = ROOT / "toolcards" / "contract_profile_manifest.json"
    profile_path = ROOT / "toolcards" / "contract_profiles.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    profile = json.loads(profile_path.read_text(encoding="utf-8"))

    included_names = [
        row["name"] for row in manifest["datasets"] if row["include"]
    ]
    excluded_rows = [
        {
            key: row[key]
            for key in ("name", "path", "reason", "duplicate_of")
            if key in row
        }
        for row in manifest["datasets"]
        if not row["include"]
    ]

    assert all(row.get("duplicate_of") in included_names for row in excluded_rows)
    assert profile["_meta"]["dataset_names"] == included_names
    assert profile["_meta"]["excluded_datasets"] == excluded_rows
    assert profile["_meta"]["manifest_digest"] == hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()


def test_static_snapshot_selects_complete_private_knowledge(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _bypass_snapshot_content_validation(monkeypatch)
    performance, profiles, passage_store, vector_index = _touch_snapshot(tmp_path)

    resolved = resolve_static_toolcard_snapshot(tmp_path)

    assert resolved.private_active is True
    assert resolved.performance_db_path == performance
    assert resolved.contract_profiles_path == profiles
    assert resolved.passage_store_path == passage_store
    assert resolved.vector_index_path == vector_index


@pytest.mark.parametrize(
    "relative_path",
    [
        "performance_db.json",
        "contract_profiles.json",
        "passage_store.json",
        "vector_index/index.json",
    ],
)
def test_static_snapshot_rejects_symlinked_private_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    relative_path: str,
) -> None:
    _bypass_snapshot_content_validation(monkeypatch)
    _touch_snapshot(tmp_path)
    artifact = tmp_path / ".private" / relative_path
    target = tmp_path / ".private" / "symlink_target.json"
    target.write_text("{}\n", encoding="utf-8")
    artifact.unlink()
    artifact.symlink_to(target)

    with pytest.raises(ValueError, match="must be regular files"):
        resolve_static_toolcard_snapshot(tmp_path)


@pytest.mark.parametrize(
    "relative_path",
    [
        "performance_db.json",
        "contract_profiles.json",
        "passage_store.json",
        "vector_index/index.json",
    ],
)
def test_static_snapshot_rejects_any_incomplete_private_artifact(
    tmp_path: Path,
    relative_path: str,
) -> None:
    private = tmp_path / ".private"
    private.mkdir()
    artifact = private / relative_path
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="incomplete local-private toolcards snapshot"):
        resolve_static_toolcard_snapshot(tmp_path)


def test_static_snapshot_rejects_complete_benchmark_pair_without_rag(
    tmp_path: Path,
) -> None:
    private = tmp_path / ".private"
    private.mkdir()
    for filename in ("performance_db.json", "contract_profiles.json"):
        (private / filename).write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="incomplete local-private toolcards snapshot"):
        resolve_static_toolcard_snapshot(tmp_path)


def test_static_snapshot_rejects_stale_public_performance_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_snapshot_fixture(
        tmp_path,
        private_performance_dataset="private-dataset",
        private_profile_dataset="private-dataset",
        stale_public_entry=True,
    )
    monkeypatch.setattr(snapshot_module, "load_performance_db", lambda _path: None)
    monkeypatch.setattr(snapshot_module, "load_profiles", lambda _path: None)

    with pytest.raises(ValueError, match="must exactly extend the current public KB"):
        resolve_static_toolcard_snapshot(tmp_path)


def test_static_snapshot_rejects_mismatched_private_dataset_identities(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_snapshot_fixture(
        tmp_path,
        private_performance_dataset="private-performance-dataset",
        private_profile_dataset="private-profile-dataset",
    )
    monkeypatch.setattr(snapshot_module, "load_performance_db", lambda _path: None)
    monkeypatch.setattr(snapshot_module, "load_profiles", lambda _path: None)

    with pytest.raises(ValueError, match="dataset identities do not match"):
        resolve_static_toolcard_snapshot(tmp_path)


def _configure_valid_rag_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[PassageStore, PassageStore]:
    _write_snapshot_fixture(
        tmp_path,
        private_performance_dataset="private-dataset",
        private_profile_dataset="private-dataset",
    )
    monkeypatch.setattr(snapshot_module, "load_performance_db", lambda _path: None)
    monkeypatch.setattr(snapshot_module, "load_profiles", lambda _path: None)
    return (
        PassageStore.model_validate_json(
            (tmp_path / "passage_store.json").read_text(encoding="utf-8")
        ),
        PassageStore.model_validate_json(
            (tmp_path / ".private" / "passage_store.json").read_text(
                encoding="utf-8"
            )
        ),
    )


def test_static_snapshot_rejects_stale_public_passage_prefix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_valid_rag_snapshot(monkeypatch, tmp_path)
    path = tmp_path / ".private" / "passage_store.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["passages"][0]["claim_text"] = (
        "Stale private copy changed the public evidence claim."
    )
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="exactly extend the current public PassageStore"):
        resolve_static_toolcard_snapshot(tmp_path)


def test_static_snapshot_rejects_passage_vector_id_order_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_valid_rag_snapshot(monkeypatch, tmp_path)
    path = tmp_path / ".private" / "vector_index" / "index.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["metadata"]["passage_ids"].reverse()
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="passage IDs do not match"):
        resolve_static_toolcard_snapshot(tmp_path)


def test_static_snapshot_rejects_embedding_dimension_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_valid_rag_snapshot(monkeypatch, tmp_path)
    path = tmp_path / ".private" / "vector_index" / "index.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["embeddings"][-1] = [0.0, 1.0, 0.0]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="embedding dimension"):
        resolve_static_toolcard_snapshot(tmp_path)


def test_static_snapshot_rejects_changed_public_embedding_prefix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_valid_rag_snapshot(monkeypatch, tmp_path)
    path = tmp_path / ".private" / "vector_index" / "index.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["embeddings"][0] = [0.5, 0.5]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="exactly retain the public embedding prefix"):
        resolve_static_toolcard_snapshot(tmp_path)


@pytest.mark.parametrize("metadata_key", ["provider", "model"])
def test_static_snapshot_rejects_incompatible_embedding_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    metadata_key: str,
) -> None:
    _configure_valid_rag_snapshot(monkeypatch, tmp_path)
    path = tmp_path / ".private" / "vector_index" / "index.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["metadata"][metadata_key] = "incompatible"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=f"{metadata_key} must match"):
        resolve_static_toolcard_snapshot(tmp_path)


def test_static_snapshot_rejects_private_passage_digest_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_valid_rag_snapshot(monkeypatch, tmp_path)
    path = tmp_path / ".private" / "vector_index" / "index.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["metadata"]["passage_store_sha256"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="passage-store digest mismatch"):
        resolve_static_toolcard_snapshot(tmp_path)


@pytest.mark.parametrize(
    "linked_evaluation_ids",
    [None, ["stage1_eval::osiris::private-dataset"]],
)
def test_static_snapshot_requires_private_passages_to_be_explicitly_qualitative(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    linked_evaluation_ids: list[str] | None,
) -> None:
    _configure_valid_rag_snapshot(monkeypatch, tmp_path)
    path = tmp_path / ".private" / "passage_store.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["passages"][-1]["linked_evaluation_ids"] = linked_evaluation_ids
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="explicitly qualitative"):
        resolve_static_toolcard_snapshot(tmp_path)


def test_static_snapshot_rejects_private_performance_observation_links(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_valid_rag_snapshot(monkeypatch, tmp_path)
    path = tmp_path / ".private" / "passage_store.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    passage = payload["passages"][-1]
    observation_id = "perf_" + "1" * 32
    passage["linked_performance_observation_ids"] = [observation_id]
    passage["performance_observation_refs"] = [
        {
            "observation_id": observation_id,
            "source_id": "private-source",
            "canonical_dataset_id": "private-dataset",
            "dataset_name": "private-dataset",
            "tool": passage["owner_tool"],
            "category": passage["category"],
            "paper_id": "paper_" + "2" * 32,
        }
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="explicitly qualitative"):
        resolve_static_toolcard_snapshot(tmp_path)


def test_static_snapshot_accepts_explicitly_qualitative_private_passage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, private_store = _configure_valid_rag_snapshot(monkeypatch, tmp_path)

    resolved = resolve_static_toolcard_snapshot(tmp_path)

    assert resolved.private_active is True
    assert private_store.passages[-1].linked_evaluation_ids == []


def test_engine_loads_complete_private_knowledge_and_warns(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _bypass_snapshot_content_validation(monkeypatch)
    performance, profiles, _, _ = _touch_snapshot(tmp_path)
    seen_performance: list[Path] = []
    seen_profiles: list[Path] = []
    _configure_terminal_pipeline(monkeypatch, seen_profiles=seen_profiles)

    def fake_performance(path):
        seen_performance.append(Path(path))
        return _empty_kb()

    monkeypatch.setattr(engine, "load_performance_db", fake_performance)
    result = engine.run_recommendation(
        target_path="fake.sol",
        toolcards_dir=str(tmp_path),
        enable_retrieval=False,
    )

    assert result.status == PipelineStatus.PRIMARY_NOT_SELECTED
    assert seen_performance == [performance]
    assert seen_profiles == [profiles]
    assert PRIVATE_SNAPSHOT_WARNING in result.warnings
    assert PRIVATE_SNAPSHOT_WARNING in capsys.readouterr().err


@pytest.mark.parametrize(
    ("passage_override", "index_override"),
    [
        ("custom_passages.json", None),
        (None, "custom_index.json"),
    ],
)
def test_engine_static_retrieval_defaults_to_snapshot_with_individual_overrides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    passage_override: str | None,
    index_override: str | None,
) -> None:
    _bypass_snapshot_content_validation(monkeypatch)
    _, _, private_passage, private_index = _touch_snapshot(tmp_path)
    _configure_ready_pipeline(monkeypatch)
    seen: list[tuple[Path, Path, bool]] = []

    def fake_retriever(passage_path, index_path, *, enabled):
        seen.append((Path(passage_path), Path(index_path), enabled))
        return None

    monkeypatch.setattr(engine, "_load_passage_retriever", fake_retriever)
    result = engine.run_recommendation(
        target_path="fake.sol",
        toolcards_dir=str(tmp_path),
        passage_store_path=passage_override,
        vector_index_path=index_override,
        emit_stderr=False,
    )

    assert result.status == PipelineStatus.PLAN_READY
    assert seen == [
        (
            Path(passage_override) if passage_override else private_passage,
            Path(index_override) if index_override else private_index,
            True,
        )
    ]


def test_explicit_kb_root_bypasses_incomplete_private_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    private = tmp_path / ".private"
    private.mkdir()
    (private / "performance_db.json").write_text("{}\n", encoding="utf-8")
    seen_profiles: list[Path] = []
    _configure_terminal_pipeline(monkeypatch, seen_profiles=seen_profiles)
    monkeypatch.setattr(
        kb_generation,
        "load_current_generation",
        lambda _root: SimpleNamespace(performance_kb=_empty_kb()),
    )
    monkeypatch.setattr(
        engine,
        "load_performance_db",
        lambda _path: pytest.fail("static Performance KB must be bypassed"),
    )

    result = engine.run_recommendation(
        target_path="fake.sol",
        toolcards_dir=str(tmp_path),
        kb_root=str(tmp_path / "dynamic"),
        enable_retrieval=False,
        emit_stderr=False,
    )

    assert result.status == PipelineStatus.PRIMARY_NOT_SELECTED
    assert seen_profiles == [tmp_path / "contract_profiles.json"]
    assert PRIVATE_SNAPSHOT_WARNING not in result.warnings
