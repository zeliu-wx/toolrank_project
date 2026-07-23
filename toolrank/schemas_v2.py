"""Pydantic models for the SCREC, DACE-RAG, CEGO, and checker pipeline."""

from __future__ import annotations

from enum import Enum
import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from toolrank.categories import normalize_category
from toolrank.roc import PreferenceLevel
from toolrank.schemas import (
    ExecutionSchedule,
    KnowledgeSourceLocator,
    PerformanceObservationRef,
    RuntimeLiteratureSummary,
)


AlertCap = Literal["low", "medium", "high"]
ActionType = Literal[
    "RUN_PRIMARY",
    "PLAN_COMPOSITION",
]
EvidenceSlot = Literal["FOR", "AGAINST", "COMPARE", "GAP"]
ConfidenceLevel = Literal["low", "medium", "high"]
EvidenceAggregationLevel = Literal[
    "category_level",
    "tool_level",
    "dataset_level",
    "scene_level",
    "paper_level",
    "unknown",
]
EvidenceDecisionRole = Literal[
    "support",
    "oppose",
    "compare",
    "gap",
    "constraint",
    "caveat",
]
EvidenceSourceReliability = Literal[
    "manual_curated",
    "benchmark",
    "artifact",
    "peer_reviewed",
    "documentation",
    "experiment_log",
    "unknown",
]
PassageActionScope = Literal[
    "SINGLE_TOOL",
    "PLAN_COMPOSITION",
    "CONTINUE_HEDGE",
]
KnowledgeKind = Literal[
    "category_capability",
    "tool_complementarity",
    "fp_precision_risk",
    "failure_mode",
    "hard_scheduling_rule",
]
RelationToOwner = Literal[
    "supports_owner",
    "opposes_owner",
    "owner_stronger",
    "owner_weaker",
    "owner_complements",
    "evidence_gap",
    "owner_ineligible",
]
EvidenceBasis = Literal[
    "benchmark_result",
    "paired_ablation",
    "official_documentation",
    "reproducible_issue",
    "manual_curation",
]
SourceReliability = Literal[
    "peer_reviewed",
    "artifact",
    "manual_curated",
    "official_tool_doc",
    "maintainer_issue",
    "internal_eval",
    "community_report",
]

ALLOWED_TAG_PREFIXES = (
    "scene:",
    "scale:",
    "input:",
    "solc:",
    "toolver:",
    "evm:",
    "analysis:",
)

SCHEDULING_ACTIONS: set[PassageActionScope] = {
    "SINGLE_TOOL",
    "PLAN_COMPOSITION",
    "CONTINUE_HEDGE",
}

ALLOWED_RELATIONS: dict[KnowledgeKind, set[RelationToOwner]] = {
    "category_capability": {"supports_owner", "owner_stronger", "owner_weaker", "evidence_gap"},
    "tool_complementarity": {"owner_complements", "owner_stronger", "owner_weaker", "evidence_gap"},
    "fp_precision_risk": {"opposes_owner", "owner_stronger", "owner_weaker"},
    "failure_mode": {"opposes_owner", "owner_ineligible", "evidence_gap"},
    "hard_scheduling_rule": {"owner_ineligible"},
}

GLOBAL_CATEGORY = "__GLOBAL__"


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def stage1_evaluation_id(tool: str, benchmark_id: str) -> str:
    """Return the stable identity of one Stage 1 ``(tool, benchmark)`` row."""
    return f"stage1_eval::{tool}::{benchmark_id}"


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    source_type: Literal[
        "paper_table_cell",
        "paper_text",
        "benchmark_metadata",
        "toolcard",
        "stage1_field",
        "stage2_field",
        "runtime_output",
        "rag_passage",
    ]
    paper_id: str | None = None
    field_path: str | None = None
    extraction_confidence: ConfidenceLevel = "medium"


class BudgetProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_slots: int = Field(ge=0)
    runtime_cap_minutes: float = Field(ge=0.0)
    alert_cap: AlertCap = "medium"
    execution_schedule: ExecutionSchedule | None = None

    @model_validator(mode="before")
    @classmethod
    def _default_execution_schedule(cls, data):
        if not isinstance(data, dict) or data.get("execution_schedule") is not None:
            return data
        runtime_cap = float(data.get("runtime_cap_minutes", 0.0))
        if runtime_cap <= 0.0:
            return data
        return {
            **data,
            "execution_schedule": {
                "contract_count": 1,
                "execution_jobs": 0,
                "tool_timeout_seconds": runtime_cap * 60.0,
                "timeout_source": "budget_default",
            },
        }

    @model_validator(mode="after")
    def _schedule_is_resolved(self) -> "BudgetProfile":
        if self.runtime_cap_minutes > 0.0 and self.execution_schedule is None:
            raise ValueError("positive runtime budgets require an execution schedule")
        return self


class UserRequirementProfile(BaseModel):
    """User requirement profile (URP).

    recall/precision preferences map to ROC weights for Stage 1 primary-tool
    selection; focus_categories enter the Stage 2 attention set (origin
    user_mandated) and must be covered by the schedule;
    runtime_budget_minutes bounds the composed combination.
    """

    model_config = ConfigDict(extra="forbid")

    recall: PreferenceLevel = "Default"
    precision: PreferenceLevel = "Default"
    focus_categories: list[str] = Field(default_factory=list)
    runtime_budget_minutes: float = Field(default=30.0, gt=0.0)

    @field_validator("focus_categories")
    @classmethod
    def _normalize_focus_categories(cls, values: list[str]) -> list[str]:
        return list(
            dict.fromkeys(
                category
                for value in values
                if (category := normalize_category(value))
            )
        )


RuntimeBasis = Literal["per_contract", "per_kloc", "campaign_cap"]


class RuntimeCandidateEvidence(BaseModel):
    """One replayable Performance-KB runtime candidate."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    dataset_name: str
    metric_field: Literal[
        "time_sec",
        "execution_time_avg",
        "execution_time_avg_average_s",
    ]
    source_runtime_seconds: float = Field(gt=0.0)
    schedulable_runtime_seconds: float | None = Field(default=None, gt=0.0)
    runtime_unit: str | None = None
    runtime_basis: str | None = None
    scene_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    compiler_match: bool = False
    loc_match: bool | None = None
    included_in_quantile: bool = False
    limitations: list[str] = Field(default_factory=list)
    sample_count: int | None = Field(default=None, ge=0)
    success_count: int | None = Field(default=None, ge=0)
    timeout_count: int | None = Field(default=None, ge=0)
    compilation_failure_count: int | None = Field(default=None, ge=0)
    failure_count: int | None = Field(default=None, ge=0)

    @field_validator("source_id", "dataset_name")
    @classmethod
    def _non_empty_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("runtime candidate identities cannot be empty")
        return normalized

    @field_validator("source_runtime_seconds", "schedulable_runtime_seconds")
    @classmethod
    def _finite_seconds(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("runtime seconds must be finite")
        return value


class RuntimeEvidenceAssessment(BaseModel):
    """Runtime evidence quality, retained even when scheduling fails closed."""

    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "QUALIFIED",
        "NO_RUNTIME_ROWS",
        "RUNTIME_UNIT_MISSING",
        "RUNTIME_UNIT_UNSUPPORTED",
        "RUNTIME_BASIS_MISSING",
        "TARGET_COMPILER_UNKNOWN",
        "NO_COMPATIBLE_RUNTIME_EVIDENCE",
        "INSUFFICIENT_RUNTIME_SUPPORT",
    ]
    target_compiler_bucket: str | None = None
    target_loc_bucket: str | None = None
    source_runtime_unit: str | None = None
    runtime_basis_default: str | None = None
    support_mass: float = Field(default=0.0, ge=0.0, le=1.0)
    support_threshold: float = Field(default=0.2, ge=0.0, le=1.0)
    quantile: float = Field(default=0.9, gt=0.0, le=1.0)
    candidates: list[RuntimeCandidateEvidence] = Field(default_factory=list)
    descriptive_literature_summaries: list[RuntimeLiteratureSummary] = Field(
        default_factory=list
    )
    limitations: list[str] = Field(default_factory=list)


class RuntimeEstimateProvenance(BaseModel):
    """Qualified Performance-KB evidence selected by weighted P90."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["scene_weighted_p90_compatible_dataset_proxy"]
    selected_source_id: str
    selected_dataset_name: str
    selected_metric_field: Literal[
        "time_sec",
        "execution_time_avg",
        "execution_time_avg_average_s",
    ]
    selected_source_runtime_seconds: float = Field(gt=0.0)
    selected_runtime_seconds: float = Field(gt=0.0)
    runtime_unit: Literal["seconds"] = "seconds"
    runtime_basis: Literal["per_contract", "per_kloc"]
    target_compiler_bucket: str
    target_loc_bucket: str | None = None
    support_mass: float = Field(ge=0.0, le=1.0)
    support_threshold: float = Field(default=0.2, ge=0.0, le=1.0)
    quantile: float = Field(default=0.9, gt=0.0, le=1.0)
    candidate_source_ids: list[str] = Field(default_factory=list)
    candidates: list[RuntimeCandidateEvidence] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("selected_source_id", "selected_dataset_name", "target_compiler_bucket")
    @classmethod
    def _non_empty_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("runtime provenance identities cannot be empty")
        return normalized

    @field_validator("selected_source_runtime_seconds", "selected_runtime_seconds")
    @classmethod
    def _finite_selected_seconds(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("selected runtime seconds must be finite")
        return value

    @field_validator("candidate_source_ids")
    @classmethod
    def _valid_candidate_ids(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if not normalized or any(not value for value in normalized):
            raise ValueError("candidate_source_ids must be non-empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("candidate_source_ids must be unique")
        return normalized

    @model_validator(mode="after")
    def _candidate_trace_is_consistent(self) -> "RuntimeEstimateProvenance":
        if self.selected_source_id not in self.candidate_source_ids:
            raise ValueError("selected_source_id must appear in candidate_source_ids")
        if not self.candidates:
            raise ValueError("runtime provenance requires candidate rows")
        candidate_ids = {candidate.source_id for candidate in self.candidates}
        if set(self.candidate_source_ids) != candidate_ids:
            raise ValueError("candidate_source_ids must match candidate rows")
        selected = [
            candidate
            for candidate in self.candidates
            if candidate.source_id == self.selected_source_id
            and candidate.included_in_quantile
        ]
        if not selected:
            raise ValueError("selected runtime source must be included in the quantile")
        return self


class FuzzCampaignBudget(BaseModel):
    """User-controlled per-input fuzz duration, not completion evidence."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["user_budget_fuzz_campaign"] = "user_budget_fuzz_campaign"
    allocated_runtime_seconds: float = Field(gt=0.0)
    timeout_source: Literal["budget_default", "explicit"]
    runtime_semantics: Literal[
        "campaign_allocation_not_completion_estimate"
    ] = "campaign_allocation_not_completion_estimate"

    @field_validator("allocated_runtime_seconds")
    @classmethod
    def _finite_allocation(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("fuzz campaign allocation must be finite")
        return value


class ToolCostEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_slots: int = Field(default=1, ge=0)
    expected_runtime_minutes: float | None = Field(default=None, gt=0.0)
    alert_risk: AlertCap = "medium"
    runtime_provenance: RuntimeEstimateProvenance | None = None
    runtime_evidence: RuntimeEvidenceAssessment | None = None
    fuzz_campaign_budget: FuzzCampaignBudget | None = None

    @field_validator("expected_runtime_minutes")
    @classmethod
    def _finite_minutes(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("expected_runtime_minutes must be finite")
        return value

    @model_validator(mode="after")
    def _runtime_matches_provenance(self) -> "ToolCostEntry":
        has_runtime = self.expected_runtime_minutes is not None
        has_provenance = self.runtime_provenance is not None
        if has_runtime != has_provenance:
            raise ValueError("runtime and runtime_provenance must be present together")
        if self.fuzz_campaign_budget is not None and (has_runtime or has_provenance):
            raise ValueError(
                "fuzz campaign allocation cannot be historical completion evidence"
            )
        if has_runtime and has_provenance:
            expected = self.runtime_provenance.selected_runtime_seconds / 60.0
            if not math.isclose(
                self.expected_runtime_minutes,
                expected,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise ValueError("runtime minutes must equal provenance seconds / 60")
        return self


class SceneNeighbor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slice_id: str
    benchmark_family: str
    paper_id: str | None = None
    weight: float = Field(ge=0.0, le=1.0)
    distance: float = Field(ge=0.0)
    kernel_density: float = Field(default=0.0, ge=0.0, le=1.0)
    category_profile: dict[str, float] = Field(default_factory=dict)
    provenance_refs: list[str] = Field(default_factory=list)


class ScenePool(BaseModel):
    model_config = ConfigDict(extra="forbid")

    neighbors: list[SceneNeighbor] = Field(default_factory=list)


class Stage1Status(str, Enum):
    PRIMARY_SELECTED = "PRIMARY_SELECTED"
    NO_SCENE_EVIDENCE = "NO_SCENE_EVIDENCE"
    NO_FEASIBLE_TOOL = "NO_FEASIBLE_TOOL"
    NO_PRIMARY_WITH_SUFFICIENT_SUPPORT = "NO_PRIMARY_WITH_SUFFICIENT_SUPPORT"


class BenchmarkToolScore(BaseModel):
    """One paper-defined score ``s_t,D`` and its source metrics."""

    model_config = ConfigDict(extra="forbid")

    evaluation_id: str
    tool: str
    benchmark_id: str
    source_id: str
    dataset_id: str
    weight: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    precision: float = Field(ge=0.0, le=1.0)
    recall_rank: float = Field(ge=1.0)
    precision_rank: float = Field(ge=1.0)
    score: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _stable_evaluation_id(self) -> "BenchmarkToolScore":
        if self.evaluation_id != stage1_evaluation_id(self.tool, self.benchmark_id):
            raise ValueError("Stage 1 evaluation ID must match tool and benchmark")
        return self


class NominalToolScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    S_scene: float = Field(ge=0.0, le=1.0)
    rank: int = Field(ge=1)
    support_mass: float = Field(default=0.0, ge=0.0, le=1.0)
    preferred_metric_value: float | None = Field(default=None, ge=0.0, le=1.0)
    P_scene: float | None = Field(default=None, ge=0.0, le=1.0)
    R_scene: float | None = Field(default=None, ge=0.0, le=1.0)


class ScorePanel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    benchmark_weights: dict[str, float] = Field(default_factory=dict)
    benchmark_scores: list[BenchmarkToolScore] = Field(default_factory=list)
    nominal_scores: list[NominalToolScore] = Field(default_factory=list)


class Stage1BenchmarkEvidence(BaseModel):
    """Canonical cross-layer projection of one Stage 1 evaluation row."""

    model_config = ConfigDict(extra="forbid")

    evaluation_id: str
    tool: str
    benchmark_id: str
    source_id: str
    dataset_id: str
    w_D: float = Field(ge=0.0, le=1.0)
    s_t_D: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    precision: float = Field(ge=0.0, le=1.0)
    recall_rank: float = Field(ge=1.0)
    precision_rank: float = Field(ge=1.0)
    linked_passage_ids: list[str] = Field(default_factory=list)

    @field_validator("linked_passage_ids")
    @classmethod
    def _dedupe_passages(cls, value: list[str]) -> list[str]:
        return _dedupe_keep_order(value)


class Stage1ToolEvidence(BaseModel):
    """Stage 1 aggregate ``S_t`` and its unflattened benchmark rows."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    S_t: float = Field(ge=0.0, le=1.0)
    support_mass: float = Field(default=0.0, ge=0.0, le=1.0)
    benchmark_evaluations: list[Stage1BenchmarkEvidence] = Field(default_factory=list)


class Stage1EvidenceLineage(BaseModel):
    """Matrix-owned Stage 1 scores and benchmark-to-passage lineage."""

    model_config = ConfigDict(extra="forbid")

    primary_tool: str
    benchmark_weights: dict[str, float] = Field(default_factory=dict)
    tools: dict[str, Stage1ToolEvidence] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_projection(self) -> "Stage1EvidenceLineage":
        seen: set[str] = set()
        for tool_id, tool in self.tools.items():
            if tool.tool != tool_id:
                raise ValueError("Stage 1 tool evidence key must match tool")
            for row in tool.benchmark_evaluations:
                if row.tool != tool_id:
                    raise ValueError("Stage 1 benchmark evidence must stay with its tool")
                if row.evaluation_id != stage1_evaluation_id(row.tool, row.benchmark_id):
                    raise ValueError("Stage 1 evaluation ID must match tool and benchmark")
                if row.evaluation_id in seen:
                    raise ValueError("Stage 1 evaluation IDs must be unique")
                seen.add(row.evaluation_id)
                expected_weight = self.benchmark_weights.get(row.benchmark_id)
                if expected_weight is None or not math.isclose(
                    row.w_D,
                    expected_weight,
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                ):
                    raise ValueError("Stage 1 benchmark evidence weight mismatch")
        return self


class PrimarySelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Stage1Status
    primary_tool: str | None = None
    tau: float = Field(default=0.2, ge=0.0, le=1.0)
    eligible_tools: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_primary_state(self) -> "PrimarySelection":
        if self.status == Stage1Status.PRIMARY_SELECTED and not self.primary_tool:
            raise ValueError("PRIMARY_SELECTED requires primary_tool")
        if self.status != Stage1Status.PRIMARY_SELECTED and self.primary_tool is not None:
            raise ValueError("terminal Stage 1 states cannot carry primary_tool")
        return self


class CategoryDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_category_profile: dict[str, float] = Field(default_factory=dict)


class RecallCoverageEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    category: str
    detected: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, ge=0)
    R_hat: float | None = Field(default=None, ge=0.0, le=1.0)
    n_eff: float | None = Field(
        default=None,
        ge=0.0,
        description="Similarity-effective category sample using raw KDE density p_hat_D.",
    )
    support_level: Literal["unsupported", "under_evidenced", "eligible"] = "unsupported"
    evidence_refs: list[str] = Field(default_factory=list)


class RecallCoverageMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    taxonomy_level: Literal["parent", "leaf"] = "parent"
    matrix: list[RecallCoverageEntry] = Field(default_factory=list)


class PrimaryAttention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_tool: str | None = None
    required_categories: list[str] = Field(default_factory=list)
    confirmed_weak_categories: list[str] = Field(default_factory=list)
    under_evidenced_categories: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class ToolTableEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    family: Literal[
        "static_source",
        "static_bytecode",
        "symbolic",
        "fuzz",
        "ml",
        "llm",
        "hybrid",
        "unknown",
    ] = "unknown"
    feasible: bool
    feasibility_reasons: list[str] = Field(default_factory=list)
    expected_runtime_bucket: Literal["unknown", "low", "medium", "high"] = "unknown"
    failure_risk_bucket: Literal["unknown", "low", "medium", "high"] = "unknown"
    tool_cost: ToolCostEntry = Field(default_factory=ToolCostEntry)

    @model_validator(mode="after")
    def _runtime_policy_matches_family(self) -> "ToolTableEntry":
        campaign = self.tool_cost.fuzz_campaign_budget
        has_historical_runtime = (
            self.tool_cost.expected_runtime_minutes is not None
            or self.tool_cost.runtime_provenance is not None
        )
        if self.family == "fuzz":
            if has_historical_runtime:
                raise ValueError(
                    "fuzz tools cannot use historical completion runtime for planning"
                )
        elif campaign is not None:
            raise ValueError("fuzz campaign allocation requires family=fuzz")
        return self


class Stage1EvidencePacket(BaseModel):
    """Typed Stage 1 output; category counts are intentionally absent."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["screc_v2"] = "screc_v2"
    target_contract: dict[str, Any] = Field(default_factory=dict)
    tool_table: list[ToolTableEntry] = Field(default_factory=list)
    scene_pool: ScenePool = Field(default_factory=ScenePool)
    score_panel: ScorePanel = Field(default_factory=ScorePanel)
    primary_selection: PrimarySelection
    provenance_index: list[EvidenceRef] = Field(default_factory=list)


class DACERAGFocusItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    category: str
    reason: str


class PerformanceDBEvidenceRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    source_id: str
    dataset_name: str
    tool: str
    category: str
    detected: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, ge=0)
    R_hat: float | None = Field(default=None, ge=0.0, le=1.0)
    n_eff: float | None = Field(default=None, ge=0.0)


class ToolOverallMetricsRow(BaseModel):
    """Per-tool overall (not per-category) metrics on a referenced dataset."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    source_id: str
    dataset_name: str
    tool: str
    precision: float | None = Field(default=None, ge=0.0, le=1.0)
    recall: float | None = Field(default=None, ge=0.0, le=1.0)
    f1: float | None = Field(default=None, ge=0.0, le=1.0)
    execution_time_avg: float | None = Field(default=None, ge=0.0)


class PrimaryCategoryDecision(BaseModel):
    """Shared Stage 2 gate deciding whether complement search may open."""

    model_config = ConfigDict(extra="forbid")

    category: str
    status: Literal["PRIMARY_SUFFICIENT", "SEARCH_REQUIRED"]
    evidence_classification: Literal[
        "sufficient", "under_evidenced", "confirmed_weak"
    ]
    reason_codes: list[str] = Field(default_factory=list)
    primary_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    primary_n_eff: float | None = Field(default=None, ge=0.0)
    credible_peer_tool: str | None = None
    credible_peer_gap_low: float | None = None


class Stage2EvidenceContext(BaseModel):
    """Post-selection evidence. Category counts live only in this boundary."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["dace_context_v2"] = "dace_context_v2"
    stage1: Stage1EvidencePacket
    required_categories: list[str] = Field(default_factory=list)
    category_diagnostics: CategoryDiagnostics = Field(default_factory=CategoryDiagnostics)
    recall_coverage: RecallCoverageMatrix = Field(default_factory=RecallCoverageMatrix)
    performance_db_view: list[PerformanceDBEvidenceRow] = Field(default_factory=list)
    tool_overall_metrics: list[ToolOverallMetricsRow] = Field(default_factory=list)
    primary_category_decisions: list[PrimaryCategoryDecision] = Field(default_factory=list)
    primary_attention: PrimaryAttention
    dace_rag_focus: list[DACERAGFocusItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_primary_decision_per_required_category(self) -> "Stage2EvidenceContext":
        categories = [decision.category for decision in self.primary_category_decisions]
        if len(categories) != len(set(categories)):
            raise ValueError("primary category decisions cannot contain duplicates")
        if set(categories) != set(self.required_categories):
            raise ValueError("every required category needs one primary decision")
        return self


class Stage2Status(str, Enum):
    PLAN_READY = "PLAN_READY"
    NO_EXECUTABLE_PLAN = "NO_EXECUTABLE_PLAN"


class PipelineStatus(str, Enum):
    PRIMARY_NOT_SELECTED = "PRIMARY_NOT_SELECTED"
    NO_EXECUTABLE_PLAN = "NO_EXECUTABLE_PLAN"
    PLAN_READY = "PLAN_READY"
    EXECUTED = "EXECUTED"
    EXECUTION_FAILED = "EXECUTION_FAILED"


class Stage2Outcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Stage2Status
    reason_codes: list[str] = Field(default_factory=list)
    estimated_plan_runtime_minutes: float | None = Field(default=None, ge=0.0)


class EvidenceCardValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detected: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, ge=0)
    rate: float | None = Field(default=None, ge=0.0, le=1.0)
    n_eff: float | None = Field(default=None, ge=0.0)
    value: float | None = None


class EvidenceCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    source: EvidenceRef
    evidence_type: Literal[
        "per_category_detected_total",
        "tool_scope",
        "runtime_cost",
        "failure_mode",
        "scene_metric",
        "stage1_score",
        "rag_passage",
    ]
    tool: str | None = None
    category: str | None = None
    metric_semantics: Literal[
        "recall_side_detection_rate",
        "historical_precision",
        "historical_recall",
        "historical_f1",
        "runtime",
        "scope",
        "qualitative",
    ]
    value: EvidenceCardValue | None = None
    scope: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    extraction_confidence: ConfidenceLevel = "medium"
    aggregation_level: EvidenceAggregationLevel = "unknown"
    decision_role: EvidenceDecisionRole = "support"
    source_reliability: EvidenceSourceReliability = "unknown"
    linked_evaluation_ids: list[str] = Field(default_factory=list)
    benchmark_relevance_weight: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("linked_evaluation_ids")
    @classmethod
    def _dedupe_evaluation_links(cls, value: list[str]) -> list[str]:
        return _dedupe_keep_order(value)


class ActionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str
    evidence_refs: list[str] = Field(default_factory=list)


class CandidateAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    action_type: ActionType
    tools: list[str] = Field(default_factory=list)
    evidence: dict[EvidenceSlot, list[ActionEvidence]] = Field(default_factory=dict)
    estimated_budget: BudgetProfile | None = None
    legal: bool = True
    legality_reasons: list[str] = Field(default_factory=list)


class ComplementStrengthResult(BaseModel):
    """Candidate-specific Stage 2 evidence strength against the primary."""

    model_config = ConfigDict(extra="forbid")

    candidate_count_qualified: bool
    primary_count_qualified_positive: bool
    evidence_stronger: bool
    basis: Literal[
        "CANDIDATE_COUNT_INELIGIBLE",
        "PRIMARY_BASELINE_UNRELIABLE",
        "NEWCOMBE_CANDIDATE_MINUS_PRIMARY",
    ]
    reason_code: Literal[
        "CANDIDATE_COUNT_EVIDENCE_INELIGIBLE",
        "COUNT_QUALIFIED_CANDIDATE_WITHOUT_RELIABLE_POSITIVE_PRIMARY",
        "CANDIDATE_RECALL_CREDIBLY_STRONGER",
        "CANDIDATE_RECALL_NOT_CREDIBLY_STRONGER",
    ]
    recall_gap: float | None = None
    recall_gap_low: float | None = None
    recall_gap_high: float | None = None


class OwnerCandidateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    category: str
    eligibility: Literal["eligible", "under_evidenced", "ineligible"]
    evidence_scope: Literal["local", "primary", "near_scene", "unrelated_external", "rag_only"]
    evidence_refs: list[str] = Field(default_factory=list)
    caveat_refs: list[str] = Field(default_factory=list)
    detected: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, ge=0)
    rate: float | None = Field(default=None, ge=0.0, le=1.0)
    n_eff: float | None = Field(default=None, ge=0.0)
    strength: ComplementStrengthResult

    @model_validator(mode="after")
    def _eligible_candidate_must_be_evidence_stronger(self) -> "OwnerCandidateEvidence":
        if self.eligibility == "eligible" and not self.strength.evidence_stronger:
            raise ValueError("eligible complement must be evidence-stronger than the primary")
        return self


class CategoryOwnershipPanel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    diagnostic: Literal["required", "confirmed_weak", "under_evidenced"] = "required"
    primary_decision: PrimaryCategoryDecision
    assignment_status: Literal[
        "PRIMARY_SUFFICIENT",
        "COMPLEMENT_AVAILABLE",
        "PRIMARY_ONLY_NO_COMPLEMENT",
    ] = "PRIMARY_ONLY_NO_COMPLEMENT"
    eligible_candidates: list[OwnerCandidateEvidence] = Field(default_factory=list)
    under_evidenced_candidates: list[OwnerCandidateEvidence] = Field(default_factory=list)
    rejected_candidates: list[OwnerCandidateEvidence] = Field(default_factory=list)
    primary_only_reason: str = ""
    caveats: list[str] = Field(default_factory=list)


class ActionEvidenceClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str
    evidence_refs: list[str] = Field(default_factory=list)


class CegoComplementProposal(BaseModel):
    """One strictly decoded complement ballot from a CEGO sample."""

    model_config = ConfigDict(extra="forbid", strict=True)

    category: Annotated[str, Field(min_length=1)]
    tool: Annotated[str, Field(min_length=1)]
    evidence_refs: Annotated[
        list[Annotated[str, Field(min_length=1)]],
        Field(min_length=1),
    ]

    @field_validator("category", "tool")
    @classmethod
    def _reject_blank_identifiers(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("CEGO identifiers cannot be blank")
        return value

    @field_validator("evidence_refs")
    @classmethod
    def _reject_blank_evidence_refs(cls, value: list[str]) -> list[str]:
        if any(not ref.strip() for ref in value):
            raise ValueError("CEGO evidence references cannot be blank")
        return value


class CegoProposalSample(BaseModel):
    """Strict local boundary for one raw CEGO model response."""

    model_config = ConfigDict(extra="forbid", strict=True)

    complements: list[CegoComplementProposal]

    @model_validator(mode="after")
    def _reject_duplicate_categories(self) -> "CegoProposalSample":
        categories = [proposal.category for proposal in self.complements]
        if len(categories) != len(set(categories)):
            raise ValueError("CEGO samples cannot repeat a category")
        return self


class CategoryAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    owner_tools: Annotated[list[str], Field(min_length=1, max_length=2)]
    complement_tool: str | None = None
    status: Literal["PRIMARY_ONLY", "COMPLEMENT_ADDED"] = "PRIMARY_ONLY"
    for_claims: list[ActionEvidenceClaim] = Field(default_factory=list)
    against_claims: list[ActionEvidenceClaim] = Field(default_factory=list)
    compare_claims: list[ActionEvidenceClaim] = Field(default_factory=list)
    gap_claims: list[ActionEvidenceClaim] = Field(default_factory=list)
    caveat_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_owners(self) -> "CategoryAssignment":
        if len(set(self.owner_tools)) != len(self.owner_tools):
            raise ValueError("owner_tools cannot contain duplicates")
        expected_complement = self.owner_tools[1] if len(self.owner_tools) == 2 else None
        expected_status = "COMPLEMENT_ADDED" if expected_complement else "PRIMARY_ONLY"
        if self.complement_tool != expected_complement:
            raise ValueError("complement_tool must match the second owner")
        if self.status != expected_status:
            raise ValueError("assignment status does not match owner_tools")
        return self


class ActionByEvidenceMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["dace_rag_v2"] = "dace_rag_v2"
    budget_profile: BudgetProfile
    stage1_evidence: Stage1EvidenceLineage
    actions: list[CandidateAction] = Field(default_factory=list)
    evidence_cards: list[EvidenceCard] = Field(default_factory=list)
    ownership_panel: dict[str, CategoryOwnershipPanel] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_evidence_links(self) -> "ActionByEvidenceMatrix":
        evaluations = {
            row.evaluation_id: row
            for tool in self.stage1_evidence.tools.values()
            for row in tool.benchmark_evaluations
        }
        evidence_ids: set[str] = set()
        for card in self.evidence_cards:
            if card.evidence_id in evidence_ids:
                raise ValueError("evidence card IDs must be unique")
            evidence_ids.add(card.evidence_id)
            linked = []
            for evaluation_id in card.linked_evaluation_ids:
                row = evaluations.get(evaluation_id)
                if row is None:
                    raise ValueError(f"unknown Stage 1 evaluation link: {evaluation_id}")
                if card.tool is not None and row.tool != card.tool:
                    raise ValueError("evidence cards may link only their tool's evaluations")
                linked.append(row)
            if not linked:
                if card.benchmark_relevance_weight is not None:
                    raise ValueError("unlinked evidence cannot carry benchmark relevance weight")
            elif len(linked) == 1:
                if card.benchmark_relevance_weight is None or not math.isclose(
                    card.benchmark_relevance_weight,
                    linked[0].w_D,
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                ):
                    raise ValueError("single evaluation link must expose its exact relevance weight")
            elif card.benchmark_relevance_weight is not None:
                raise ValueError("multiple evaluation links cannot be flattened into one weight")

        required_tools = {self.stage1_evidence.primary_tool}
        required_tools.update(
            candidate.tool
            for panel in self.ownership_panel.values()
            for candidate in panel.eligible_candidates
        )
        if not required_tools.issubset(self.stage1_evidence.tools):
            raise ValueError("Stage 1 evidence must include the primary and every legal candidate")
        return self


class SelectedToolEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    role: Literal["STARTER", "COMPLEMENT"]
    execution_order: int = Field(ge=1)
    reason_codes: list[str] = Field(default_factory=list)


class BudgetUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: BudgetProfile
    estimated_use: BudgetProfile
    remaining_after_plan: BudgetProfile


class ForbiddenClaimsAttestation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    no_target_vulnerability_claim: bool = True
    no_code_semantic_inference: bool = True
    no_precision_from_detected_total: bool = True
    absence_of_findings_not_treated_as_safe: bool = True
    no_unsourced_numeric_gain: bool = True


class Step2DecisionCertificate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["dace_orch_v2"] = "dace_orch_v2"
    decision_type: ActionType
    selected_action_id: str
    selected_plan: list[SelectedToolEntry] = Field(default_factory=list)
    primary_tool: str
    category_assignments: list[CategoryAssignment] = Field(default_factory=list)
    budget: BudgetUsage
    forbidden_claims_attestation: ForbiddenClaimsAttestation
    short_summary: str = ""

    @model_validator(mode="after")
    def _validate_primary_ownership(self) -> "Step2DecisionCertificate":
        categories: set[str] = set()
        for assignment in self.category_assignments:
            if assignment.category in categories:
                raise ValueError(f"duplicate category assignment: {assignment.category}")
            categories.add(assignment.category)
            if assignment.owner_tools[0] != self.primary_tool:
                raise ValueError("every owner set must begin with primary_tool")
        return self


class CheckerVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ACCEPT", "REJECT", "REQUEST_REGENERATION"]
    checked_action_id: str | None = None
    rule_failures: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    hard_failures: list[str] = Field(default_factory=list)
    regeneration_reasons: list[str] = Field(default_factory=list)


class Passage(BaseModel):
    """Owner-oriented atomic scheduling evidence.

    One Passage = one (owner_tool, category, claim) with a deterministic
    relation to that owner. The 4 evidence slots (FOR/AGAINST/COMPARE/GAP)
    are a runtime projection of `relation_to_owner` and are NOT stored.
    """

    model_config = ConfigDict(extra="forbid")

    # --- Identity ---
    passage_id: Annotated[str, Field(min_length=6, max_length=80)]
    source_id: Annotated[str, Field(min_length=3, max_length=120)]

    # --- Retrieval keys (metadata filter) ---
    owner_tool: Annotated[str, Field(min_length=1, max_length=64)]
    counterpart_tool_ids: list[str] = Field(default_factory=list)
    category: Annotated[str, Field(min_length=1, max_length=64)]
    knowledge_kind: KnowledgeKind
    action_scope: Annotated[list[PassageActionScope], Field(min_length=1)]
    applicability_tags: list[str] = Field(default_factory=list)

    # --- Decision semantics ---
    relation_to_owner: RelationToOwner
    evidence_basis: EvidenceBasis
    source_reliability: SourceReliability

    # --- Prompt content ---
    claim_text: Annotated[str, Field(min_length=12, max_length=180)]
    limitations_text: Annotated[str, Field(default="", max_length=120)]

    # --- Audit only (not rendered to LLM by default) ---
    source_excerpt: Annotated[str, Field(min_length=12, max_length=320)]
    linked_evaluation_ids: list[str] | None = None
    paper_id: str | None = Field(default=None, pattern=r"^paper_[0-9a-f]{32}$")
    source_locator: KnowledgeSourceLocator | None = None
    linked_performance_observation_ids: list[str] = Field(default_factory=list)
    performance_observation_refs: list[PerformanceObservationRef] = Field(
        default_factory=list
    )

    @property
    def tool_ids(self) -> list[str]:
        return _dedupe_keep_order([self.owner_tool, *self.counterpart_tool_ids])

    @property
    def categories(self) -> list[str]:
        return [] if self.category == GLOBAL_CATEGORY else [self.category]

    @property
    def text(self) -> str:
        return self.claim_text

    @property
    def passage_type(self) -> str:
        if self.relation_to_owner == "owner_ineligible":
            return "limitation"
        if self.relation_to_owner in {"owner_stronger", "owner_weaker"}:
            return "comparison"
        if self.relation_to_owner == "owner_complements":
            return "recommendation"
        if self.relation_to_owner == "evidence_gap":
            return "gap"
        return "performance"

    @property
    def scheduling_type(self) -> str:
        if self.knowledge_kind == "tool_complementarity":
            return "tool_complementarity"
        if self.knowledge_kind == "failure_mode":
            return "tool_weakness"
        if self.relation_to_owner == "evidence_gap":
            return "coverage_gap"
        if self.relation_to_owner in {"owner_stronger", "owner_weaker"}:
            return "category_comparison"
        return self.knowledge_kind

    @property
    def polarity(self) -> str:
        if self.relation_to_owner in {"opposes_owner", "owner_ineligible", "owner_weaker"}:
            return "con"
        if self.relation_to_owner == "evidence_gap":
            return "gap"
        if self.relation_to_owner == "owner_stronger":
            return "comparative"
        return "pro"

    @property
    def scenario(self) -> str:
        for tag in self.applicability_tags:
            if tag.startswith("scene:"):
                return tag.removeprefix("scene:")
        return ""

    @property
    def comparison_scope(self) -> str:
        return self.category

    @property
    def stronger_tool_ids(self) -> list[str]:
        return [self.owner_tool] if self.relation_to_owner == "owner_stronger" else []

    @property
    def weaker_tool_ids(self) -> list[str]:
        return [self.owner_tool] if self.relation_to_owner == "owner_weaker" else []

    @property
    def primary_tool(self) -> str:
        return self.counterpart_tool_ids[0] if self.counterpart_tool_ids else ""

    @property
    def complement_tool(self) -> str:
        return self.owner_tool

    @property
    def scene_constraints(self) -> list[str]:
        return [self.scenario] if self.scenario else []

    @property
    def limitations(self) -> list[str]:
        return [self.limitations_text] if self.limitations_text else []

    @field_validator("counterpart_tool_ids", "action_scope", "applicability_tags", mode="before")
    @classmethod
    def _default_list(cls, value):
        return [] if value is None else value

    @field_validator("counterpart_tool_ids", "action_scope", "applicability_tags")
    @classmethod
    def _dedupe(cls, value: list[str]) -> list[str]:
        return _dedupe_keep_order(value)

    @field_validator("linked_evaluation_ids")
    @classmethod
    def _dedupe_explicit_evaluation_links(
        cls, value: list[str] | None
    ) -> list[str] | None:
        return None if value is None else _dedupe_keep_order(value)

    @field_validator("linked_performance_observation_ids")
    @classmethod
    def _dedupe_observation_links(cls, value: list[str]) -> list[str]:
        return _dedupe_keep_order(value)

    @field_validator("applicability_tags")
    @classmethod
    def _validate_tags(cls, tags: list[str]) -> list[str]:
        for tag in tags:
            if ":" not in tag or not tag.startswith(ALLOWED_TAG_PREFIXES):
                raise ValueError(f"unsupported applicability tag: {tag!r}")
        return tags

    @model_validator(mode="after")
    def _validate_contract(self) -> "Passage":
        if self.owner_tool in self.counterpart_tool_ids:
            raise ValueError("owner_tool cannot appear in counterpart_tool_ids")

        ref_ids = [ref.observation_id for ref in self.performance_observation_refs]
        if len(ref_ids) != len(set(ref_ids)):
            raise ValueError("performance observation references must be unique")
        if ref_ids != self.linked_performance_observation_ids:
            raise ValueError(
                "linked_performance_observation_ids must match reference order"
            )
        for ref in self.performance_observation_refs:
            if ref.tool != self.owner_tool:
                raise ValueError("performance observation link belongs to another tool")
            if ref.category != self.category:
                raise ValueError("performance observation link category mismatch")
            if self.paper_id is not None and ref.paper_id != self.paper_id:
                raise ValueError("performance observation link paper mismatch")

        if self.relation_to_owner not in ALLOWED_RELATIONS[self.knowledge_kind]:
            raise ValueError(
                f"relation_to_owner={self.relation_to_owner!r} is illegal for "
                f"knowledge_kind={self.knowledge_kind!r}"
            )

        if self.knowledge_kind == "tool_complementarity" and not self.counterpart_tool_ids:
            raise ValueError("tool_complementarity requires at least one counterpart tool")

        if self.relation_to_owner in {"owner_stronger", "owner_weaker", "owner_complements"}:
            if not self.counterpart_tool_ids:
                raise ValueError(f"{self.relation_to_owner} requires counterpart_tool_ids")

        if self.relation_to_owner == "owner_ineligible":
            if self.knowledge_kind not in {"failure_mode", "hard_scheduling_rule"}:
                raise ValueError("owner_ineligible only valid for failure_mode / hard_scheduling_rule")

        if self.knowledge_kind == "hard_scheduling_rule":
            if self.relation_to_owner != "owner_ineligible":
                raise ValueError("hard_scheduling_rule must map to owner_ineligible")
            if set(self.action_scope) != SCHEDULING_ACTIONS:
                raise ValueError("hard_scheduling_rule must apply to all scheduling actions")
            if self.evidence_basis not in {"official_documentation", "reproducible_issue"}:
                raise ValueError("hard_scheduling_rule needs official_documentation or reproducible_issue")
            if self.source_reliability not in {
                "official_tool_doc", "maintainer_issue", "peer_reviewed", "artifact", "manual_curated",
            }:
                raise ValueError("hard_scheduling_rule has insufficient source_reliability")

        if self.category == GLOBAL_CATEGORY and self.knowledge_kind not in {
            "failure_mode", "hard_scheduling_rule",
        }:
            raise ValueError("__GLOBAL__ category only allowed for failure_mode / hard_scheduling_rule")

        if self.relation_to_owner == "owner_complements" and "SINGLE_TOOL" in self.action_scope:
            raise ValueError("owner_complements is not legal for SINGLE_TOOL")

        if self.relation_to_owner == "evidence_gap":
            if self.evidence_basis not in {"benchmark_result", "manual_curation"}:
                raise ValueError("evidence_gap needs benchmark_result or manual_curation basis")

        return self


class PassageStore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passages: list[Passage] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_passage_ids(self) -> "PassageStore":
        passage_ids = [passage.passage_id for passage in self.passages]
        if len(passage_ids) != len(set(passage_ids)):
            raise ValueError("passage IDs must be unique")
        return self


class ToolRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    run_status: Literal["NOT_RUN", "SUCCESS", "FAIL", "PARTIAL", "TIMEOUT"] = "NOT_RUN"
    runtime_minutes: float | None = Field(default=None, ge=0.0)
    total_findings: int = Field(default=0, ge=0)
