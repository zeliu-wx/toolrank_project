from __future__ import annotations

from toolrank.schemas import (
    D1Metric,
    DatasetProfile,
    PerformanceEntry,
    PerformanceKnowledgeBase,
    ToolPerformanceObservation,
)
from toolrank.schemas_v2 import (
    RuntimeCandidateEvidence,
    RuntimeEvidenceAssessment,
    RuntimeEstimateProvenance,
    SceneNeighbor,
    ScenePool,
    ToolCostEntry,
    ToolTableEntry,
)


def observation(
    tool: str,
    *,
    recall: float | None,
    precision: float | None,
    detected: int | None = None,
    total: int | None = None,
) -> ToolPerformanceObservation:
    counts = None
    if detected is not None and total is not None:
        counts = {"reentrancy": {"detected": detected, "total": total}}
    return ToolPerformanceObservation(
        tool_name=tool,
        metrics=D1Metric(recall=recall, precision=precision),
        vulnerability_score_counts=counts,
    )


def entry(source_id: str, observations: list[ToolPerformanceObservation]) -> PerformanceEntry:
    return PerformanceEntry(
        source_id=source_id,
        dataset_profile=DatasetProfile(dataset_name=source_id),
        tool_performance_data=observations,
    )


def knowledge_base(entries: list[PerformanceEntry]) -> PerformanceKnowledgeBase:
    return PerformanceKnowledgeBase(knowledge_base_type="performance", entries=entries)


def scene_pool(*weighted_sources: tuple[str, float, float]) -> ScenePool:
    return ScenePool(
        neighbors=[
            SceneNeighbor(
                slice_id=f"{source_id}_slice",
                benchmark_family=source_id,
                paper_id=source_id,
                weight=weight,
                kernel_density=density,
                distance=0.1,
            )
            for source_id, weight, density in weighted_sources
        ]
    )


def tool_entry(
    tool: str,
    *,
    feasible: bool = True,
    runtime: float | None = 1.0,
) -> ToolTableEntry:
    provenance = None
    evidence = None
    if runtime is not None:
        source_id = f"synthetic_{tool}"
        candidate = RuntimeCandidateEvidence(
            source_id=source_id,
            dataset_name="synthetic_fixture",
            metric_field="execution_time_avg",
            source_runtime_seconds=runtime * 60.0,
            schedulable_runtime_seconds=runtime * 60.0,
            runtime_unit="seconds",
            runtime_basis="per_contract",
            scene_weight=1.0,
            compiler_match=True,
            included_in_quantile=True,
        )
        provenance = RuntimeEstimateProvenance(
            method="scene_weighted_p90_compatible_dataset_proxy",
            selected_source_id=source_id,
            selected_dataset_name="synthetic_fixture",
            selected_metric_field="execution_time_avg",
            selected_source_runtime_seconds=runtime * 60.0,
            selected_runtime_seconds=runtime * 60.0,
            runtime_basis="per_contract",
            target_compiler_bucket="0.8.x",
            support_mass=1.0,
            candidate_source_ids=[source_id],
            candidates=[candidate],
        )
        evidence = RuntimeEvidenceAssessment(
            status="QUALIFIED",
            target_compiler_bucket="0.8.x",
            source_runtime_unit="seconds",
            runtime_basis_default="per_contract",
            support_mass=1.0,
            candidates=[candidate],
        )
    return ToolTableEntry(
        tool=tool,
        feasible=feasible,
        tool_cost=ToolCostEntry(
            expected_runtime_minutes=runtime,
            runtime_provenance=provenance,
            runtime_evidence=evidence,
        ),
    )
