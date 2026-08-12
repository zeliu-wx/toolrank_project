"""DACE-RAG: build the Stage 2 action/evidence matrix.

Stage 1 has already selected an immutable primary tool.  This module only asks
whether a count-qualified complementary tool should be added for a required
category.
"""

from __future__ import annotations

from collections.abc import Iterable

from toolrank.action_contract import action_id_for
from toolrank.assignment_evidence import (
    complement_count_eligible,
    complement_strength_against_primary,
)
from toolrank.ownership_evidence import category_ownership_panel, rcov_evidence_id
from toolrank.passage_store import PassageRetriever
from toolrank.plan_runtime import (
    estimated_budget,
    plan_constraint_reasons,
    planning_runtime_minutes,
    within_budget,
)
from toolrank.schemas_v2 import (
    ActionByEvidenceMatrix,
    ActionEvidence,
    BudgetProfile,
    CandidateAction,
    EvidenceCard,
    EvidenceCardValue,
    EvidenceRef,
    MatrixEvidenceApplicability,
    MatrixRuntimeEvidence,
    MatrixTargetConstraints,
    Passage,
    PassageRetrievalDiagnostic,
    RelevantToolCategoryRow,
    Stage1BenchmarkEvidence,
    Stage1EvidenceLineage,
    Stage1Status,
    Stage1ToolEvidence,
    Stage2EvidenceContext,
)
from toolrank.solc_range import version_in_range


__all__ = [
    "build_action_evidence_matrix",
    "project_performance_observation_links",
]

_SLOTS = ("FOR", "AGAINST", "COMPARE", "GAP")


def _empty_evidence() -> dict[str, list[ActionEvidence]]:
    return {slot: [] for slot in _SLOTS}


def _append_claim(
    evidence: dict[str, list[ActionEvidence]],
    slot: str,
    claim: str,
    refs: Iterable[str],
) -> None:
    evidence[slot].append(
        ActionEvidence(claim=claim, evidence_refs=list(dict.fromkeys(refs)))
    )


def _stage1_evidence(context: Stage2EvidenceContext) -> Stage1EvidenceLineage:
    nominal = {
        score.tool: score
        for score in context.stage1.score_panel.nominal_scores
    }
    rows_by_tool: dict[str, list[Stage1BenchmarkEvidence]] = {}
    for row in context.stage1.score_panel.benchmark_scores:
        rows_by_tool.setdefault(row.tool, []).append(
            Stage1BenchmarkEvidence(
                evaluation_id=row.evaluation_id,
                tool=row.tool,
                benchmark_id=row.benchmark_id,
                source_id=row.source_id,
                dataset_id=row.dataset_id,
                w_D=row.weight,
                s_t_D=row.score,
                recall=row.recall,
                precision=row.precision,
                recall_rank=row.recall_rank,
                precision_rank=row.precision_rank,
            )
        )

    primary = context.stage1.primary_selection.primary_tool
    assert primary is not None
    tool_ids = list(
        dict.fromkeys(
            [
                primary,
                *[
                    entry.tool
                    for entry in context.stage1.tool_table
                    if entry.feasible
                ],
            ]
        )
    )
    tools: dict[str, Stage1ToolEvidence] = {}
    for tool in tool_ids:
        score = nominal.get(tool)
        tools[tool] = Stage1ToolEvidence(
            tool=tool,
            S_t=score.S_scene if score is not None else None,
            support_mass=score.support_mass if score is not None else 0.0,
            benchmark_evaluations=rows_by_tool.get(tool, []),
        )
    return Stage1EvidenceLineage(
        primary_tool=primary,
        benchmark_weights=dict(context.stage1.score_panel.benchmark_weights),
        tools=tools,
    )


def _evaluation_index(
    lineage: Stage1EvidenceLineage,
) -> dict[str, Stage1BenchmarkEvidence]:
    return {
        row.evaluation_id: row
        for tool in lineage.tools.values()
        for row in tool.benchmark_evaluations
    }


def _evaluation_links(
    lineage: Stage1EvidenceLineage,
    *,
    tool: str,
    source_ids: Iterable[str] = (),
    explicit_ids: list[str] | None = None,
) -> list[str]:
    rows = _evaluation_index(lineage)
    if explicit_ids is not None:
        unique_ids = list(dict.fromkeys(explicit_ids))
        for evaluation_id in unique_ids:
            row = rows.get(evaluation_id)
            if row is None:
                raise ValueError(
                    f"explicit Stage 1 evaluation link not found: {evaluation_id}"
                )
            if row.tool != tool:
                raise ValueError(
                    "explicit Stage 1 evaluation link belongs to another tool: "
                    f"{evaluation_id}"
                )
        return unique_ids
    exact_sources = set(source_ids)
    return [
        row.evaluation_id
        for row in rows.values()
        if row.tool == tool and row.source_id in exact_sources
    ]


def project_performance_observation_links(
    lineage: Stage1EvidenceLineage,
    passage: Passage,
) -> list[str]:
    """Project persistent observation refs only through rows in this run.

    The persistent IDs are never converted with ``stage1_evaluation_id``.
    Instead, this function selects an already-existing current-lineage row by
    exact tool, Performance-KB source, and dataset identity.
    """
    rows = _evaluation_index(lineage)
    projected: list[str] = []
    for reference in passage.performance_observation_refs:
        for row in rows.values():
            if (
                row.tool == reference.tool == passage.owner_tool
                and row.source_id == reference.source_id
                and row.dataset_id == reference.dataset_name
            ):
                if row.evaluation_id not in projected:
                    projected.append(row.evaluation_id)
    return projected


def _link_weight(
    lineage: Stage1EvidenceLineage,
    linked_evaluation_ids: list[str],
) -> float | None:
    if len(linked_evaluation_ids) != 1:
        return None
    return _evaluation_index(lineage)[linked_evaluation_ids[0]].w_D


def _stage1_score_cards(
    context: Stage2EvidenceContext,
    lineage: Stage1EvidenceLineage,
) -> list[EvidenceCard]:
    links_by_tool = {
        tool: [row.evaluation_id for row in evidence.benchmark_evaluations]
        for tool, evidence in lineage.tools.items()
    }
    return [
        EvidenceCard(
            evidence_id=f"ev_scene_{score.tool}",
            source=EvidenceRef(
                evidence_id=f"ev_scene_{score.tool}",
                source_type="stage1_field",
                field_path="score_panel.nominal_scores",
                extraction_confidence="high",
            ),
            evidence_type="stage1_score",
            tool=score.tool,
            metric_semantics="qualitative",
            value=EvidenceCardValue(value=score.S_scene),
            scope={
                "rank": score.rank,
                "support_mass": score.support_mass,
                "preferred_metric_value": score.preferred_metric_value,
            },
            aggregation_level="scene_level",
            decision_role="support",
            source_reliability="benchmark",
            extraction_confidence="high",
            linked_evaluation_ids=links_by_tool.get(score.tool, []),
            benchmark_relevance_weight=_link_weight(
                lineage,
                links_by_tool.get(score.tool, []),
            ),
        )
        for score in context.stage1.score_panel.nominal_scores
    ]


def _recall_cards(
    context: Stage2EvidenceContext,
    lineage: Stage1EvidenceLineage,
) -> list[EvidenceCard]:
    cards: list[EvidenceCard] = []
    for row in context.recall_coverage.matrix:
        evidence_id = rcov_evidence_id(row.tool, row.category)
        eligible = complement_count_eligible(rate=row.R_hat, n_eff=row.n_eff)
        source_ids = [
            item.source_id
            for item in context.performance_db_view
            if item.tool == row.tool and item.category == row.category
        ]
        links = _evaluation_links(
            lineage,
            tool=row.tool,
            source_ids=source_ids,
        )
        cards.append(
            EvidenceCard(
                evidence_id=evidence_id,
                source=EvidenceRef(
                    evidence_id=evidence_id,
                    source_type="stage2_field",
                    field_path="recall_coverage.matrix",
                    extraction_confidence="high",
                ),
                evidence_type="per_category_detected_total",
                tool=row.tool,
                category=row.category,
                metric_semantics="recall_side_detection_rate",
                value=EvidenceCardValue(
                    detected=row.detected,
                    total=row.total,
                    rate=row.R_hat,
                    n_eff=row.n_eff,
                ),
                scope={"support_level": row.support_level},
                limitations=[
                    "detected/total is recall-side evidence and must not be read as precision"
                ],
                extraction_confidence="high",
                aggregation_level="category_level",
                decision_role="support" if eligible else "gap",
                source_reliability="benchmark",
                linked_evaluation_ids=links,
                benchmark_relevance_weight=_link_weight(lineage, links),
            )
        )
    return cards


def _external_performance_cards(
    context: Stage2EvidenceContext,
    lineage: Stage1EvidenceLineage,
) -> list[EvidenceCard]:
    cards: list[EvidenceCard] = []
    for row in context.performance_db_view:
        links = _evaluation_links(
            lineage,
            tool=row.tool,
            source_ids=[row.source_id],
        )
        cards.append(
            EvidenceCard(
                evidence_id=row.evidence_id,
                source=EvidenceRef(
                    evidence_id=row.evidence_id,
                    source_type="stage2_field",
                    field_path="performance_db_view",
                    paper_id=row.source_id,
                    extraction_confidence="high",
                ),
                evidence_type="per_category_detected_total",
                tool=row.tool,
                category=row.category,
                metric_semantics="recall_side_detection_rate",
                value=EvidenceCardValue(
                    detected=row.detected,
                    total=row.total,
                    rate=row.R_hat,
                    n_eff=row.n_eff,
                ),
                scope={"source_id": row.source_id, "dataset_name": row.dataset_name},
                limitations=["external benchmark evidence is contextual, not a local eligibility gate"],
                extraction_confidence="high",
                aggregation_level="dataset_level",
                decision_role="compare",
                source_reliability="benchmark",
                linked_evaluation_ids=links,
                benchmark_relevance_weight=_link_weight(lineage, links),
            )
        )
    return cards


def _overall_metric_cards(
    context: Stage2EvidenceContext,
    lineage: Stage1EvidenceLineage,
) -> list[EvidenceCard]:
    cards: list[EvidenceCard] = []
    for row in context.tool_overall_metrics:
        metrics = (
            ("historical_precision", row.precision),
            ("historical_recall", row.recall),
            ("historical_f1", row.f1),
        )
        semantic, value = next(((name, value) for name, value in metrics if value is not None), (None, None))
        if semantic is None:
            continue
        links = _evaluation_links(
            lineage,
            tool=row.tool,
            source_ids=[row.source_id],
        )
        cards.append(
            EvidenceCard(
                evidence_id=row.evidence_id,
                source=EvidenceRef(
                    evidence_id=row.evidence_id,
                    source_type="stage2_field",
                    field_path="tool_overall_metrics",
                    paper_id=row.source_id,
                    extraction_confidence="high",
                ),
                evidence_type="scene_metric",
                tool=row.tool,
                metric_semantics=semantic,
                value=EvidenceCardValue(value=value),
                scope={"source_id": row.source_id, "dataset_name": row.dataset_name},
                limitations=["overall metrics are not category-specific"],
                aggregation_level="dataset_level",
                decision_role="caveat" if semantic == "historical_precision" else "compare",
                source_reliability="benchmark",
                extraction_confidence="high",
                linked_evaluation_ids=links,
                benchmark_relevance_weight=_link_weight(lineage, links),
            )
        )
    return cards


def _runtime_cards(context: Stage2EvidenceContext) -> list[EvidenceCard]:
    cards: list[EvidenceCard] = []
    for entry in context.stage1.tool_table:
        evidence_id = f"ev_runtime_{entry.tool}"
        provenance = entry.tool_cost.runtime_provenance
        assessment = entry.tool_cost.runtime_evidence
        campaign = entry.tool_cost.fuzz_campaign_budget
        if provenance is not None:
            source = EvidenceRef(
                evidence_id=evidence_id,
                source_type="paper_table_cell",
                field_path=(
                    "tool_performance_data.metrics."
                    f"{provenance.selected_metric_field}"
                ),
                paper_id=provenance.selected_source_id,
                extraction_confidence="high",
            )
            scope = {
                "feasible": entry.feasible,
                "alert_risk": entry.tool_cost.alert_risk,
                "dataset_name": provenance.selected_dataset_name,
                "runtime_estimation_method": provenance.method,
                "selected_runtime_seconds": provenance.selected_runtime_seconds,
                "selected_source_runtime_seconds": provenance.selected_source_runtime_seconds,
                "candidate_source_ids": provenance.candidate_source_ids,
                "target_compiler_bucket": provenance.target_compiler_bucket,
                "target_loc_bucket": provenance.target_loc_bucket,
                "support_mass": provenance.support_mass,
                "support_threshold": provenance.support_threshold,
                "quantile": provenance.quantile,
                "runtime_basis": provenance.runtime_basis,
                "runtime_candidates": [
                    candidate.model_dump(mode="json")
                    for candidate in provenance.candidates
                ],
                "runtime_unit": "minutes",
                "source_runtime_unit": "seconds",
            }
            limitations = list(provenance.limitations)
            aggregation_level = "dataset_level"
            source_reliability = "benchmark"
        else:
            source = EvidenceRef(
                evidence_id=evidence_id,
                source_type="benchmark_metadata",
                field_path="performance_db.runtime_rows",
                extraction_confidence="high",
            )
            scope = {
                "feasible": entry.feasible,
                "alert_risk": entry.tool_cost.alert_risk,
                "runtime_unit": "minutes",
                "runtime_evidence_status": assessment.status if assessment else "NO_RUNTIME_ROWS",
                "target_compiler_bucket": assessment.target_compiler_bucket if assessment else None,
                "target_loc_bucket": assessment.target_loc_bucket if assessment else None,
                "support_mass": assessment.support_mass if assessment else 0.0,
                "support_threshold": assessment.support_threshold if assessment else 0.2,
                "quantile": assessment.quantile if assessment else 0.9,
                "runtime_candidates": [
                    candidate.model_dump(mode="json")
                    for candidate in (assessment.candidates if assessment else [])
                ],
            }
            limitations = (
                list(assessment.limitations)
                if assessment is not None
                else ["NO_RUNTIME_ROWS"]
            )
            aggregation_level = "dataset_level"
            source_reliability = "benchmark"
        literature_summaries = (
            assessment.descriptive_literature_summaries
            if assessment is not None
            else []
        )
        if literature_summaries:
            scope["descriptive_literature_summaries"] = [
                summary.model_dump(mode="json") for summary in literature_summaries
            ]
            limitations = list(
                dict.fromkeys(
                    [
                        *limitations,
                        "LITERATURE_SUMMARY_DESCRIPTIVE_NOT_SCHEDULABLE",
                    ]
                )
            )
        scope["historical_completion_runtime_minutes"] = (
            entry.tool_cost.expected_runtime_minutes
        )
        scope["runtime_semantics"] = "historical_completion_estimate"
        if campaign is None:
            scope["planning_runtime_minutes"] = planning_runtime_minutes(entry)
        cards.append(
            EvidenceCard(
                evidence_id=evidence_id,
                source=source,
                evidence_type="runtime_cost",
                tool=entry.tool,
                metric_semantics="runtime",
                value=EvidenceCardValue(value=entry.tool_cost.expected_runtime_minutes),
                scope=scope,
                limitations=limitations,
                aggregation_level=aggregation_level,
                decision_role="constraint",
                source_reliability=source_reliability,
                extraction_confidence="high",
            )
        )
        if campaign is not None:
            campaign_evidence_id = f"ev_fuzz_campaign_{entry.tool}"
            planning_minutes = planning_runtime_minutes(entry)
            cards.append(
                EvidenceCard(
                    evidence_id=campaign_evidence_id,
                    source=EvidenceRef(
                        evidence_id=campaign_evidence_id,
                        source_type="stage2_field",
                        field_path=(
                            "budget_profile.execution_schedule."
                            "tool_timeout_seconds"
                        ),
                        extraction_confidence="high",
                    ),
                    evidence_type="runtime_cost",
                    tool=entry.tool,
                    metric_semantics="runtime",
                    value=EvidenceCardValue(value=planning_minutes),
                    scope={
                        "fuzz_campaign_budget": campaign.model_dump(mode="json"),
                        "planning_runtime_minutes": planning_minutes,
                        "planning_runtime_source": campaign.method,
                        "runtime_semantics": campaign.runtime_semantics,
                        "runtime_unit": "minutes",
                        "source_runtime_unit": "seconds",
                    },
                    limitations=[
                        "FUZZ_CAMPAIGN_ALLOCATION_NOT_COMPLETION_ESTIMATE"
                    ],
                    aggregation_level="tool_level",
                    decision_role="constraint",
                    source_reliability="artifact",
                    extraction_confidence="high",
                )
            )
    return cards


def _target_features(context: Stage2EvidenceContext) -> dict:
    raw = context.stage1.target_contract
    features = raw.get("features") if isinstance(raw, dict) else None
    return features if isinstance(features, dict) else {}


def _scale_bucket(loc_total: object) -> str | None:
    if not isinstance(loc_total, (int, float)):
        return None
    if loc_total <= 500:
        return "small"
    if loc_total <= 5000:
        return "medium"
    return "large"


def _passage_applies(context: Stage2EvidenceContext, passage: Passage) -> bool:
    """Conservatively verify machine-readable premises for hard exclusions."""
    features = _target_features(context)
    checked = False
    for tag in passage.applicability_tags:
        prefix, value = tag.split(":", 1)
        value = value.strip().lower()
        if prefix == "solc":
            checked = True
            version = features.get("primary_solidity_version")
            if not isinstance(version, str) or not version_in_range(version, value):
                return False
        elif prefix == "scale":
            checked = True
            if _scale_bucket(features.get("loc_total")) != value:
                return False
        elif prefix == "input":
            checked = True
            target_input = features.get("input_mode") or features.get("input_type")
            if not isinstance(target_input, str) or target_input.strip().lower() != value:
                return False
    return checked or not passage.applicability_tags or passage.source_reliability == "manual_curated"


def _passage_role(passage: Passage) -> str:
    if passage.relation_to_owner == "owner_ineligible":
        return "constraint"
    if passage.relation_to_owner in {"opposes_owner", "owner_weaker"}:
        return "oppose"
    if passage.relation_to_owner == "evidence_gap":
        return "gap"
    if passage.relation_to_owner in {"owner_stronger", "owner_complements"}:
        return "compare"
    return "support"


def _passage_reliability(passage: Passage) -> str:
    return {
        "manual_curated": "manual_curated",
        "peer_reviewed": "peer_reviewed",
        "artifact": "artifact",
        "official_tool_doc": "documentation",
        "maintainer_issue": "documentation",
        "internal_eval": "experiment_log",
    }.get(passage.source_reliability, "unknown")


def _rag_card(
    context: Stage2EvidenceContext,
    passage: Passage,
    lineage: Stage1EvidenceLineage,
) -> EvidenceCard:
    links = (
        project_performance_observation_links(lineage, passage)
        if passage.performance_observation_refs
        else _evaluation_links(
            lineage,
            tool=passage.owner_tool,
            source_ids=[passage.source_id],
            explicit_ids=passage.linked_evaluation_ids,
        )
    )
    return EvidenceCard(
        evidence_id=passage.passage_id,
        source=EvidenceRef(
            evidence_id=passage.passage_id,
            source_type="rag_passage",
            paper_id=passage.source_id,
            extraction_confidence="high",
        ),
        evidence_type="rag_passage",
        tool=passage.owner_tool,
        category=passage.category,
        metric_semantics="qualitative",
        scope={
            "source_id": passage.source_id,
            "knowledge_kind": passage.knowledge_kind,
            "relation_to_owner": passage.relation_to_owner,
            "evidence_basis": passage.evidence_basis,
            "action_scope": passage.action_scope,
            "applicability_tags": passage.applicability_tags,
            "counterpart_tool_ids": passage.counterpart_tool_ids,
            "applies_to_target": _passage_applies(context, passage),
            "claim_text": passage.claim_text,
        },
        limitations=[passage.limitations_text] if passage.limitations_text else [],
        aggregation_level="paper_level",
        decision_role=_passage_role(passage),
        source_reliability=_passage_reliability(passage),
        extraction_confidence="high",
        linked_evaluation_ids=links,
        benchmark_relevance_weight=_link_weight(lineage, links),
    )


def _retrieved_cards(
    context: Stage2EvidenceContext,
    retriever: PassageRetriever | None,
    lineage: Stage1EvidenceLineage,
) -> tuple[list[EvidenceCard], list[PassageRetrievalDiagnostic]]:
    if not context.required_categories:
        return [], []
    tools = list(lineage.tools)
    passages: list[Passage] = []
    diagnostics: list[PassageRetrievalDiagnostic] = []
    for category in dict.fromkeys(context.required_categories):
        for tool in tools:
            if retriever is None:
                diagnostics.append(
                    PassageRetrievalDiagnostic(
                        category=category,
                        owner_tool=tool,
                        query_text=f"{category} {tool} PLAN_COMPOSITION",
                        mode="RETRIEVER_UNAVAILABLE",
                        dense_status="NOT_ATTEMPTED",
                        reason_codes=["PASSAGE_RETRIEVER_UNAVAILABLE"],
                        fusion_method="none",
                    )
                )
                continue
            try:
                retrieve_for_action = getattr(
                    retriever,
                    "retrieve_for_action",
                    None,
                )
                if callable(retrieve_for_action):
                    result = retrieve_for_action(
                        category=category,
                        owner_tool=tool,
                        action_scope="PLAN_COMPOSITION",
                        top_k=8,
                    )
                    cell_passages = list(result.passages)
                    diagnostics.append(result.diagnostic)
                else:
                    cell_passages = list(
                        retriever.retrieve(
                            [tool],
                            [category, "__GLOBAL__"],
                            top_k=8,
                        )
                    )
                    diagnostics.append(
                        PassageRetrievalDiagnostic(
                            category=category,
                            owner_tool=tool,
                            query_text=f"{category} {tool} PLAN_COMPOSITION",
                            mode="LEXICAL_BM25_FALLBACK",
                            dense_status="NOT_ATTEMPTED",
                            reason_codes=["LEGACY_RETRIEVER_INTERFACE"],
                            lexical_hit_count=len(cell_passages),
                            returned_passage_ids=[
                                passage.passage_id
                                for passage in cell_passages
                            ],
                            fusion_method="lexical_bm25",
                        )
                    )
            except (AttributeError, RuntimeError, ValueError):
                diagnostics.append(
                    PassageRetrievalDiagnostic(
                        category=category,
                        owner_tool=tool,
                        query_text=f"{category} {tool} PLAN_COMPOSITION",
                        mode="RETRIEVER_UNAVAILABLE",
                        dense_status="QUERY_FAILED",
                        reason_codes=["PASSAGE_RETRIEVAL_QUERY_FAILED"],
                        fusion_method="none",
                    )
                )
                continue
            passages.extend(
                passage
                for passage in cell_passages
                if passage.owner_tool == tool
                and "PLAN_COMPOSITION" in passage.action_scope
                and passage.category in {category, "__GLOBAL__"}
            )
    cards: list[EvidenceCard] = []
    seen: set[str] = set()
    for passage in passages:
        if passage.passage_id in seen or passage.owner_tool not in tools:
            continue
        if "PLAN_COMPOSITION" not in passage.action_scope:
            continue
        if passage.category not in {*context.required_categories, "__GLOBAL__"}:
            continue
        cards.append(_rag_card(context, passage, lineage))
        seen.add(passage.passage_id)
    return cards, diagnostics


def _attach_passage_ids(
    lineage: Stage1EvidenceLineage,
    cards: list[EvidenceCard],
) -> Stage1EvidenceLineage:
    passage_ids: dict[str, list[str]] = {}
    for card in cards:
        if card.evidence_type != "rag_passage":
            continue
        for evaluation_id in card.linked_evaluation_ids:
            passage_ids.setdefault(evaluation_id, []).append(card.evidence_id)

    tools = {
        tool_id: tool.model_copy(
            update={
                "benchmark_evaluations": [
                    row.model_copy(
                        update={
                            "linked_passage_ids": list(
                                dict.fromkeys(passage_ids.get(row.evaluation_id, []))
                            )
                        }
                    )
                    for row in tool.benchmark_evaluations
                ]
            }
        )
        for tool_id, tool in lineage.tools.items()
    }
    return lineage.model_copy(update={"tools": tools})


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _target_constraints(context: Stage2EvidenceContext) -> MatrixTargetConstraints:
    features = _target_features(context)
    return MatrixTargetConstraints(
        primary_solidity_version=(
            features.get("primary_solidity_version")
            if isinstance(features.get("primary_solidity_version"), str)
            else None
        ),
        solidity_version_constraints=_string_list(
            features.get("solidity_version_constraints")
        ),
        gower_solc_bucket=(
            features.get("gower_solc_bucket")
            if isinstance(features.get("gower_solc_bucket"), str)
            else None
        ),
        present_input_kinds=_string_list(features.get("present_input_kinds")),
        source_kind=(
            features.get("source_kind")
            if isinstance(features.get("source_kind"), str)
            else None
        ),
        loc_total=(
            features.get("loc_total")
            if isinstance(features.get("loc_total"), int)
            and features.get("loc_total") >= 0
            else None
        ),
        execution_input_count=(
            features.get("execution_input_count")
            if isinstance(features.get("execution_input_count"), int)
            and features.get("execution_input_count") >= 0
            else None
        ),
    )


def _matrix_runtime_evidence(entry) -> MatrixRuntimeEvidence:
    provenance = entry.tool_cost.runtime_provenance
    assessment = entry.tool_cost.runtime_evidence
    campaign = entry.tool_cost.fuzz_campaign_budget
    limitations = list(
        dict.fromkeys(
            [
                *(provenance.limitations if provenance is not None else []),
                *(assessment.limitations if assessment is not None else []),
                *(
                    ["FUZZ_CAMPAIGN_ALLOCATION_NOT_COMPLETION_ESTIMATE"]
                    if campaign is not None
                    else []
                ),
            ]
        )
    )
    return MatrixRuntimeEvidence(
        expected_runtime_minutes=entry.tool_cost.expected_runtime_minutes,
        planning_runtime_minutes=planning_runtime_minutes(entry),
        runtime_provenance=provenance,
        runtime_evidence=assessment,
        fuzz_campaign_budget=campaign,
        limitations=limitations,
    )


def _evidence_slot(card: EvidenceCard) -> str:
    if card.decision_role == "support":
        return "FOR"
    if card.decision_role in {"oppose", "constraint", "caveat"}:
        return "AGAINST"
    if card.decision_role == "compare":
        return "COMPARE"
    return "GAP"


def _relevant_matrix_rows(
    context: Stage2EvidenceContext,
    lineage: Stage1EvidenceLineage,
    cards: list[EvidenceCard],
    ownership: dict,
) -> list[RelevantToolCategoryRow]:
    primary = lineage.primary_tool
    table = {entry.tool: entry for entry in context.stage1.tool_table}
    coverage = {
        (row.tool, row.category): row
        for row in context.recall_coverage.matrix
    }
    target_constraints = _target_constraints(context)
    rows: list[RelevantToolCategoryRow] = []
    for category in dict.fromkeys(context.required_categories):
        panel = ownership[category]
        primary_row = coverage.get((primary, category))
        candidates = {
            candidate.tool: ("ELIGIBLE", candidate)
            for candidate in panel.eligible_candidates
        }
        candidates.update(
            {
                candidate.tool: ("NOT_SHORTLISTED", candidate)
                for candidate in panel.not_shortlisted_candidates
            }
        )
        candidates.update(
            {
                candidate.tool: ("UNDER_EVIDENCED", candidate)
                for candidate in panel.under_evidenced_candidates
            }
        )
        candidates.update(
            {
                candidate.tool: ("INELIGIBLE", candidate)
                for candidate in panel.rejected_candidates
            }
        )
        for tool, stage1_evidence in lineage.tools.items():
            entry = table[tool]
            relevant_cards = [
                card
                for card in cards
                if card.tool == tool
                and card.category in {None, category, "__GLOBAL__"}
            ]
            evidence_by_slot: dict[str, list[EvidenceCard]] = {
                slot: [] for slot in _SLOTS
            }
            for card in relevant_cards:
                evidence_by_slot[_evidence_slot(card)].append(card)
            applicability = [
                MatrixEvidenceApplicability(
                    evidence_id=card.evidence_id,
                    applicability_tags=_string_list(
                        card.scope.get("applicability_tags")
                    ),
                    applies_to_target=(
                        card.scope.get("applies_to_target")
                        if isinstance(
                            card.scope.get("applies_to_target"),
                            bool,
                        )
                        else None
                    ),
                )
                for card in relevant_cards
                if card.evidence_type == "rag_passage"
            ]
            category_row = coverage.get((tool, category))
            if tool == primary:
                eligibility = "PRIMARY"
                strength = None
                role = "PRIMARY"
            else:
                role = "FEASIBLE_CANDIDATE"
                if panel.assignment_status == "PRIMARY_SUFFICIENT":
                    eligibility = "PRIMARY_SUFFICIENT_CLOSED"
                    strength = complement_strength_against_primary(
                        candidate_rate=(
                            category_row.R_hat
                            if category_row is not None
                            else None
                        ),
                        candidate_n_eff=(
                            category_row.n_eff
                            if category_row is not None
                            else None
                        ),
                        primary_rate=(
                            primary_row.R_hat
                            if primary_row is not None
                            else None
                        ),
                        primary_n_eff=(
                            primary_row.n_eff
                            if primary_row is not None
                            else None
                        ),
                    )
                else:
                    eligibility, candidate = candidates[tool]
                    strength = candidate.strength
            rows.append(
                RelevantToolCategoryRow(
                    category=category,
                    tool=tool,
                    role=role,
                    feasible=entry.feasible,
                    feasibility_reasons=list(entry.feasibility_reasons),
                    ownership_eligibility=eligibility,
                    stage1_evidence=stage1_evidence,
                    category_evidence=category_row,
                    evidence_by_slot=evidence_by_slot,
                    applicability=applicability,
                    target_constraints=target_constraints,
                    runtime_evidence=_matrix_runtime_evidence(entry),
                    primary_decision=panel.primary_decision,
                    strength=strength,
                )
            )
    return rows


def _action(
    *,
    action_type: str,
    primary: str,
    evidence: dict[str, list[ActionEvidence]],
    context: Stage2EvidenceContext,
    budget: BudgetProfile,
    extra_legal: bool = True,
    extra_reason: str | None = None,
) -> CandidateAction:
    estimate = estimated_budget(
        [primary],
        context.stage1.tool_table,
        budget.execution_schedule,
    )
    legal = estimate is not None and within_budget(estimate, budget) and extra_legal
    reasons: list[str] = []
    if estimate is None:
        constraints = (
            plan_constraint_reasons(
                [primary],
                context.stage1.tool_table,
                budget.execution_schedule,
            )
            if budget.execution_schedule is not None
            else []
        )
        if any(reason.startswith("TOOL_TIMEOUT_TOO_SHORT:") for reason in constraints):
            reasons.append("PRIMARY_EXCEEDS_EXPLICIT_TOOL_TIMEOUT")
        else:
            reasons.append("PRIMARY_RUNTIME_UNKNOWN")
    elif not within_budget(estimate, budget):
        reasons.append("PRIMARY_EXCEEDS_BUDGET")
    if not extra_legal and extra_reason:
        reasons.append(extra_reason)
    return CandidateAction(
        action_id=action_id_for(action_type),
        action_type=action_type,
        tools=[primary],
        evidence=evidence,
        estimated_budget=estimate,
        legal=legal,
        legality_reasons=reasons,
    )


def build_action_evidence_matrix(
    context: Stage2EvidenceContext,
    budget: BudgetProfile,
    *,
    retriever: PassageRetriever | None = None,
) -> ActionByEvidenceMatrix:
    """Build the two-action matrix and auditable complement candidate panels."""
    selection = context.stage1.primary_selection
    if selection.status != Stage1Status.PRIMARY_SELECTED or not selection.primary_tool:
        raise ValueError("Stage 2 requires a selected Stage 1 primary tool")
    primary = selection.primary_tool

    stage1_evidence = _stage1_evidence(context)
    retrieved_cards, retrieval_diagnostics = _retrieved_cards(
        context,
        retriever,
        stage1_evidence,
    )
    cards = [
        *_stage1_score_cards(context, stage1_evidence),
        *_recall_cards(context, stage1_evidence),
        *_external_performance_cards(context, stage1_evidence),
        *_overall_metric_cards(context, stage1_evidence),
        *_runtime_cards(context),
        *retrieved_cards,
    ]
    stage1_evidence = _attach_passage_ids(stage1_evidence, cards)
    ownership = {
        category: category_ownership_panel(context, cards, category, budget)
        for category in dict.fromkeys(context.required_categories)
    }
    relevant_rows = _relevant_matrix_rows(
        context,
        stage1_evidence,
        cards,
        ownership,
    )

    run_evidence = _empty_evidence()
    primary_entry = next(
        entry for entry in context.stage1.tool_table if entry.tool == primary
    )
    primary_runtime_ref = (
        f"ev_fuzz_campaign_{primary}"
        if primary_entry.tool_cost.fuzz_campaign_budget is not None
        else f"ev_runtime_{primary}"
    )
    primary_refs = [f"ev_scene_{primary}", primary_runtime_ref]
    _append_claim(run_evidence, "FOR", f"Keep immutable Stage 1 primary {primary}", primary_refs)
    rcov = {(row.tool, row.category): row for row in context.recall_coverage.matrix}
    for category in context.required_categories:
        row = rcov.get((primary, category))
        ref = rcov_evidence_id(primary, category)
        if row is not None and row.R_hat is not None:
            slot = "FOR" if row.support_level == "eligible" else "GAP"
            _append_claim(run_evidence, slot, f"Primary evidence for {category}", [ref])

    composition_evidence = _empty_evidence()
    for category, panel in ownership.items():
        for candidate in panel.eligible_candidates:
            _append_claim(
                composition_evidence,
                "FOR",
                f"Count-qualified complement {candidate.tool} for {category}",
                candidate.evidence_refs,
            )
        if not panel.eligible_candidates:
            _append_claim(
                composition_evidence,
                "GAP",
                f"No eligible complement for {category}; retain primary",
                [ref for item in panel.under_evidenced_candidates for ref in item.evidence_refs],
            )
    for card in cards:
        if card.evidence_type != "rag_passage":
            continue
        if card.decision_role in {"oppose", "constraint"}:
            _append_claim(
                composition_evidence,
                "AGAINST",
                str(card.scope.get("claim_text") or "Complement caveat"),
                [card.evidence_id],
            )
        elif card.decision_role == "compare":
            _append_claim(
                composition_evidence,
                "COMPARE",
                str(card.scope.get("claim_text") or "Complement comparison"),
                [card.evidence_id],
            )

    has_complement = any(panel.eligible_candidates for panel in ownership.values())
    actions = [
        _action(
            action_type="RUN_PRIMARY",
            primary=primary,
            evidence=run_evidence,
            context=context,
            budget=budget,
        ),
        _action(
            action_type="PLAN_COMPOSITION",
            primary=primary,
            evidence=composition_evidence,
            context=context,
            budget=budget,
            extra_legal=has_complement,
            extra_reason="NO_ELIGIBLE_COMPLEMENT",
        ),
    ]
    return ActionByEvidenceMatrix(
        budget_profile=budget,
        stage1_evidence=stage1_evidence,
        actions=actions,
        evidence_cards=cards,
        ownership_panel=ownership,
        retrieval_diagnostics=retrieval_diagnostics,
        relevant_matrix_rows=relevant_rows,
    )
