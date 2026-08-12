from __future__ import annotations

import json

from toolrank.cego import _prompt_payload
from toolrank.dace_rag import build_action_evidence_matrix
from toolrank.engine import _load_passage_retriever
from toolrank.passage_store import PassageRetrievalResult, PassageRetriever
from toolrank.schemas_v2 import (
    Passage,
    PassageRetrievalDiagnostic,
    PassageStore,
    PrimaryAttention,
    RecallCoverageMatrix,
    Stage2EvidenceContext,
    stage1_evaluation_id,
)
from toolrank.vector_store import VectorIndex
from tests.stage1_fixtures import tool_entry
from tests.stage2_fixtures import budget, stage2_context


def _passage(
    passage_id: str,
    *,
    owner_tool: str = "b",
    category: str = "reentrancy",
    claim: str = "Tool b detects reentrancy with benchmark-backed category evidence.",
) -> Passage:
    return Passage(
        passage_id=passage_id,
        source_id=f"source_{passage_id}",
        owner_tool=owner_tool,
        category=category,
        knowledge_kind="category_capability",
        action_scope=["PLAN_COMPOSITION"],
        applicability_tags=["solc:0.8.x"],
        relation_to_owner="supports_owner",
        evidence_basis="benchmark_result",
        source_reliability="peer_reviewed",
        claim_text=claim,
        source_excerpt=f"Published evaluation: {claim}",
    )


def _clear_embedding_keys(monkeypatch) -> None:
    for name in (
        "embeddingAPI",
        "SILICONFLOW_API_KEY",
        "QWEN_API_KEY",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_missing_dense_key_uses_visible_deterministic_bm25_fallback(monkeypatch) -> None:
    _clear_embedding_keys(monkeypatch)
    passages = [
        _passage("passage_lexical_match"),
        _passage(
            "passage_other_claim",
            claim="Tool b reports unrelated timestamp diagnostics in source code.",
        ),
    ]
    retriever = PassageRetriever(
        PassageStore(passages=passages),
        index=VectorIndex(embeddings=[[1.0, 0.0], [0.0, 1.0]]),
    )

    first = retriever.retrieve_for_action(
        category="reentrancy",
        owner_tool="b",
        action_scope="PLAN_COMPOSITION",
        top_k=2,
    )
    second = retriever.retrieve_for_action(
        category="reentrancy",
        owner_tool="b",
        action_scope="PLAN_COMPOSITION",
        top_k=2,
    )

    assert [item.passage_id for item in first.passages] == [
        item.passage_id for item in second.passages
    ]
    assert first.passages
    assert first.diagnostic.mode == "LEXICAL_BM25_FALLBACK"
    assert first.diagnostic.dense_status == "API_KEY_UNAVAILABLE"
    assert "DENSE_API_KEY_UNAVAILABLE" in first.diagnostic.reason_codes
    assert first.diagnostic.lexical_hit_count == 2
    assert first.diagnostic.returned_passage_ids == [
        item.passage_id for item in first.passages
    ]


def test_configured_dense_search_is_fused_with_bm25(monkeypatch) -> None:
    monkeypatch.setenv("embeddingAPI", "fixture-key")
    monkeypatch.setattr(
        "toolrank.vector_store.get_embeddings",
        lambda texts, **_kwargs: [[1.0, 0.0] for _text in texts],
    )
    passages = [
        _passage("passage_dense_and_lexical"),
        _passage(
            "passage_dense_only",
            claim="Tool b supports a separate smart-contract weakness class.",
        ),
    ]
    retriever = PassageRetriever(
        PassageStore(passages=passages),
        index=VectorIndex(embeddings=[[0.0, 1.0], [1.0, 0.0]]),
    )

    result = retriever.retrieve_for_action(
        category="reentrancy",
        owner_tool="b",
        action_scope="PLAN_COMPOSITION",
        top_k=2,
    )

    assert result.diagnostic.mode == "HYBRID_BM25_DENSE"
    assert result.diagnostic.dense_status == "USED"
    assert result.diagnostic.fusion_method == "reciprocal_rank_fusion"
    assert result.diagnostic.lexical_hit_count == 2
    assert result.diagnostic.dense_hit_count == 2
    assert {item.passage_id for item in result.passages} == {
        "passage_dense_and_lexical",
        "passage_dense_only",
    }


def test_dense_query_failure_keeps_lexical_passages_and_reports_failure(monkeypatch) -> None:
    monkeypatch.setenv("embeddingAPI", "fixture-key")

    def fail_embeddings(_texts, **_kwargs):
        raise RuntimeError("embedding endpoint unavailable")

    monkeypatch.setattr("toolrank.vector_store.get_embeddings", fail_embeddings)
    passage = _passage("passage_survives_dense_failure")
    retriever = PassageRetriever(
        PassageStore(passages=[passage]),
        index=VectorIndex(embeddings=[[1.0, 0.0]]),
    )

    result = retriever.retrieve_for_action(
        category="reentrancy",
        owner_tool="b",
        action_scope="PLAN_COMPOSITION",
    )

    assert [item.passage_id for item in result.passages] == [passage.passage_id]
    assert result.diagnostic.mode == "LEXICAL_BM25_FALLBACK"
    assert result.diagnostic.dense_status == "QUERY_FAILED"
    assert "DENSE_QUERY_FAILED" in result.diagnostic.reason_codes


def test_engine_loader_keeps_lexical_retrieval_without_vector_index(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("embeddingAPI", "configured-but-index-is-absent")
    passage = _passage("passage_loaded_without_dense_index")
    store_path = tmp_path / "passage_store.json"
    store_path.write_text(
        PassageStore(passages=[passage]).model_dump_json(),
        encoding="utf-8",
    )

    retriever = _load_passage_retriever(
        store_path,
        tmp_path / "missing-vector-index.json",
        enabled=True,
    )

    assert retriever is not None
    result = retriever.retrieve_for_action(
        category="reentrancy",
        owner_tool="b",
        action_scope="PLAN_COMPOSITION",
    )
    assert [item.passage_id for item in result.passages] == [passage.passage_id]
    assert result.diagnostic.mode == "LEXICAL_BM25_FALLBACK"
    assert result.diagnostic.dense_status == "INDEX_UNAVAILABLE"
    assert "DENSE_INDEX_UNAVAILABLE" in result.diagnostic.reason_codes


def test_hand_curated_passages_remain_retrievable_as_qualitative_bm25_evidence(
    monkeypatch,
) -> None:
    _clear_embedding_keys(monkeypatch)
    passages = [
        Passage(
            passage_id="synthetic_alpha_reentrancy_strength",
            source_id="synthetic_manual_source",
            owner_tool="analyzer_alpha",
            counterpart_tool_ids=["analyzer_baseline"],
            category="reentrancy",
            knowledge_kind="category_capability",
            action_scope=["PLAN_COMPOSITION"],
            applicability_tags=[],
            relation_to_owner="owner_stronger",
            evidence_basis="manual_curation",
            source_reliability="manual_curated",
            claim_text=(
                "Synthetic note: Analyzer Alpha recognizes a reentrancy fixture."
            ),
            source_excerpt=(
                "Synthetic retrieval corpus entry for Analyzer Alpha."
            ),
            linked_evaluation_ids=[],
        ),
        Passage(
            passage_id="synthetic_beta_reentrancy_complement",
            source_id="synthetic_manual_source",
            owner_tool="analyzer_beta",
            counterpart_tool_ids=["analyzer_baseline"],
            category="reentrancy",
            knowledge_kind="tool_complementarity",
            action_scope=["PLAN_COMPOSITION"],
            applicability_tags=["solc:0.8.x"],
            relation_to_owner="owner_complements",
            evidence_basis="manual_curation",
            source_reliability="manual_curated",
            claim_text=(
                "Synthetic note: Analyzer Beta complements a reentrancy fixture."
            ),
            source_excerpt=(
                "Synthetic retrieval corpus entry for Analyzer Beta."
            ),
            linked_evaluation_ids=[],
        ),
        Passage(
            passage_id="synthetic_gamma_arithmetic_risk",
            source_id="synthetic_manual_source",
            owner_tool="analyzer_gamma",
            category="arithmetic",
            knowledge_kind="fp_precision_risk",
            action_scope=["PLAN_COMPOSITION"],
            applicability_tags=[],
            relation_to_owner="opposes_owner",
            evidence_basis="manual_curation",
            source_reliability="manual_curated",
            claim_text=(
                "Synthetic note: Analyzer Gamma may over-report an arithmetic fixture."
            ),
            source_excerpt=(
                "Synthetic retrieval corpus entry for Analyzer Gamma."
            ),
            linked_evaluation_ids=[],
        ),
        Passage(
            passage_id="synthetic_delta_arithmetic_risk",
            source_id="synthetic_manual_source",
            owner_tool="analyzer_delta",
            category="arithmetic",
            knowledge_kind="fp_precision_risk",
            action_scope=["PLAN_COMPOSITION"],
            applicability_tags=["solc:0.8.x"],
            relation_to_owner="opposes_owner",
            evidence_basis="manual_curation",
            source_reliability="manual_curated",
            claim_text=(
                "Synthetic note: Analyzer Delta may over-report an arithmetic fixture."
            ),
            source_excerpt=(
                "Synthetic retrieval corpus entry for Analyzer Delta."
            ),
            linked_evaluation_ids=[],
        ),
    ]
    retriever = PassageRetriever(PassageStore(passages=passages))

    queries = [
        ("reentrancy", "analyzer_alpha", passages[0].passage_id),
        ("reentrancy", "analyzer_beta", passages[1].passage_id),
        ("arithmetic", "analyzer_gamma", passages[2].passage_id),
        ("arithmetic", "analyzer_delta", passages[3].passage_id),
    ]
    for category, owner_tool, expected_passage_id in queries:
        result = retriever.retrieve_for_action(
            category=category,
            owner_tool=owner_tool,
            action_scope="PLAN_COMPOSITION",
            top_k=1,
        )
        assert [item.passage_id for item in result.passages] == [
            expected_passage_id
        ]
        assert result.passages[0].linked_evaluation_ids == []
        assert result.diagnostic.mode == "LEXICAL_BM25_FALLBACK"


class RecordingCellRetriever:
    def __init__(self, passage: Passage) -> None:
        self.passage = passage
        self.calls: list[tuple[str, str, str]] = []

    def retrieve_for_action(
        self,
        *,
        category: str,
        owner_tool: str,
        action_scope: str,
        top_k: int,
    ) -> PassageRetrievalResult:
        _ = top_k
        self.calls.append((category, owner_tool, action_scope))
        passages = [self.passage] if owner_tool == self.passage.owner_tool else []
        return PassageRetrievalResult(
            passages=passages,
            diagnostic=PassageRetrievalDiagnostic(
                category=category,
                owner_tool=owner_tool,
                action_scope="PLAN_COMPOSITION",
                query_text=f"{category} {owner_tool} PLAN_COMPOSITION",
                mode="LEXICAL_BM25_FALLBACK",
                dense_status="API_KEY_UNAVAILABLE",
                reason_codes=["DENSE_API_KEY_UNAVAILABLE"],
                lexical_hit_count=len(passages),
                returned_passage_ids=[item.passage_id for item in passages],
                fusion_method="lexical_bm25",
            ),
        )


def test_dace_retrieves_per_category_owner_action_cell_and_exposes_diagnostics() -> None:
    context = stage2_context()
    retriever = RecordingCellRetriever(_passage("passage_cell_b"))
    matrix = build_action_evidence_matrix(context, budget(), retriever=retriever)

    assert retriever.calls == [
        ("reentrancy", "a", "PLAN_COMPOSITION"),
        ("reentrancy", "b", "PLAN_COMPOSITION"),
        ("reentrancy", "c", "PLAN_COMPOSITION"),
    ]
    assert [
        (item.category, item.owner_tool, item.action_scope)
        for item in matrix.retrieval_diagnostics
    ] == retriever.calls
    assert all(item.mode == "LEXICAL_BM25_FALLBACK" for item in matrix.retrieval_diagnostics)

    payload = json.loads(
        _prompt_payload(context, matrix, None, w_recall=0.5, w_precision=0.5)
    )
    assert payload["retrieval_diagnostics"] == [
        item.model_dump(mode="json") for item in matrix.retrieval_diagnostics
    ]


def test_complete_typed_primary_and_feasible_candidate_rows_reach_cego() -> None:
    context = stage2_context()
    retriever = RecordingCellRetriever(_passage("passage_matrix_b"))
    matrix = build_action_evidence_matrix(context, budget(), retriever=retriever)

    rows = {
        (row.category, row.tool): row
        for row in matrix.relevant_matrix_rows
    }
    assert set(rows) == {
        ("reentrancy", "a"),
        ("reentrancy", "b"),
        ("reentrancy", "c"),
    }

    primary = rows[("reentrancy", "a")]
    candidate = rows[("reentrancy", "b")]
    assert primary.role == "PRIMARY"
    assert primary.stage1_evidence.S_t == 1.0
    assert primary.stage1_evidence.benchmark_evaluations[0].w_D == 1.0
    assert primary.category_evidence is not None
    assert primary.category_evidence.R_hat == 0.0
    assert set(primary.evidence_by_slot) == {"FOR", "AGAINST", "COMPARE", "GAP"}

    assert candidate.role == "FEASIBLE_CANDIDATE"
    assert candidate.strength is not None
    assert candidate.strength.evidence_stronger is True
    assert candidate.target_constraints.primary_solidity_version == "0.8.20"
    assert candidate.target_constraints.solidity_version_constraints == ["^0.8.20"]
    assert candidate.target_constraints.gower_solc_bucket == "0.8.x"
    assert candidate.runtime_evidence.planning_runtime_minutes == 8.0
    assert candidate.runtime_evidence.runtime_provenance is not None
    assert any(
        item.evidence_id == "passage_matrix_b" and item.applies_to_target is True
        for item in candidate.applicability
    )

    payload = json.loads(
        _prompt_payload(context, matrix, None, w_recall=0.5, w_precision=0.5)
    )
    assert "relevant_matrix_rows" not in payload
    candidate_payload = payload["required_categories"][0]["eligible_candidates"][0]
    expected_row = candidate.model_dump(
        mode="json",
        exclude={"stage1_evidence"},
    )
    expected_row["stage1_tool_ref"] = candidate.tool
    assert candidate_payload["matrix_row"] == expected_row
    assert "evidence" not in candidate_payload
    assert (
        candidate_payload["strength"]
        == candidate.strength.model_dump(mode="json")
    )


def _nine_category_context() -> Stage2EvidenceContext:
    base = stage2_context()
    tools = [chr(ord("a") + index) for index in range(15)]
    categories = [
        "reentrancy",
        "access_control",
        "arithmetic",
        "unchecked_low_level_calls",
        "denial_of_service",
        "bad_randomness",
        "front_running",
        "time_manipulation",
        "short_addresses",
    ]
    benchmark_id = base.stage1.score_panel.benchmark_scores[0].benchmark_id
    benchmark_template = base.stage1.score_panel.benchmark_scores[0]
    nominal_template = base.stage1.score_panel.nominal_scores[0]
    benchmark_scores = [
        benchmark_template.model_copy(
            update={
                "evaluation_id": stage1_evaluation_id(tool, benchmark_id),
                "tool": tool,
                "recall": 1.0 - index / 20,
                "precision": 1.0 - index / 20,
                "recall_rank": float(index + 1),
                "precision_rank": float(index + 1),
                "score": (len(tools) - index) / len(tools),
            }
        )
        for index, tool in enumerate(tools)
    ]
    nominal_scores = [
        nominal_template.model_copy(
            update={
                "tool": tool,
                "S_scene": (len(tools) - index) / len(tools),
                "rank": index + 1,
            }
        )
        for index, tool in enumerate(tools)
    ]
    stage1 = base.stage1.model_copy(
        update={
            "tool_table": [
                tool_entry(tool, runtime=2.0 if tool == "a" else 8.0)
                for tool in tools
            ],
            "score_panel": base.stage1.score_panel.model_copy(
                update={
                    "benchmark_scores": benchmark_scores,
                    "nominal_scores": nominal_scores,
                }
            ),
            "primary_selection": base.stage1.primary_selection.model_copy(
                update={"eligible_tools": tools}
            ),
        }
    )
    coverage_templates = {
        row.tool: row
        for row in base.recall_coverage.matrix
    }
    coverage = [
        coverage_templates.get(tool, coverage_templates["c"]).model_copy(
            update={
                "tool": tool,
                "category": category,
                **(
                    {}
                    if tool in {"a", "b", "c"}
                    else {
                        "detected": 1,
                        "total": 14,
                        "R_hat": 1 / 14,
                        "n_eff": 14.0,
                        "support_level": "under_evidenced",
                    }
                ),
            }
        )
        for category in categories
        for tool in tools
    ]
    performance_template = base.performance_db_view[0]
    performance_rows = [
        performance_template.model_copy(
            update={
                "tool": tool,
                "category": category,
                "evidence_id": f"ev_full_{tool}_{category}",
                **(
                    {
                        "detected": 0,
                        "total": 15,
                        "R_hat": 0.0,
                        "n_eff": 15.0,
                    }
                    if tool == "a"
                    else {
                        "detected": 12,
                        "total": 15,
                        "R_hat": 0.8,
                        "n_eff": 15.0,
                    }
                    if tool == "b"
                    else {
                        "detected": 1,
                        "total": 14,
                        "R_hat": 1 / 14,
                        "n_eff": 14.0,
                    }
                ),
            }
        )
        for category in categories
        for tool in tools
    ]
    decisions = [
        base.primary_category_decisions[0].model_copy(
            update={"category": category}
        )
        for category in categories
    ]
    return Stage2EvidenceContext(
        stage1=stage1,
        required_categories=categories,
        category_diagnostics=base.category_diagnostics,
        recall_coverage=RecallCoverageMatrix(matrix=coverage),
        performance_db_view=performance_rows,
        tool_overall_metrics=base.tool_overall_metrics,
        primary_category_decisions=decisions,
        primary_attention=PrimaryAttention(
            primary_tool="a",
            required_categories=categories,
            confirmed_weak_categories=categories,
        ),
    )


def test_full_category_prompt_has_one_stage1_lineage_and_no_full_matrix_dump() -> None:
    context = _nine_category_context()
    matrix = build_action_evidence_matrix(context, budget())

    prompt = _prompt_payload(
        context,
        matrix,
        None,
        w_recall=0.5,
        w_precision=0.5,
    )
    payload = json.loads(prompt)

    assert len(context.required_categories) == 9
    assert len(matrix.relevant_matrix_rows) == 135
    assert len(prompt.encode("utf-8")) < 2_000_000
    assert "relevant_matrix_rows" not in payload
    assert payload["stage1_evidence"] == matrix.stage1_evidence.model_dump(
        mode="json"
    )
    assert sum(
        1
        for category in payload["required_categories"]
        for candidate in category["eligible_candidates"]
        if "stage1_evidence" in candidate["matrix_row"]
    ) == 0
