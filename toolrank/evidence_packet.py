"""Build the Stage 1 tool table and post-selection Stage 2 evidence context."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re

from toolrank.assignment_evidence import MIN_N_EFF, complement_strength_against_primary
from toolrank.categories import normalize_category
from toolrank.feasibility import check_feasibility
from toolrank.numeric_bounds import clamp_normalized_mass
from toolrank.rcov import build_recall_coverage
from toolrank.solc_range import version_in_range
from toolrank.schemas import (
    ContractFeatures,
    D1Metric,
    DASP10_CATEGORIES,
    PerformanceKnowledgeBase,
    RuntimeLiteratureSummary,
    ToolCard,
)
from toolrank.schemas_v2 import (
    BudgetProfile,
    CategoryDiagnostics,
    DACERAGFocusItem,
    FuzzCampaignBudget,
    PerformanceDBEvidenceRow,
    PrimaryCategoryDecision,
    PrimaryAttention,
    RuntimeCandidateEvidence,
    RuntimeEvidenceAssessment,
    RuntimeEstimateProvenance,
    ScenePool,
    Stage1EvidencePacket,
    Stage1Status,
    Stage2EvidenceContext,
    ToolCostEntry,
    ToolOverallMetricsRow,
    ToolTableEntry,
)


_DASP10 = set(DASP10_CATEGORIES)


def _tool_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


_RUNTIME_FIELDS = (
    "time_sec",
    "execution_time_avg",
    "execution_time_avg_average_s",
)
MIN_RUNTIME_SUPPORT_MASS = 0.2
RUNTIME_QUANTILE = 0.9
_SUPPORTED_RUNTIME_BASES = {"per_contract", "per_kloc", "campaign_cap"}


@dataclass(frozen=True)
class _RuntimeRow:
    source_id: str
    dataset_name: str
    tool: str
    seconds: float
    metric_field: str
    metric: D1Metric
    solc: tuple[str, ...]
    loc_profile: dict


@dataclass(frozen=True)
class _RuntimeEstimate:
    seconds: float | None
    provenance: RuntimeEstimateProvenance | None
    evidence: RuntimeEvidenceAssessment


def _tool_aliases(cards: list[ToolCard]) -> dict[str, str]:
    owners: dict[str, set[str]] = {}
    for card in cards:
        for raw_alias in (card.tool_id, card.tool_name):
            alias = _tool_key(raw_alias)
            if alias:
                owners.setdefault(alias, set()).add(card.tool_id)
    return {
        alias: next(iter(canonical_tools))
        for alias, canonical_tools in owners.items()
        if len(canonical_tools) == 1
    }


def _runtime_value(metric: D1Metric) -> tuple[float, str] | None:
    for field in _RUNTIME_FIELDS:
        value = getattr(metric, field, None)
        if value is None:
            continue
        seconds = float(value)
        if seconds > 0.0 and math.isfinite(seconds):
            return seconds, field
    return None


def _runtime_rows(
    cards: list[ToolCard],
    kb: PerformanceKnowledgeBase,
) -> dict[str, list[_RuntimeRow]]:
    aliases = _tool_aliases(cards)
    deduplicated: dict[tuple[str, str], _RuntimeRow] = {}
    for entry in kb.entries:
        for observation in entry.tool_performance_data:
            tool = aliases.get(_tool_key(observation.tool_name))
            runtime = _runtime_value(observation.metrics)
            if tool is None or runtime is None:
                continue
            seconds, metric_field = runtime
            row = _RuntimeRow(
                source_id=entry.source_id,
                dataset_name=entry.dataset_profile.dataset_name,
                tool=tool,
                seconds=seconds,
                metric_field=metric_field,
                metric=observation.metrics,
                solc=tuple(entry.dataset_profile.solc),
                loc_profile=entry.dataset_profile.loc_profile,
            )
            key = (entry.source_id, tool)
            current = deduplicated.get(key)
            if current is None or row.seconds > current.seconds:
                deduplicated[key] = row

    by_tool: dict[str, list[_RuntimeRow]] = {}
    for row in deduplicated.values():
        by_tool.setdefault(row.tool, []).append(row)
    return by_tool


def _compiler_bucket(version: str | None) -> str | None:
    if not version:
        return None
    match = re.search(r"(\d+)\.(\d+)", version)
    if match is None:
        return None
    return f"{match.group(1)}.{match.group(2)}.x"


def _loc_bucket(loc_total: int, criteria: dict) -> str | None:
    for raw in criteria.get("loc_bins", []):
        if not isinstance(raw, dict) or not isinstance(raw.get("label"), str):
            continue
        minimum = raw.get("min_inclusive")
        maximum = raw.get("max_exclusive")
        if not isinstance(minimum, (int, float)):
            continue
        if loc_total >= minimum and (maximum is None or loc_total < maximum):
            return raw["label"]
    return None


def _loc_match(
    loc_profile: dict,
    *,
    target_loc_bucket: str | None,
    target_version: str | None,
) -> bool | None:
    counts = loc_profile.get("loc_bin_counts_by_solc") if isinstance(loc_profile, dict) else None
    if not isinstance(counts, dict) or target_loc_bucket is None or target_version is None:
        return None
    bucket = counts.get(target_loc_bucket)
    if not isinstance(bucket, dict):
        return False
    total = 0.0
    matched_key = False
    for version_spec, value in bucket.items():
        if not isinstance(version_spec, str) or not version_in_range(target_version, version_spec):
            continue
        matched_key = True
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            total += float(value)
    return matched_key and total > 0.0


def _candidate_limitations(
    row: _RuntimeRow,
    *,
    runtime_unit: str | None,
    runtime_basis: str | None,
    target_version: str | None,
    compiler_match: bool,
    loc_match: bool | None,
    scene_weight: float,
    target_loc_total: int,
) -> list[str]:
    limitations: list[str] = []
    if runtime_unit is None:
        limitations.append("RUNTIME_UNIT_MISSING")
    elif runtime_unit != "seconds":
        limitations.append("RUNTIME_UNIT_UNSUPPORTED")
    if runtime_basis is None:
        limitations.append("RUNTIME_BASIS_MISSING")
    elif runtime_basis not in _SUPPORTED_RUNTIME_BASES:
        limitations.append("RUNTIME_BASIS_UNSUPPORTED")
    elif runtime_basis == "campaign_cap":
        limitations.append("CAMPAIGN_CAP_NOT_SCHEDULABLE")
    elif runtime_basis == "per_kloc" and target_loc_total <= 0:
        limitations.append("PER_KLOC_TARGET_LOC_MISSING")
    if target_version is None:
        limitations.append("TARGET_COMPILER_UNKNOWN")
    elif not compiler_match:
        limitations.append("COMPILER_BUCKET_MISMATCH")
    if loc_match is False:
        limitations.append("TARGET_LOC_BUCKET_ABSENT")
    if scene_weight <= 0.0:
        limitations.append("NO_SCENE_SUPPORT")
    return limitations


def _runtime_assessment(
    *,
    rows: list[_RuntimeRow],
    scene_weights: dict[str, float],
    kb: PerformanceKnowledgeBase,
    features: ContractFeatures,
    literature_summaries: list[RuntimeLiteratureSummary],
) -> _RuntimeEstimate:
    target_version = features.primary_solidity_version
    target_compiler_bucket = _compiler_bucket(target_version)
    target_loc_bucket = _loc_bucket(features.loc_total, kb.criteria)
    default_unit = kb.criteria.get("runtime_unit")
    default_basis = kb.criteria.get("runtime_basis_default")
    candidates: list[RuntimeCandidateEvidence] = []

    for row in sorted(rows, key=lambda item: (item.source_id, item.dataset_name)):
        runtime_unit = row.metric.runtime_unit or (
            str(default_unit) if default_unit is not None else None
        )
        runtime_basis = row.metric.runtime_basis or (
            str(default_basis) if default_basis is not None else None
        )
        compiler_match = bool(
            target_version
            and row.solc
            and any(
                version_in_range(target_version, version_spec)
                for version_spec in row.solc
            )
        )
        loc_match = _loc_match(
            row.loc_profile,
            target_loc_bucket=target_loc_bucket,
            target_version=target_version,
        )
        scene_weight = scene_weights.get(row.source_id, 0.0)
        limitations = _candidate_limitations(
            row,
            runtime_unit=runtime_unit,
            runtime_basis=runtime_basis,
            target_version=target_version,
            compiler_match=compiler_match,
            loc_match=loc_match,
            scene_weight=scene_weight,
            target_loc_total=features.loc_total,
        )
        if runtime_basis == "per_contract":
            schedulable_seconds = row.seconds
        elif runtime_basis == "per_kloc" and features.loc_total > 0:
            schedulable_seconds = row.seconds * features.loc_total / 1000.0
        else:
            schedulable_seconds = None
        if schedulable_seconds is not None and schedulable_seconds <= 0.0:
            schedulable_seconds = None
        candidates.append(
            RuntimeCandidateEvidence(
                source_id=row.source_id,
                dataset_name=row.dataset_name,
                metric_field=row.metric_field,
                source_runtime_seconds=row.seconds,
                schedulable_runtime_seconds=schedulable_seconds,
                runtime_unit=runtime_unit,
                runtime_basis=runtime_basis,
                scene_weight=scene_weight,
                compiler_match=compiler_match,
                loc_match=loc_match,
                sample_count=row.metric.sample_count,
                success_count=row.metric.success_count,
                timeout_count=row.metric.timeout_count,
                compilation_failure_count=row.metric.compilation_failure_count,
                failure_count=row.metric.failure_count,
                limitations=limitations,
            )
        )

    compatible = [
        candidate
        for candidate in candidates
        if default_unit == "seconds"
        and default_basis == "per_contract"
        and candidate.runtime_unit == "seconds"
        and candidate.runtime_basis in {"per_contract", "per_kloc"}
        and candidate.schedulable_runtime_seconds is not None
        and candidate.compiler_match
        and candidate.loc_match is not False
    ]
    exact_loc = [candidate for candidate in compatible if candidate.loc_match is True]
    exact_support = math.fsum(candidate.scene_weight for candidate in exact_loc)
    aggregate = exact_loc if exact_support >= MIN_RUNTIME_SUPPORT_MASS else compatible
    support_mass = clamp_normalized_mass(
        math.fsum(candidate.scene_weight for candidate in aggregate)
    )
    aggregate_ids = {candidate.source_id for candidate in aggregate}
    candidates = [
        candidate.model_copy(
            update={"included_in_quantile": candidate.source_id in aggregate_ids}
        )
        for candidate in candidates
    ]

    if not rows:
        status = "NO_RUNTIME_ROWS"
    elif default_unit is None:
        status = "RUNTIME_UNIT_MISSING"
    elif default_unit != "seconds":
        status = "RUNTIME_UNIT_UNSUPPORTED"
    elif default_basis is None:
        status = "RUNTIME_BASIS_MISSING"
    elif default_basis != "per_contract":
        status = "NO_COMPATIBLE_RUNTIME_EVIDENCE"
    elif target_compiler_bucket is None:
        status = "TARGET_COMPILER_UNKNOWN"
    elif not compatible:
        units = {candidate.runtime_unit for candidate in candidates}
        bases = {candidate.runtime_basis for candidate in candidates}
        if units == {None}:
            status = "RUNTIME_UNIT_MISSING"
        elif all(unit != "seconds" for unit in units):
            status = "RUNTIME_UNIT_UNSUPPORTED"
        elif bases == {None}:
            status = "RUNTIME_BASIS_MISSING"
        else:
            status = "NO_COMPATIBLE_RUNTIME_EVIDENCE"
    elif support_mass < MIN_RUNTIME_SUPPORT_MASS:
        status = "INSUFFICIENT_RUNTIME_SUPPORT"
    else:
        status = "QUALIFIED"

    limitations = list(
        dict.fromkeys(
            limitation
            for candidate in candidates
            for limitation in candidate.limitations
        )
    )
    limitations.append(
        "DATASET_LEVEL_PROXY_NOT_FINE_GRAINED_RUNTIME_CELL"
    )
    if status == "INSUFFICIENT_RUNTIME_SUPPORT":
        limitations.append("ORIGINAL_SCENE_SUPPORT_BELOW_0_2")
    evidence = RuntimeEvidenceAssessment(
        status=status,
        target_compiler_bucket=target_compiler_bucket,
        target_loc_bucket=target_loc_bucket,
        source_runtime_unit=str(default_unit) if default_unit is not None else None,
        runtime_basis_default=str(default_basis) if default_basis is not None else None,
        support_mass=support_mass,
        support_threshold=MIN_RUNTIME_SUPPORT_MASS,
        quantile=RUNTIME_QUANTILE,
        candidates=candidates,
        descriptive_literature_summaries=literature_summaries,
        limitations=list(dict.fromkeys(limitations)),
    )
    if status != "QUALIFIED":
        return _RuntimeEstimate(seconds=None, provenance=None, evidence=evidence)

    weighted_candidates = [
        candidate
        for candidate in candidates
        if candidate.included_in_quantile and candidate.scene_weight > 0.0
    ]
    ordered = sorted(
        weighted_candidates,
        key=lambda candidate: (
            candidate.schedulable_runtime_seconds or math.inf,
            candidate.source_id,
        ),
    )
    threshold = RUNTIME_QUANTILE * support_mass
    cumulative = 0.0
    selected = ordered[-1]
    for candidate in ordered:
        cumulative += candidate.scene_weight
        if cumulative >= threshold:
            selected = candidate
            break
    assert selected.schedulable_runtime_seconds is not None
    assert selected.runtime_basis in {"per_contract", "per_kloc"}
    provenance = RuntimeEstimateProvenance(
        method="scene_weighted_p90_compatible_dataset_proxy",
        selected_source_id=selected.source_id,
        selected_dataset_name=selected.dataset_name,
        selected_metric_field=selected.metric_field,
        selected_source_runtime_seconds=selected.source_runtime_seconds,
        selected_runtime_seconds=selected.schedulable_runtime_seconds,
        runtime_basis=selected.runtime_basis,
        target_compiler_bucket=target_compiler_bucket,
        target_loc_bucket=target_loc_bucket,
        support_mass=support_mass,
        support_threshold=MIN_RUNTIME_SUPPORT_MASS,
        quantile=RUNTIME_QUANTILE,
        candidate_source_ids=sorted({candidate.source_id for candidate in candidates}),
        candidates=candidates,
        limitations=evidence.limitations,
    )
    return _RuntimeEstimate(
        seconds=selected.schedulable_runtime_seconds,
        provenance=provenance,
        evidence=evidence,
    )


def _runtime_estimates(
    cards: list[ToolCard],
    kb: PerformanceKnowledgeBase,
    scene_pool: ScenePool,
    features: ContractFeatures,
) -> dict[str, _RuntimeEstimate]:
    """Resolve fail-closed runtime evidence from compatible scene-linked rows."""
    weights_by_source: dict[str, list[float]] = {}
    for neighbor in scene_pool.neighbors:
        if neighbor.paper_id is None:
            continue
        weights_by_source.setdefault(neighbor.paper_id, []).append(neighbor.weight)
    scene_weights = {
        source_id: clamp_normalized_mass(math.fsum(weights))
        for source_id, weights in weights_by_source.items()
    }

    rows_by_tool = _runtime_rows(cards, kb)
    aliases = _tool_aliases(cards)
    literature_by_tool: dict[str, list[RuntimeLiteratureSummary]] = {}
    for summary in kb.runtime_literature_summaries:
        tool = aliases.get(_tool_key(summary.tool))
        if tool is not None:
            literature_by_tool.setdefault(tool, []).append(summary)
    return {
        card.tool_id: _runtime_assessment(
            rows=rows_by_tool.get(card.tool_id, []),
            scene_weights=scene_weights,
            kb=kb,
            features=features,
            literature_summaries=literature_by_tool.get(card.tool_id, []),
        )
        for card in cards
    }


def _runtime_bucket(runtime_minutes: float | None) -> str:
    if runtime_minutes is None:
        return "unknown"
    if runtime_minutes < 5.0:
        return "low"
    if runtime_minutes < 30.0:
        return "medium"
    return "high"


def _family(card: ToolCard) -> str:
    mode = card.d8_mode.value
    if mode == "static":
        return "static_source" if card.d7_input_support.sol else "static_bytecode"
    if mode in {"symbolic", "fuzz", "ml", "llm"}:
        return mode
    return "unknown"


def _fuzz_campaign_for_budget(budget: BudgetProfile) -> FuzzCampaignBudget | None:
    """Resolve a positive, schedule-consistent campaign or fail closed."""
    schedule = budget.execution_schedule
    if schedule is None or budget.runtime_cap_minutes <= 0.0:
        return None
    if schedule.timeout_source == "budget_default" and not math.isclose(
        schedule.tool_timeout_seconds,
        budget.runtime_cap_minutes * 60.0,
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        return None
    return FuzzCampaignBudget(
        allocated_runtime_seconds=schedule.tool_timeout_seconds,
        timeout_source=schedule.timeout_source,
    )


def build_tool_table(
    cards: list[ToolCard],
    features: ContractFeatures,
    budget: BudgetProfile,
    kb: PerformanceKnowledgeBase,
    scene_pool: ScenePool,
) -> list[ToolTableEntry]:
    runtime_estimates = _runtime_estimates(cards, kb, scene_pool, features)
    entries: list[ToolTableEntry] = []
    for card in cards:
        feasibility = check_feasibility(card, features, budget)
        runtime_estimate = runtime_estimates.get(card.tool_id)
        historical_runtime_minutes = (
            runtime_estimate.seconds / 60.0
            if runtime_estimate is not None and runtime_estimate.seconds is not None
            else None
        )
        is_fuzz = card.d8_mode.value == "fuzz"
        fuzz_campaign_budget = _fuzz_campaign_for_budget(budget) if is_fuzz else None
        runtime_minutes = None if is_fuzz else historical_runtime_minutes
        entries.append(
            ToolTableEntry(
                tool=card.tool_id,
                family=_family(card),
                feasible=feasibility.feasible,
                feasibility_reasons=feasibility.reasons,
                expected_runtime_bucket=_runtime_bucket(runtime_minutes),
                failure_risk_bucket="unknown",
                tool_cost=ToolCostEntry(
                    tool_slots=1,
                    expected_runtime_minutes=runtime_minutes,
                    alert_risk=budget.alert_cap,
                    runtime_provenance=(
                        runtime_estimate.provenance
                        if runtime_estimate is not None and not is_fuzz
                        else None
                    ),
                    runtime_evidence=(
                        runtime_estimate.evidence
                        if runtime_estimate is not None
                        else None
                    ),
                    fuzz_campaign_budget=fuzz_campaign_budget,
                ),
            )
        )
    return entries


def _category_diagnostics(stage1: Stage1EvidencePacket) -> CategoryDiagnostics:
    profile: dict[str, float] = {}
    for neighbor in stage1.scene_pool.neighbors:
        for category, value in neighbor.category_profile.items():
            profile[category] = profile.get(category, 0.0) + neighbor.weight * value
    total = sum(profile.values())
    if total > 0.0:
        profile = {category: value / total for category, value in profile.items()}
    return CategoryDiagnostics(scene_category_profile=profile)


def _evidence_id(source_id: str, dataset_name: str, tool: str, category: str) -> str:
    def safe(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")

    return f"ev_dataset_{safe(source_id)}_{safe(dataset_name)}_{safe(tool)}_{safe(category)}"


def _performance_view(
    kb: PerformanceKnowledgeBase,
    tool_ids: list[str],
    required_categories: list[str],
    scene_densities: dict[str, float],
) -> list[PerformanceDBEvidenceRow]:
    requested = {_tool_key(tool): tool for tool in tool_ids}
    required = set(required_categories)
    rows: list[PerformanceDBEvidenceRow] = []
    for entry in kb.entries:
        density = scene_densities.get(entry.source_id)
        for observation in entry.tool_performance_data:
            tool = requested.get(_tool_key(observation.tool_name))
            if tool is None:
                continue
            counts = observation.vulnerability_score_counts or {}
            scores = observation.vulnerability_scores or {}
            for category in sorted(required & (set(counts) | set(scores))):
                count = counts.get(category)
                if count is not None and count.total > 0:
                    detected = count.detected
                    total = count.total
                    rate = detected / total
                    n_eff = density * total if density is not None else None
                else:
                    detected = None
                    total = None
                    rate = scores.get(category)
                    n_eff = None
                if rate is None:
                    continue
                rows.append(
                    PerformanceDBEvidenceRow(
                        evidence_id=_evidence_id(
                            entry.source_id,
                            entry.dataset_profile.dataset_name,
                            tool,
                            category,
                        ),
                        source_id=entry.source_id,
                        dataset_name=entry.dataset_profile.dataset_name,
                        tool=tool,
                        category=category,
                        detected=detected,
                        total=total,
                        R_hat=rate,
                        n_eff=n_eff,
                    )
                )
    rows.sort(
        key=lambda row: (
            row.category,
            -(row.R_hat if row.R_hat is not None else -1.0),
            -(row.n_eff or 0.0),
            row.tool,
            row.source_id,
        )
    )
    return rows


def _overall_metrics_view(
    kb: PerformanceKnowledgeBase,
    tool_ids: list[str],
) -> list[ToolOverallMetricsRow]:
    requested = {_tool_key(tool): tool for tool in tool_ids}
    rows: list[ToolOverallMetricsRow] = []
    seen: set[tuple[str, str]] = set()
    for entry in kb.entries:
        for observation in entry.tool_performance_data:
            tool = requested.get(_tool_key(observation.tool_name))
            if tool is None or (tool, entry.source_id) in seen:
                continue
            metric = observation.metrics
            if metric.precision is None and metric.recall is None and metric.f1 is None:
                continue
            seen.add((tool, entry.source_id))
            rows.append(
                ToolOverallMetricsRow(
                    evidence_id=f"ev_overall_{entry.source_id}_{_tool_key(tool)}",
                    source_id=entry.source_id,
                    dataset_name=entry.dataset_profile.dataset_name,
                    tool=tool,
                    precision=metric.precision,
                    recall=metric.recall,
                    f1=metric.f1,
                    execution_time_avg=metric.resolved_time_sec,
                )
            )
    rows.sort(key=lambda row: (row.tool, row.source_id))
    return rows


def decide_primary_categories(
    context_rows,
    *,
    primary_tool: str,
    required_categories: list[str],
) -> list[PrimaryCategoryDecision]:
    """Classify the one legal Stage 2 search gate for each category."""
    by_key = {(row.tool, row.category): row for row in context_rows}
    tools = sorted({row.tool for row in context_rows})
    decisions: list[PrimaryCategoryDecision] = []

    for category in required_categories:
        primary = by_key.get((primary_tool, category))
        if primary is None:
            decisions.append(
                PrimaryCategoryDecision(
                    category=category,
                    status="SEARCH_REQUIRED",
                    evidence_classification="under_evidenced",
                    reason_codes=["PRIMARY_CATEGORY_ROW_MISSING"],
                )
            )
            continue
        if primary.n_eff is None:
            decisions.append(
                PrimaryCategoryDecision(
                    category=category,
                    status="SEARCH_REQUIRED",
                    evidence_classification="under_evidenced",
                    reason_codes=["PRIMARY_N_EFF_MISSING"],
                    primary_rate=primary.R_hat,
                    primary_n_eff=primary.n_eff,
                )
            )
            continue
        if primary.n_eff < MIN_N_EFF:
            decisions.append(
                PrimaryCategoryDecision(
                    category=category,
                    status="SEARCH_REQUIRED",
                    evidence_classification="under_evidenced",
                    reason_codes=["PRIMARY_N_EFF_BELOW_15"],
                    primary_rate=primary.R_hat,
                    primary_n_eff=primary.n_eff,
                )
            )
            continue
        if primary.R_hat is None:
            decisions.append(
                PrimaryCategoryDecision(
                    category=category,
                    status="SEARCH_REQUIRED",
                    evidence_classification="under_evidenced",
                    reason_codes=["PRIMARY_CATEGORY_RATE_MISSING"],
                    primary_rate=primary.R_hat,
                    primary_n_eff=primary.n_eff,
                )
            )
            continue
        if primary.R_hat <= 0.0:
            decisions.append(
                PrimaryCategoryDecision(
                    category=category,
                    status="SEARCH_REQUIRED",
                    evidence_classification="confirmed_weak",
                    reason_codes=["PRIMARY_CATEGORY_RATE_NON_POSITIVE"],
                    primary_rate=primary.R_hat,
                    primary_n_eff=primary.n_eff,
                )
            )
            continue

        credible: list[tuple[float, object]] = []
        for tool in tools:
            if tool == primary_tool or (tool, category) not in by_key:
                continue
            peer = by_key[(tool, category)]
            strength = complement_strength_against_primary(
                candidate_rate=peer.R_hat,
                candidate_n_eff=peer.n_eff,
                primary_rate=primary.R_hat,
                primary_n_eff=primary.n_eff,
            )
            if strength.evidence_stronger and strength.recall_gap_low is not None:
                credible.append((strength.recall_gap_low, peer))
        if credible:
            low, peer = max(
                credible,
                key=lambda item: (
                    item[0],
                    item[1].R_hat or 0.0,
                    item[1].n_eff or 0.0,
                    item[1].tool,
                ),
            )
            decisions.append(
                PrimaryCategoryDecision(
                    category=category,
                    status="SEARCH_REQUIRED",
                    evidence_classification="confirmed_weak",
                    reason_codes=["PEER_RECALL_CREDIBLY_HIGHER"],
                    primary_rate=primary.R_hat,
                    primary_n_eff=primary.n_eff,
                    credible_peer_tool=peer.tool,
                    credible_peer_gap_low=low,
                )
            )
        else:
            decisions.append(
                PrimaryCategoryDecision(
                    category=category,
                    status="PRIMARY_SUFFICIENT",
                    evidence_classification="sufficient",
                    reason_codes=["PRIMARY_COUNT_EVIDENCE_SUFFICIENT"],
                    primary_rate=primary.R_hat,
                    primary_n_eff=primary.n_eff,
                )
            )
    return decisions


def _focus_items(
    rows,
    *,
    primary_tool: str,
    required_categories: list[str],
    decisions: list[PrimaryCategoryDecision],
) -> list[DACERAGFocusItem]:
    focus: list[DACERAGFocusItem] = []
    by_key = {(row.tool, row.category): row for row in rows}
    search_required = {
        decision.category
        for decision in decisions
        if decision.status == "SEARCH_REQUIRED"
    }
    for category in required_categories:
        if category not in search_required:
            continue
        primary = by_key.get((primary_tool, category))
        candidates = [
            row
            for row in rows
            if row.category == category
            and row.tool != primary_tool
            and complement_strength_against_primary(
                candidate_rate=row.R_hat,
                candidate_n_eff=row.n_eff,
                primary_rate=primary.R_hat if primary else None,
                primary_n_eff=primary.n_eff if primary else None,
            ).evidence_stronger
        ]
        candidates.sort(key=lambda row: (-(row.R_hat or 0.0), -(row.n_eff or 0.0), row.tool))
        for row in candidates[:3]:
            focus.append(
                DACERAGFocusItem(
                    tool=row.tool,
                    category=category,
                    reason="category_complement_candidate_n_eff_at_least_15",
                )
            )
    return focus


def build_stage2_context(
    stage1: Stage1EvidencePacket,
    kb: PerformanceKnowledgeBase,
    required_categories: list[str],
) -> Stage2EvidenceContext:
    """Build category evidence only after Stage 1 has fixed ``t^star``."""
    if stage1.primary_selection.status != Stage1Status.PRIMARY_SELECTED:
        raise ValueError("Stage 2 requires a selected Stage 1 primary")
    primary_tool = stage1.primary_selection.primary_tool
    assert primary_tool is not None

    required = list(
        dict.fromkeys(
            category
            for category in (normalize_category(value) for value in required_categories)
            if category in _DASP10
        )
    )
    tool_ids = [entry.tool for entry in stage1.tool_table]
    scene_densities = {
        neighbor.paper_id: neighbor.kernel_density
        for neighbor in stage1.scene_pool.neighbors
        if neighbor.paper_id is not None
    }
    recall_coverage = build_recall_coverage(
        kb,
        tool_ids,
        scene_densities=scene_densities,
    )
    decisions = decide_primary_categories(
        recall_coverage.matrix,
        primary_tool=primary_tool,
        required_categories=required,
    )
    confirmed_weak = [
        decision.category
        for decision in decisions
        if decision.evidence_classification == "confirmed_weak"
    ]
    under_evidenced = [
        decision.category
        for decision in decisions
        if decision.evidence_classification == "under_evidenced"
    ]
    reasons = [
        f"{decision.category}:{reason}"
        for decision in decisions
        for reason in decision.reason_codes
        if decision.status == "SEARCH_REQUIRED"
    ]
    attention = PrimaryAttention(
        primary_tool=primary_tool,
        required_categories=required,
        confirmed_weak_categories=confirmed_weak,
        under_evidenced_categories=under_evidenced,
        reason_codes=reasons,
    )
    return Stage2EvidenceContext(
        stage1=stage1,
        required_categories=required,
        category_diagnostics=_category_diagnostics(stage1),
        recall_coverage=recall_coverage,
        performance_db_view=_performance_view(
            kb,
            tool_ids,
            required,
            scene_densities,
        ),
        tool_overall_metrics=_overall_metrics_view(kb, tool_ids),
        primary_category_decisions=decisions,
        primary_attention=attention,
        dace_rag_focus=_focus_items(
            recall_coverage.matrix,
            primary_tool=primary_tool,
            required_categories=required,
            decisions=decisions,
        ),
    )
