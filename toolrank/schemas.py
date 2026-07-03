from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


DASP10_CATEGORIES = [
    "reentrancy",
    "access_control",
    "arithmetic",
    "unchecked_low_level_calls",
    "denial_of_service",
    "bad_randomness",
    "front_running",
    "time_manipulation",
    "short_addresses",
    "unknown_unknowns",
]


class TriState(str, Enum):
    no = "no"
    partial = "partial"
    yes = "yes"


class DetectionMode(str, Enum):
    static = "static"
    symbolic = "symbolic"
    fuzz = "fuzz"
    ml = "ml"
    llm = "llm"


class D7InputSupport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sol: bool = False
    bytecode: bool = False
    runtime: bool = False


class D1Metric(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    precision: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    recall: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    f1: Optional[float] = Field(default=None, ge=0.0, le=1.0, alias="f1_score")
    accuracy: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    time_sec: Optional[float] = Field(default=None, gt=0.0)
    execution_time_avg: Optional[float] = Field(default=None, gt=0.0)
    failure_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    @property
    def resolved_time_sec(self) -> Optional[float]:
        return self.time_sec if self.time_sec is not None else self.execution_time_avg


class VulnerabilityScoreCount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detected: int = Field(ge=0)
    total: int = Field(ge=0)


class ToolCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str
    tool_name: str
    d7_input_support: D7InputSupport
    d8_mode: DetectionMode
    d2_solidity_versions: str
    d3_multifile_support: TriState
    d3_multicontract_support: TriState = TriState.partial
    d1_metrics: Optional[Dict[str, D1Metric]] = None


class FeasibilityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feasible: bool
    reasons: List[str] = Field(default_factory=list)


class ContractFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_path: Optional[str] = None
    source_kind: Literal["sol", "bytecode", "runtime", "mixed", "unknown"] = "unknown"
    solidity_versions: List[str] = Field(default_factory=list)
    primary_solidity_version: Optional[str] = None
    loc_total: int = 0
    function_count: int = 0
    file_count: int = 0
    contract_count: int = 0
    is_multifile: bool = False
    cyclomatic_avg: float = 0.0
    cyclomatic_max: int = 0
    cyclomatic_sum: int = 0
    max_nesting: int = 0
    contract_coupling: int = 0


class DatasetComplexityStats(BaseModel):
    """Contract complexity summary statistics per dataset.

    Follows the Table-1 convention in SliSE (Wang et al., FSE 2024):
    avg Loc, avg functions, avg sub-contracts.
    """

    model_config = ConfigDict(extra="allow")

    avg_loc: Optional[float] = None
    median_loc: Optional[float] = None
    avg_functions: Optional[float] = None
    avg_subcontracts: Optional[float] = None
    vulnerability_categories: List[str] = Field(default_factory=list)


class DatasetProfile(BaseModel):
    model_config = ConfigDict(extra="allow")

    dataset_name: str
    solc: List[str] = Field(default_factory=list)
    contract_count_total: Optional[int] = None
    realism_level: Optional[str] = None
    domain_tags: List[str] = Field(default_factory=list)
    loc_profile: Dict[str, Any] = Field(default_factory=dict)
    complexity_stats: Optional[DatasetComplexityStats] = None
    what_contracts: Optional[str] = None
    how_collected: Optional[str] = None
    scale: Optional[str] = None
    labeling: Optional[str] = None
    target_vulnerabilities: List[str] = Field(default_factory=list)
    label_granularity: Optional[str] = None
    label_count: Optional[int] = None
    label_count_basis: Optional[str] = None


class ToolPerformanceObservation(BaseModel):
    model_config = ConfigDict(extra="allow")

    tool_name: str
    metrics: D1Metric
    vulnerability_scores: Optional[Dict[str, float]] = None
    vulnerability_score_counts: Optional[Dict[str, VulnerabilityScoreCount]] = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_tp_over_gt_scores(cls, data):
        if not isinstance(data, dict):
            return data
        raw_scores = data.get("vulnerability_scores")
        if not isinstance(raw_scores, dict):
            return data

        normalized_scores: Dict[str, float] = {}
        raw_counts = data.get("vulnerability_score_counts")
        normalized_counts = dict(raw_counts) if isinstance(raw_counts, dict) else {}
        for category, value in raw_scores.items():
            key = str(category)
            if isinstance(value, str) and "/" in value:
                detected_text, total_text = value.split("/", 1)
                detected = int(detected_text.strip())
                total = int(total_text.strip())
                normalized_counts[key] = {"detected": detected, "total": total}
                if total > 0:
                    normalized_scores[key] = detected / total
            else:
                normalized_scores[key] = float(value)

        return {
            **data,
            "vulnerability_scores": normalized_scores or None,
            "vulnerability_score_counts": normalized_counts or None,
        }


class PerformanceEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    source_id: str
    publication_date: Optional[str] = None
    dataset_profile: DatasetProfile
    tool_performance_data: List[ToolPerformanceObservation] = Field(default_factory=list)


class PerformanceKnowledgeBase(BaseModel):
    model_config = ConfigDict(extra="allow")

    knowledge_base_type: str
    criteria: Dict[str, Any] = Field(default_factory=dict)
    entries: List[PerformanceEntry] = Field(default_factory=list)


class CompositionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_tool_ids: List[str] = Field(default_factory=list)
    anchor_tool_id: str = ""
    complementary_tool_ids: List[str] = Field(default_factory=list)
    total_estimated_time_sec: float = 0.0
    category_assignments: Dict[str, str] = Field(default_factory=dict)
    rationale: str = ""


class ExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["not_requested", "planned", "executed", "failed"] = "not_requested"
    execution_mode: str = "none"
    target_path: Optional[str] = None
    results_root: Optional[str] = None
    runner_script: Optional[str] = None
    runner_cwd: Optional[str] = None
    runner_command: List[str] = Field(default_factory=list)
    native_commands: List[str] = Field(default_factory=list)
    primary_tool: Optional[str] = None
    tool_categories: Dict[str, List[str]] = Field(default_factory=dict)
    return_code: Optional[int] = None
    stdout_tail: Optional[str] = None
    stderr_tail: Optional[str] = None
    fusion_summary: str = ""
    per_tool_findings: Dict[str, List[Dict[str, Any]]] = Field(
        default_factory=dict,
        description="Per-tool raw findings: {tool_id: [finding_dicts]}. "
        "Populated by the execution runner or injected externally.",
    )


class Finding(BaseModel):
    """Normalized finding representation per paper Eq. 7: r = (t, ν, λ, γ, η).

    t = source_tool, ν = category, λ = location, γ = severity, η = explanation.
    The ``raw`` dict preserves all original fields from the tool's output report.
    """
    model_config = ConfigDict(extra="forbid")

    source_tool: str
    category: str
    location: str = ""
    severity: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    explanation: str = ""
    raw: Dict[str, Any] = Field(default_factory=dict, description="Original tool report fields, preserved verbatim.")


class FusedReport(BaseModel):
    """Category-aware fused report produced after multi-tool composition.

    Paper semantics: anchor strong categories kept, weak categories
    replaced/supplemented, overlapping findings deduplicated.
    """
    model_config = ConfigDict(extra="forbid")

    anchor_tool_id: str
    weak_categories: List[str] = Field(default_factory=list)
    strong_categories: List[str] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)
    removed_anchor_findings_count: int = 0
    inserted_complement_findings_count: int = 0
    deduplicated_count: int = 0
    findings_source: str = Field(
        default="synthesized",
        description="'execution' if fused from real runner findings, "
        "'synthesized' if built from toolcard fallback.",
    )
    summary: str = ""
