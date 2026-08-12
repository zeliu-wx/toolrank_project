"""Shared evidence rules for additive Stage 2 category ownership."""

from __future__ import annotations

from toolrank.assignment_evidence import (
    MAX_COMPLEMENT_CANDIDATES,
    complement_strength_against_primary,
)
from toolrank.plan_runtime import estimated_budget, within_budget
from toolrank.schemas_v2 import (
    BudgetProfile,
    CategoryOwnershipPanel,
    ComplementStrengthResult,
    EvidenceCard,
    OwnerCandidateEvidence,
    RecallCoverageEntry,
    Stage2EvidenceContext,
)


def category_group(context: Stage2EvidenceContext, category: str) -> str:
    if category in context.primary_attention.confirmed_weak_categories:
        return "confirmed_weak"
    if category in context.primary_attention.under_evidenced_categories:
        return "under_evidenced"
    return "required"


def rcov_evidence_id(tool: str, category: str) -> str:
    return f"ev_rcov_{tool}_{category}"


def category_capability_pro_refs(
    cards: list[EvidenceCard], *, tool: str, category: str
) -> list[str]:
    return [
        card.evidence_id
        for card in cards
        if card.tool == tool
        and card.category == category
        and card.evidence_type == "rag_passage"
        and card.scope.get("knowledge_kind") == "category_capability"
        and card.scope.get("relation_to_owner") in {"supports_owner", "owner_stronger"}
    ]


def applicable_owner_ineligible_refs(
    cards: list[EvidenceCard], *, tool: str, category: str
) -> list[str]:
    return [
        card.evidence_id
        for card in cards
        if card.tool == tool
        and card.category in {category, "__GLOBAL__"}
        and card.evidence_type == "rag_passage"
        and card.scope.get("relation_to_owner") == "owner_ineligible"
        and card.scope.get("applies_to_target") is True
    ]


def candidate_caveat_refs(
    cards: list[EvidenceCard], *, tool: str, category: str
) -> list[str]:
    return [
        card.evidence_id
        for card in cards
        if card.tool == tool
        and card.category in {category, "__GLOBAL__"}
        and card.decision_role in {"oppose", "constraint", "caveat"}
    ]


def _candidate(
    *,
    tool: str,
    category: str,
    eligibility: str,
    row: RecallCoverageEntry | None,
    evidence_refs: list[str],
    caveat_refs: list[str],
    strength: ComplementStrengthResult,
) -> OwnerCandidateEvidence:
    return OwnerCandidateEvidence(
        tool=tool,
        category=category,
        eligibility=eligibility,
        evidence_scope="local",
        evidence_refs=evidence_refs,
        caveat_refs=caveat_refs,
        detected=row.detected if row else None,
        total=row.total if row else None,
        rate=row.R_hat if row else None,
        n_eff=row.n_eff if row else None,
        strength=strength,
    )


def category_ownership_panel(
    context: Stage2EvidenceContext,
    cards: list[EvidenceCard],
    category: str,
    budget: BudgetProfile,
) -> CategoryOwnershipPanel:
    """Build the auditable candidate slate for one required category."""
    primary = context.stage1.primary_selection.primary_tool
    decision = next(
        item
        for item in context.primary_category_decisions
        if item.category == category
    )
    if decision.status == "PRIMARY_SUFFICIENT":
        return CategoryOwnershipPanel(
            category=category,
            diagnostic=category_group(context, category),
            primary_decision=decision,
            assignment_status="PRIMARY_SUFFICIENT",
            primary_only_reason="PRIMARY_CATEGORY_EVIDENCE_SUFFICIENT",
        )
    rows = {(row.tool, row.category): row for row in context.recall_coverage.matrix}
    primary_row = rows.get((primary, category)) if primary else None
    eligible: list[OwnerCandidateEvidence] = []
    under: list[OwnerCandidateEvidence] = []
    rejected: list[OwnerCandidateEvidence] = []

    for entry in sorted(context.stage1.tool_table, key=lambda item: item.tool):
        tool = entry.tool
        if tool == primary:
            continue
        row = rows.get((tool, category))
        base_ref = [rcov_evidence_id(tool, category)] if row is not None else []
        pro_refs = category_capability_pro_refs(cards, tool=tool, category=category)
        hard_refs = applicable_owner_ineligible_refs(cards, tool=tool, category=category)
        caveat_refs = candidate_caveat_refs(cards, tool=tool, category=category)
        refs = list(dict.fromkeys([*base_ref, *pro_refs]))
        strength = complement_strength_against_primary(
            candidate_rate=row.R_hat if row else None,
            candidate_n_eff=row.n_eff if row else None,
            primary_rate=primary_row.R_hat if primary_row else None,
            primary_n_eff=primary_row.n_eff if primary_row else None,
        )

        estimate = (
            estimated_budget(
                [primary, tool],
                context.stage1.tool_table,
                budget.execution_schedule,
            )
            if primary
            else None
        )
        runtime_ok = estimate is not None and within_budget(estimate, budget)
        count_ok = strength.candidate_count_qualified
        if (
            entry.feasible
            and strength.evidence_stronger
            and runtime_ok
            and not hard_refs
        ):
            eligible.append(
                _candidate(
                    tool=tool,
                    category=category,
                    eligibility="eligible",
                    row=row,
                    evidence_refs=refs,
                    caveat_refs=caveat_refs,
                    strength=strength,
                )
            )
        elif entry.feasible and row is not None and row.R_hat and not count_ok:
            under.append(
                _candidate(
                    tool=tool,
                    category=category,
                    eligibility="under_evidenced",
                    row=row,
                    evidence_refs=refs,
                    caveat_refs=caveat_refs,
                    strength=strength,
                )
            )
        else:
            rejected.append(
                _candidate(
                    tool=tool,
                    category=category,
                    eligibility="ineligible",
                    row=row,
                    evidence_refs=refs,
                    caveat_refs=caveat_refs,
                    strength=strength,
                )
            )

    sort_key = lambda item: (-(item.rate or 0.0), -(item.n_eff or 0.0), item.tool)
    eligible.sort(key=sort_key)
    under.sort(key=sort_key)
    rejected.sort(key=sort_key)
    not_shortlisted = [
        candidate.model_copy(update={"eligibility": "not_shortlisted"})
        for candidate in eligible[MAX_COMPLEMENT_CANDIDATES:]
    ]
    eligible = eligible[:MAX_COMPLEMENT_CANDIDATES]
    if eligible:
        status = "COMPLEMENT_AVAILABLE"
        reason = ""
    else:
        status = "PRIMARY_ONLY_NO_COMPLEMENT"
        reason = (
            "PRIMARY_COMPARISON_BASELINE_UNRELIABLE"
            if any(
                item.strength.basis == "PRIMARY_BASELINE_UNRELIABLE"
                for item in rejected
            )
            else "NO_EVIDENCE_STRONGER_COMPLEMENT_WITH_VERIFIABLE_BUDGET"
        )
    return CategoryOwnershipPanel(
        category=category,
        diagnostic=category_group(context, category),
        primary_decision=decision,
        assignment_status=status,
        eligible_candidates=eligible,
        not_shortlisted_candidates=not_shortlisted,
        under_evidenced_candidates=under,
        rejected_candidates=rejected,
        primary_only_reason=reason,
    )
