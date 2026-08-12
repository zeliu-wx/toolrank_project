"""Deterministic checker for Stage 2 decision certificates."""

from __future__ import annotations

import math

from toolrank.action_contract import action_id_for
from toolrank.assignment_evidence import complement_strength_against_primary
from toolrank.ownership_evidence import category_ownership_panel
from toolrank.plan_runtime import (
    budget_usage,
    estimated_budget,
    planning_runtime_minutes,
    within_budget,
)
from toolrank.schemas_v2 import (
    ActionByEvidenceMatrix,
    CheckerVerdict,
    EvidenceCard,
    Stage2EvidenceContext,
    Step2DecisionCertificate,
)


def _add(failures: list[str], code: str) -> None:
    if code not in failures:
        failures.append(code)


def _relevant(card: EvidenceCard, *, tool: str, category: str) -> bool:
    return card.tool == tool and card.category in {category, "__GLOBAL__"}


def _applies(card: EvidenceCard) -> bool:
    if card.evidence_type != "rag_passage":
        return True
    value = card.scope.get("applies_to_target")
    return value is not False


def _evidence_balance(
    matrix: ActionByEvidenceMatrix,
    cited_refs: list[str],
    *,
    tool: str,
    category: str,
) -> tuple[float, float]:
    by_id = {card.evidence_id: card for card in matrix.evidence_cards}
    evaluations = {
        row.evaluation_id: row
        for tool_evidence in matrix.stage1_evidence.tools.values()
        for row in tool_evidence.benchmark_evaluations
    }
    positive_ids: set[str] = set()
    for ref in cited_refs:
        card = by_id.get(ref)
        if (
            card is None
            or not _relevant(card, tool=tool, category=category)
            or not _applies(card)
        ):
            continue
        if card.decision_role in {"support", "compare"}:
            positive_ids.update(card.linked_evaluation_ids)

    negative_ids: set[str] = set()
    for card in matrix.evidence_cards:
        if not _relevant(card, tool=tool, category=category) or not _applies(card):
            continue
        if card.decision_role in {"oppose", "constraint"}:
            negative_ids.update(card.linked_evaluation_ids)
    positive = math.fsum(evaluations[evaluation_id].w_D for evaluation_id in positive_ids)
    negative = math.fsum(evaluations[evaluation_id].w_D for evaluation_id in negative_ids)
    return positive, negative


def check_decision(
    certificate: Step2DecisionCertificate,
    context: Stage2EvidenceContext,
    matrix: ActionByEvidenceMatrix,
) -> CheckerVerdict:
    """Verify ownership, grounding, and max-runtime budget invariants."""
    failures: list[str] = []
    expected_primary = context.stage1.primary_selection.primary_tool
    if not expected_primary or certificate.primary_tool != expected_primary:
        _add(failures, "PRIMARY_TOOL_NOT_STAGE1_PRIMARY")

    actions = {action.action_id: action for action in matrix.actions}
    action = actions.get(certificate.selected_action_id)
    if action is None:
        _add(failures, "UNKNOWN_ACTION_ID")
    else:
        if action.action_type != certificate.decision_type:
            _add(failures, "ACTION_TYPE_MISMATCH")
        if not action.legal:
            _add(failures, "SELECTED_ACTION_NOT_LEGAL")

    required = list(dict.fromkeys(context.required_categories))
    canonical_panels = {
        category: category_ownership_panel(
            context,
            matrix.evidence_cards,
            category,
            matrix.budget_profile,
        )
        for category in required
    }
    if set(matrix.ownership_panel) != set(required):
        _add(failures, "OWNERSHIP_PANEL_SCOPE_MISMATCH")
    for category, canonical_panel in canonical_panels.items():
        if matrix.ownership_panel.get(category) != canonical_panel:
            _add(failures, f"OWNERSHIP_PANEL_NOT_CANONICAL:{category}")

    assignments = {assignment.category: assignment for assignment in certificate.category_assignments}
    if len(assignments) != len(certificate.category_assignments) or set(assignments) != set(required):
        _add(failures, "CATEGORY_SCOPE_MISMATCH")

    table = {entry.tool: entry for entry in context.stage1.tool_table}
    rcov = {(row.tool, row.category): row for row in context.recall_coverage.matrix}
    cards_by_id = {card.evidence_id: card for card in matrix.evidence_cards}
    selected_tools = [expected_primary] if expected_primary else []
    any_complement = False

    for category in required:
        assignment = assignments.get(category)
        if assignment is None:
            continue
        if not assignment.owner_tools or assignment.owner_tools[0] != expected_primary:
            _add(failures, f"PRIMARY_OWNER_MISSING:{category}")
            continue
        if len(assignment.owner_tools) == 1:
            if assignment.complement_tool is not None or assignment.status != "PRIMARY_ONLY":
                _add(failures, f"PRIMARY_ONLY_ASSIGNMENT_INVALID:{category}")
            continue

        any_complement = True
        complement = assignment.owner_tools[1]
        decision = next(
            (
                item
                for item in context.primary_category_decisions
                if item.category == category
            ),
            None,
        )
        if decision is None or decision.status != "SEARCH_REQUIRED":
            _add(failures, f"COMPLEMENT_SEARCH_NOT_REQUIRED:{category}")
        if complement not in selected_tools:
            selected_tools.append(complement)
        if assignment.complement_tool != complement or assignment.status != "COMPLEMENT_ADDED":
            _add(failures, f"COMPLEMENT_ASSIGNMENT_INVALID:{category}")

        panel = canonical_panels.get(category)
        eligible = {
            candidate.tool: candidate
            for candidate in (panel.eligible_candidates if panel else [])
        }
        if complement not in eligible:
            _add(failures, f"COMPLEMENT_NOT_IN_ELIGIBLE_PANEL:{category}:{complement}")

        entry = table.get(complement)
        if entry is None or not entry.feasible:
            _add(failures, f"COMPLEMENT_NOT_FEASIBLE:{category}:{complement}")
        elif planning_runtime_minutes(entry) is None:
            _add(failures, f"COMPLEMENT_RUNTIME_UNKNOWN:{category}:{complement}")

        row = rcov.get((complement, category))
        primary_row = rcov.get((expected_primary, category)) if expected_primary else None
        strength = complement_strength_against_primary(
            candidate_rate=row.R_hat if row else None,
            candidate_n_eff=row.n_eff if row else None,
            primary_rate=primary_row.R_hat if primary_row else None,
            primary_n_eff=primary_row.n_eff if primary_row else None,
        )
        if not strength.candidate_count_qualified:
            _add(failures, f"COMPLEMENT_COUNT_EVIDENCE_INELIGIBLE:{category}:{complement}")
        elif not strength.evidence_stronger:
            _add(
                failures,
                f"COMPLEMENT_NOT_EVIDENCE_STRONGER_THAN_PRIMARY:{category}:{complement}",
            )
        panel_candidate = eligible.get(complement)
        if panel_candidate is not None and panel_candidate.strength != strength:
            _add(failures, f"COMPLEMENT_STRENGTH_RESULT_MISMATCH:{category}:{complement}")

        refs = [
            ref
            for claim in assignment.for_claims
            for ref in claim.evidence_refs
        ]
        if not refs:
            _add(failures, f"COMPLEMENT_SUPPORT_REF_MISSING:{category}:{complement}")
        for ref in refs:
            card = cards_by_id.get(ref)
            if card is None:
                _add(failures, f"EVIDENCE_REF_NOT_FOUND:{ref}")
            elif not _relevant(card, tool=complement, category=category):
                _add(failures, f"EVIDENCE_REF_NOT_RELEVANT:{ref}")

        hard_blocks = [
            card.evidence_id
            for card in matrix.evidence_cards
            if _relevant(card, tool=complement, category=category)
            and card.evidence_type == "rag_passage"
            and card.scope.get("relation_to_owner") == "owner_ineligible"
            and _applies(card)
        ]
        if hard_blocks:
            _add(failures, f"APPLICABLE_OWNER_INELIGIBLE:{category}:{complement}")

        positive, negative = _evidence_balance(
            matrix,
            refs,
            tool=complement,
            category=category,
        )
        if positive <= negative:
            _add(failures, f"EVIDENCE_BALANCE_NOT_POSITIVE:{category}:{complement}")

    expected_type = "PLAN_COMPOSITION" if any_complement else "RUN_PRIMARY"
    if certificate.decision_type != expected_type:
        _add(failures, "DECISION_TYPE_DOES_NOT_MATCH_ASSIGNMENTS")
    if certificate.selected_action_id != action_id_for(expected_type):
        _add(failures, "ACTION_ID_DOES_NOT_MATCH_ASSIGNMENTS")

    planned_tools = [entry.tool for entry in certificate.selected_plan]
    if planned_tools != selected_tools or len(planned_tools) != len(set(planned_tools)):
        _add(failures, "SELECTED_PLAN_DOES_NOT_MATCH_OWNERS")
    if certificate.selected_plan:
        first = certificate.selected_plan[0]
        if first.tool != expected_primary or first.role != "STARTER":
            _add(failures, "SELECTED_PLAN_PRIMARY_INVALID")
        if any(entry.role != "COMPLEMENT" for entry in certificate.selected_plan[1:]):
            _add(failures, "SELECTED_PLAN_COMPLEMENT_ROLE_INVALID")

    estimate = estimated_budget(
        selected_tools,
        context.stage1.tool_table,
        matrix.budget_profile.execution_schedule,
    )
    if estimate is None:
        _add(failures, "PLAN_RUNTIME_UNVERIFIABLE")
    elif not within_budget(estimate, matrix.budget_profile):
        _add(failures, "PLAN_EXCEEDS_BUDGET")
    expected_usage = budget_usage(selected_tools, context.stage1.tool_table, matrix.budget_profile)
    if expected_usage is None or certificate.budget != expected_usage:
        _add(failures, "BUDGET_ACCOUNTING_MISMATCH")

    attestation = certificate.forbidden_claims_attestation
    if not all(
        (
            attestation.no_target_vulnerability_claim,
            attestation.no_code_semantic_inference,
            attestation.no_precision_from_detected_total,
            attestation.absence_of_findings_not_treated_as_safe,
            attestation.no_unsourced_numeric_gain,
        )
    ):
        _add(failures, "FORBIDDEN_CLAIMS_ATTESTATION_FAILED")

    if failures:
        return CheckerVerdict(
            status="REJECT",
            checked_action_id=certificate.selected_action_id,
            rule_failures=failures,
            reasons=["Decision certificate violates one or more Stage 2 invariants."],
            hard_failures=[
                code
                for code in failures
                if code.startswith(("PRIMARY_", "APPLICABLE_OWNER_INELIGIBLE", "PLAN_"))
            ],
            regeneration_reasons=failures,
        )
    return CheckerVerdict(
        status="ACCEPT",
        checked_action_id=certificate.selected_action_id,
        reasons=["Primary ownership, complement evidence, and parallel budget are valid."],
    )
