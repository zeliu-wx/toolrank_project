"""Passage store with deterministic BM25 and optional dense retrieval."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import hashlib
import math
from pathlib import Path
import re
from typing import Any, Literal

from toolrank.kb_update_models import canonical_json_bytes
from toolrank.schemas_v2 import (
    GLOBAL_CATEGORY,
    Passage,
    PassageRetrievalDiagnostic,
    PassageStore,
)
from toolrank.vector_store import VectorIndex, resolve_embedding_config


_BM25_K1 = 1.5
_BM25_B = 0.75
_RRF_K = 60


@dataclass(frozen=True)
class PassageRetrievalResult:
    passages: list[Passage]
    diagnostic: PassageRetrievalDiagnostic


def load_passage_store(path: Path) -> PassageStore | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return PassageStore.model_validate(data)


def _format_field_value(value: str | list[str]) -> str:
    if isinstance(value, list):
        return ", ".join(item for item in value if item)
    return value.strip()


def passage_to_embedding_text(passage: Passage) -> str:
    fields: list[tuple[str, str | list[str]]] = [
        ("claim_text", passage.claim_text),
        ("owner_tool", passage.owner_tool),
        ("counterpart_tool_ids", passage.counterpart_tool_ids),
        ("category", passage.category),
        ("knowledge_kind", passage.knowledge_kind),
        ("relation_to_owner", passage.relation_to_owner),
        ("action_scope", passage.action_scope),
        ("applicability_tags", passage.applicability_tags),
        ("evidence_basis", passage.evidence_basis),
        ("source_reliability", passage.source_reliability),
        ("limitations_text", passage.limitations_text),
        ("source_id", passage.source_id),
    ]
    lines = []
    for name, value in fields:
        formatted = _format_field_value(value)
        if formatted:
            lines.append(f"{name}: {formatted}")
    return "\n".join(lines)


def passage_store_embedding_texts(store: PassageStore) -> list[str]:
    return [passage_to_embedding_text(passage) for passage in store.passages]


def passage_store_sha256(store: PassageStore) -> str:
    return hashlib.sha256(
        canonical_json_bytes(store.model_dump(mode="json"))
    ).hexdigest()


def validate_passage_index_binding(
    store: PassageStore,
    index: VectorIndex,
    *,
    expected_store_sha256: str | None = None,
) -> None:
    expected_ids = [passage.passage_id for passage in store.passages]
    metadata_ids = index.metadata.get("passage_ids")
    if metadata_ids is not None and metadata_ids != expected_ids:
        raise ValueError("Vector index passage IDs do not match passage store order")
    if expected_store_sha256 is not None:
        if index.metadata.get("passage_store_sha256") != expected_store_sha256:
            raise ValueError("Vector index passage-store digest mismatch")
    if len(index) != len(store.passages):
        raise ValueError("Vector index size does not match passage store size")


def _norm_key(value: str) -> str:
    return str(value).strip().lower()


def _tokenize(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.lower())


class PassageGraphIndex:
    def __init__(self, passages: list[Passage]) -> None:
        self.tool_to_indexes: dict[str, set[int]] = {}
        self.owner_tool_to_indexes: dict[str, set[int]] = {}
        self.category_to_indexes: dict[str, set[int]] = {}
        self.dataset_name_to_indexes: dict[str, set[int]] = {}
        self.scheduling_type_to_indexes: dict[str, set[int]] = {}
        self.action_scope_to_indexes: dict[str, set[int]] = {}
        self.source_id_to_indexes: dict[str, set[int]] = {}
        self.knowledge_kind_to_indexes: dict[str, set[int]] = {}
        for index, passage in enumerate(passages):
            self._add(self.owner_tool_to_indexes, passage.owner_tool, index)
            for tool_id in [passage.owner_tool, *passage.counterpart_tool_ids]:
                self._add(self.tool_to_indexes, tool_id, index)
            self._add(self.category_to_indexes, passage.category, index)
            self._add(self.source_id_to_indexes, passage.source_id, index)
            self._add(self.scheduling_type_to_indexes, passage.scheduling_type, index)
            self._add(self.knowledge_kind_to_indexes, passage.knowledge_kind, index)
            for action_scope in passage.action_scope:
                self._add(self.action_scope_to_indexes, action_scope, index)

    @staticmethod
    def _add(index: dict[str, set[int]], key: str, passage_index: int) -> None:
        normalized = _norm_key(key)
        if normalized:
            index.setdefault(normalized, set()).add(passage_index)

    @staticmethod
    def _union(index: dict[str, set[int]], keys: list[str] | None) -> set[int]:
        candidates: set[int] = set()
        for key in keys or []:
            candidates.update(index.get(_norm_key(key), set()))
        return candidates

    def candidate_indexes(
        self,
        *,
        tool_ids: list[str] | None = None,
        owner_tool_ids: list[str] | None = None,
        categories: list[str] | None = None,
        dataset_names: list[str] | None = None,
        scheduling_types: list[str] | None = None,
        action_scopes: list[str] | None = None,
        source_ids: list[str] | None = None,
        knowledge_kinds: list[str] | None = None,
    ) -> set[int]:
        candidates: set[int] | None = None
        for index, keys in (
            (self.tool_to_indexes, tool_ids),
            (self.owner_tool_to_indexes, owner_tool_ids),
            (self.dataset_name_to_indexes, dataset_names),
            (self.scheduling_type_to_indexes, scheduling_types),
            (self.action_scope_to_indexes, action_scopes),
            (self.source_id_to_indexes, source_ids),
            (self.knowledge_kind_to_indexes, knowledge_kinds),
        ):
            if not keys:
                continue
            matched = self._union(index, keys)
            candidates = matched if candidates is None else candidates & matched
        category_candidates = self._union(self.category_to_indexes, categories)
        if categories:
            return category_candidates if candidates is None else candidates & category_candidates
        if candidates is None:
            return category_candidates
        return candidates


def _has_structured_filter(*groups: list[str] | None) -> bool:
    return any(bool(group) for group in groups)


def project_passage_store_for_purpose_rag(store: PassageStore) -> PassageStore:
    """No-op preserved for backward compatibility with external callers.

    Under the new owner-oriented Passage schema, every entry already carries a
    canonical `knowledge_kind` plus `relation_to_owner`, so no purpose-time
    re-projection is needed. The legacy implementation built copies via
    `_copy_passage`; that helper has been removed.
    """
    return store


def build_passage_vector_index(
    store: PassageStore,
    *,
    batch_size: int | None = None,
    **embedding_kwargs: Any,
) -> VectorIndex:
    index = VectorIndex()
    index.build(passage_store_embedding_texts(store), batch_size=batch_size, **embedding_kwargs)
    return index


def save_passage_vector_index(
    store: PassageStore,
    output_dir: Path,
    *,
    batch_size: int | None = None,
    **embedding_kwargs: Any,
) -> Path:
    index = build_passage_vector_index(store, batch_size=batch_size, **embedding_kwargs)
    config = resolve_embedding_config(
        base_url=embedding_kwargs.get("base_url"),
        api_key=embedding_kwargs.get("api_key"),
        model=embedding_kwargs.get("model"),
    )
    index_path = output_dir / "index.json"
    index.save(
        index_path,
        metadata={
            "provider": config.provider,
            "base_url": config.base_url,
            "model": config.model,
            "passage_ids": [passage.passage_id for passage in store.passages],
            "passage_store_sha256": passage_store_sha256(store),
            "text_fields": [
                "claim_text",
                "owner_tool",
                "counterpart_tool_ids",
                "category",
                "knowledge_kind",
                "relation_to_owner",
                "action_scope",
                "applicability_tags",
                "evidence_basis",
                "source_reliability",
                "limitations_text",
                "source_id",
            ],
        },
    )
    return index_path


class PassageRetriever:
    def __init__(
        self,
        store: PassageStore,
        *,
        index: VectorIndex | None = None,
        **embedding_kwargs: Any,
    ) -> None:
        self._passages = store.passages
        self._graph = PassageGraphIndex(self._passages)
        self._embedding_kwargs = dict(embedding_kwargs)
        self._index = index
        if index is not None:
            validate_passage_index_binding(store, self._index)
        self._lexical_documents = [
            _tokenize(passage_to_embedding_text(passage))
            for passage in self._passages
        ]
        self._document_frequency: Counter[str] = Counter()
        for document in self._lexical_documents:
            self._document_frequency.update(set(document))
        self._average_document_length = (
            sum(len(document) for document in self._lexical_documents)
            / len(self._lexical_documents)
            if self._lexical_documents
            else 0.0
        )

    def _bm25_candidates(
        self,
        query_text: str,
        candidates: set[int] | list[int] | range,
    ) -> list[tuple[int, float]]:
        query_terms = _tokenize(query_text)
        candidate_indexes = sorted(
            {
                index
                for index in candidates
                if 0 <= index < len(self._lexical_documents)
            }
        )
        if not query_terms or not candidate_indexes:
            return []
        corpus_size = max(len(self._lexical_documents), 1)
        average_length = max(self._average_document_length, 1.0)
        scores: list[tuple[int, float]] = []
        for index in candidate_indexes:
            document = self._lexical_documents[index]
            frequencies = Counter(document)
            score = 0.0
            for term in query_terms:
                frequency = frequencies.get(term, 0)
                if frequency == 0:
                    continue
                document_frequency = self._document_frequency.get(term, 0)
                inverse_document_frequency = math.log(
                    1.0
                    + (corpus_size - document_frequency + 0.5)
                    / (document_frequency + 0.5)
                )
                denominator = frequency + _BM25_K1 * (
                    1.0
                    - _BM25_B
                    + _BM25_B * len(document) / average_length
                )
                score += inverse_document_frequency * (
                    frequency * (_BM25_K1 + 1.0) / denominator
                )
            scores.append((index, score))
        scores.sort(
            key=lambda item: (
                -item[1],
                self._passages[item[0]].passage_id,
            )
        )
        return scores

    def _dense_readiness(
        self,
        embedding_kwargs: dict[str, Any],
    ) -> tuple[str, list[str]]:
        if self._index is None or len(self._index) == 0:
            return "INDEX_UNAVAILABLE", ["DENSE_INDEX_UNAVAILABLE"]
        config = resolve_embedding_config(
            base_url=embedding_kwargs.get("base_url"),
            api_key=embedding_kwargs.get("api_key"),
            model=embedding_kwargs.get("model"),
        )
        if not config.api_key:
            return "API_KEY_UNAVAILABLE", ["DENSE_API_KEY_UNAVAILABLE"]
        return "USED", []

    def retrieve_for_action(
        self,
        *,
        category: str,
        owner_tool: str,
        action_scope: Literal["PLAN_COMPOSITION"] = "PLAN_COMPOSITION",
        top_k: int = 3,
        **embedding_kwargs: Any,
    ) -> PassageRetrievalResult:
        """Retrieve one exact DACE cell with BM25 plus optional dense RRF."""
        query_text = f"{category} {owner_tool} {action_scope}"
        candidates = self._graph.candidate_indexes(
            owner_tool_ids=[owner_tool],
            categories=[category, GLOBAL_CATEGORY],
            action_scopes=[action_scope],
        )
        lexical_hits = self._bm25_candidates(query_text, candidates)
        merged_embedding_kwargs = {
            **self._embedding_kwargs,
            **embedding_kwargs,
        }
        dense_status, reason_codes = self._dense_readiness(
            merged_embedding_kwargs
        )
        dense_hits: list[tuple[int, float]] = []
        if candidates and dense_status == "USED":
            assert self._index is not None
            try:
                dense_hits = self._index.query_candidates(
                    query_text,
                    candidates,
                    top_k=len(candidates),
                    **merged_embedding_kwargs,
                )
            except (IndexError, OSError, RuntimeError, ValueError):
                dense_status = "QUERY_FAILED"
                reason_codes = ["DENSE_QUERY_FAILED"]

        if dense_status == "USED":
            fused_scores: dict[int, float] = {}
            for rank, (index, _score) in enumerate(lexical_hits, start=1):
                fused_scores[index] = fused_scores.get(index, 0.0) + 1.0 / (
                    _RRF_K + rank
                )
            for rank, (index, _score) in enumerate(dense_hits, start=1):
                fused_scores[index] = fused_scores.get(index, 0.0) + 1.0 / (
                    _RRF_K + rank
                )
            ranked_indexes = sorted(
                fused_scores,
                key=lambda index: (
                    -fused_scores[index],
                    self._passages[index].passage_id,
                ),
            )
            mode = "HYBRID_BM25_DENSE"
            fusion_method = "reciprocal_rank_fusion"
        else:
            ranked_indexes = [index for index, _score in lexical_hits]
            mode = "LEXICAL_BM25_FALLBACK"
            fusion_method = "lexical_bm25"

        if not candidates:
            reason_codes = [*reason_codes, "NO_STRUCTURED_RETRIEVAL_CANDIDATES"]
            if dense_status == "USED":
                dense_status = "NOT_ATTEMPTED"
                mode = "LEXICAL_BM25_FALLBACK"
                fusion_method = "lexical_bm25"

        passages = [
            self._passages[index]
            for index in ranked_indexes[: max(top_k, 0)]
        ]
        diagnostic = PassageRetrievalDiagnostic(
            category=category,
            owner_tool=owner_tool,
            action_scope=action_scope,
            query_text=query_text,
            mode=mode,
            dense_status=dense_status,
            reason_codes=reason_codes,
            lexical_hit_count=len(lexical_hits),
            dense_hit_count=len(dense_hits),
            returned_passage_ids=[
                passage.passage_id for passage in passages
            ],
            fusion_method=fusion_method,
        )
        return PassageRetrievalResult(
            passages=passages,
            diagnostic=diagnostic,
        )

    def search_text(
        self,
        query_text: str,
        top_k: int = 3,
        **embedding_kwargs: Any,
    ) -> list[tuple[Passage, float]]:
        if not query_text.strip():
            return []
        merged_embedding_kwargs = {
            **self._embedding_kwargs,
            **embedding_kwargs,
        }
        dense_status, _reasons = self._dense_readiness(
            merged_embedding_kwargs
        )
        if dense_status != "USED":
            hits = self._bm25_candidates(
                query_text,
                range(len(self._passages)),
            )[:top_k]
        else:
            assert self._index is not None
            try:
                hits = self._index.query(
                    query_text,
                    top_k=top_k,
                    **merged_embedding_kwargs,
                )
            except (IndexError, OSError, RuntimeError, ValueError):
                hits = self._bm25_candidates(
                    query_text,
                    range(len(self._passages)),
                )[:top_k]
        return [(self._passages[i], score) for i, score in hits]

    def _fallback_candidates_without_knowledge_kind(
        self,
        *,
        tool_ids: list[str] | None = None,
        categories: list[str] | None = None,
        dataset_names: list[str] | None = None,
        scheduling_types: list[str] | None = None,
        source_ids: list[str] | None = None,
        knowledge_kinds: list[str] | None = None,
    ) -> set[int] | range | None:
        if not knowledge_kinds:
            return None
        candidates = self._graph.candidate_indexes(
            tool_ids=tool_ids,
            categories=categories,
            dataset_names=dataset_names,
            scheduling_types=scheduling_types,
            source_ids=source_ids,
        )
        if candidates:
            return candidates
        if _has_structured_filter(tool_ids, categories, dataset_names, scheduling_types, source_ids):
            return None
        return range(len(self._passages))

    def search_structured(
        self,
        query_text: str,
        *,
        tool_ids: list[str] | None = None,
        categories: list[str] | None = None,
        dataset_names: list[str] | None = None,
        scheduling_types: list[str] | None = None,
        source_ids: list[str] | None = None,
        knowledge_kinds: list[str] | None = None,
        top_k: int = 3,
        candidate_multiplier: int = 8,
        **embedding_kwargs: Any,
    ) -> list[tuple[Passage, float]]:
        if not query_text.strip():
            return []
        candidates = self._graph.candidate_indexes(
            tool_ids=tool_ids,
            categories=categories,
            dataset_names=dataset_names,
            scheduling_types=scheduling_types,
            source_ids=source_ids,
            knowledge_kinds=knowledge_kinds,
        )
        if not candidates:
            fallback_candidates = self._fallback_candidates_without_knowledge_kind(
                tool_ids=tool_ids,
                categories=categories,
                dataset_names=dataset_names,
                scheduling_types=scheduling_types,
                source_ids=source_ids,
                knowledge_kinds=knowledge_kinds,
            )
            if fallback_candidates is None:
                if _has_structured_filter(
                    tool_ids,
                    categories,
                    dataset_names,
                    scheduling_types,
                    source_ids,
                    knowledge_kinds,
                ):
                    return []
                return self.search_text(query_text, top_k=top_k, **embedding_kwargs)
            candidates = fallback_candidates
        merged_embedding_kwargs = {
            **self._embedding_kwargs,
            **embedding_kwargs,
        }
        dense_status, _reasons = self._dense_readiness(
            merged_embedding_kwargs
        )
        if dense_status != "USED":
            hits = self._bm25_candidates(query_text, candidates)
            return [
                (self._passages[index], score)
                for index, score in hits[:top_k]
            ]
        candidate_limit = max(top_k, top_k * max(candidate_multiplier, 1))
        assert self._index is not None
        try:
            hits = self._index.query_candidates(
                query_text,
                candidates,
                top_k=min(candidate_limit, len(candidates)),
                **merged_embedding_kwargs,
            )
        except (IndexError, OSError, RuntimeError, ValueError):
            hits = self._bm25_candidates(query_text, candidates)
        return [(self._passages[i], score) for i, score in hits[:top_k]]

    def batch_search_structured(
        self,
        queries: list[dict[str, Any]],
        **embedding_kwargs: Any,
    ) -> list[list[tuple[Passage, float]]]:
        if not queries:
            return []
        merged_embedding_kwargs = {
            **self._embedding_kwargs,
            **embedding_kwargs,
        }
        dense_status, _reasons = self._dense_readiness(
            merged_embedding_kwargs
        )
        if dense_status != "USED":
            return [
                self.search_structured(
                    q.get("query_text", ""),
                    tool_ids=q.get("tool_ids"),
                    categories=q.get("categories"),
                    dataset_names=q.get("dataset_names"),
                    scheduling_types=q.get("scheduling_types"),
                    source_ids=q.get("source_ids"),
                    knowledge_kinds=q.get("knowledge_kinds"),
                    top_k=q.get("top_k", 3),
                    candidate_multiplier=q.get("candidate_multiplier", 8),
                    **merged_embedding_kwargs,
                )
                for q in queries
            ]
        batch_inputs: list[tuple[str, set[int] | list[int] | range, int]] = []
        query_indexes: list[int] = []
        fallback_results: dict[int, list[tuple[Passage, float]]] = {}
        for qi, q in enumerate(queries):
            query_text = q.get("query_text", "")
            top_k = q.get("top_k", 3)
            candidate_multiplier = q.get("candidate_multiplier", 8)
            if not query_text.strip():
                fallback_results[qi] = []
                continue
            candidates = self._graph.candidate_indexes(
                tool_ids=q.get("tool_ids"),
                categories=q.get("categories"),
                dataset_names=q.get("dataset_names"),
                scheduling_types=q.get("scheduling_types"),
                source_ids=q.get("source_ids"),
                knowledge_kinds=q.get("knowledge_kinds"),
            )
            if not candidates:
                fallback_candidates = self._fallback_candidates_without_knowledge_kind(
                    tool_ids=q.get("tool_ids"),
                    categories=q.get("categories"),
                    dataset_names=q.get("dataset_names"),
                    scheduling_types=q.get("scheduling_types"),
                    source_ids=q.get("source_ids"),
                    knowledge_kinds=q.get("knowledge_kinds"),
                )
                if fallback_candidates is None:
                    has_filter = _has_structured_filter(
                        q.get("tool_ids"), q.get("categories"), q.get("dataset_names"),
                        q.get("scheduling_types"), q.get("source_ids"), q.get("knowledge_kinds"),
                    )
                    if has_filter:
                        fallback_results[qi] = []
                        continue
                    candidates = range(len(self._passages))
                else:
                    candidates = fallback_candidates
            candidate_limit = max(top_k, top_k * max(candidate_multiplier, 1))
            batch_inputs.append((query_text, candidates, min(candidate_limit, len(candidates))))
            query_indexes.append(qi)
        if batch_inputs:
            assert self._index is not None
            try:
                batch_hits = self._index.batch_query_candidates(
                    batch_inputs,
                    **merged_embedding_kwargs,
                )
            except (IndexError, OSError, RuntimeError, ValueError):
                return [
                    self.search_structured(
                        q.get("query_text", ""),
                        tool_ids=q.get("tool_ids"),
                        categories=q.get("categories"),
                        dataset_names=q.get("dataset_names"),
                        scheduling_types=q.get("scheduling_types"),
                        source_ids=q.get("source_ids"),
                        knowledge_kinds=q.get("knowledge_kinds"),
                        top_k=q.get("top_k", 3),
                        candidate_multiplier=q.get("candidate_multiplier", 8),
                        **merged_embedding_kwargs,
                    )
                    for q in queries
                ]
        else:
            batch_hits = []
        results: list[list[tuple[Passage, float]]] = [[] for _ in queries]
        for qi in range(len(queries)):
            if qi in fallback_results:
                results[qi] = fallback_results[qi]
        for bi, qi in enumerate(query_indexes):
            top_k = queries[qi].get("top_k", 3)
            results[qi] = [(self._passages[i], score) for i, score in batch_hits[bi][:top_k]]
        return results

    def retrieve(
        self,
        tool_ids: list[str],
        categories: list[str],
        top_k: int = 3,
        **embedding_kwargs: Any,
    ) -> list[Passage]:
        passages: list[Passage] = []
        seen: set[str] = set()
        for category in categories:
            for owner_tool in tool_ids:
                result = self.retrieve_for_action(
                    category=category,
                    owner_tool=owner_tool,
                    top_k=top_k,
                    **embedding_kwargs,
                )
                for passage in result.passages:
                    if passage.passage_id in seen:
                        continue
                    passages.append(passage)
                    seen.add(passage.passage_id)
        return passages[:top_k]
