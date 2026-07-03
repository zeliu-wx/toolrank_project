"""Checker: multi-rule legality auditor for CEGO decisions."""

from __future__ import annotations

from toolrank.ownership_evidence import (
    category_capability_pro_refs,
)
from toolrank.schemas import DASP10_CATEGORIES
from toolrank.schemas_v2 import (
    ActionByEvidenceMatrix,
    ActionEvidenceClaim,
    CandidateAction,
    CheckerVerdict,
    Step1EvidencePacket,
    Step2DecisionCertificate,
)


Failure = tuple[str, str]
ALL_CATEGORY = "ALL"


def _action_by_id(matrix: ActionByEvidenceMatrix) -> dict[str, CandidateAction]:
    return {action.action_id: action for action in matrix.actions}


def _selected_action(
    certificate: Step2DecisionCertificate,
    matrix: ActionByEvidenceMatrix,
) -> CandidateAction | None:
    return _action_by_id(matrix).get(certificate.selected_action_id)


def _all_claims(certificate: Step2DecisionCertificate) -> list[ActionEvidenceClaim]:
    claims: list[ActionEvidenceClaim] = []
    for assignment in certificate.category_assignments:
        claims += (
            assignment.for_claims
            + assignment.against_claims
            + assignment.compare_claims
            + assignment.gap_claims
        )
    return claims


def _check_action_legality(
    certificate: Step2DecisionCertificate,
    packet: Step1EvidencePacket,
    matrix: ActionByEvidenceMatrix,
) -> list[Failure]:
    failures: list[Failure] = []
    action = _selected_action(certificate, matrix)
    if action is None:
        failures.append(
            ("ACTION_NOT_IN_MATRIX", "Selected action is not present in the action matrix.")
        )
    elif not action.legal:
        failures.append(
            ("ACTION_ILLEGAL_IN_MATRIX", "Selected action is marked illegal in the action matrix.")
        )

    feasible_by_tool = {entry.tool: entry.feasible for entry in packet.tool_table}
    seen_tools: set[str] = set()
    duplicate_tools: set[str] = set()
    for item in certificate.selected_plan:
        if not feasible_by_tool.get(item.tool, False):
            failures.append(
                (
                    f"TOOL_NOT_FEASIBLE:{item.tool}",
                    f"Selected tool is missing from the feasible tool table: {item.tool}.",
                )
            )
        if item.tool in seen_tools and item.tool not in duplicate_tools:
            duplicate_tools.add(item.tool)
            failures.append((f"DUPLICATE_TOOL:{item.tool}", f"Selected plan repeats tool: {item.tool}."))
        seen_tools.add(item.tool)

    if certificate.budget.estimated_use.tool_slots > certificate.budget.limit.tool_slots:
        failures.append(
            (
                "BUDGET_TOOL_SLOTS_EXCEEDED",
                "Estimated tool slots exceed the configured tool slot limit.",
            )
        )
    if (
        certificate.budget.estimated_use.runtime_cap_minutes
        > certificate.budget.limit.runtime_cap_minutes
    ):
        failures.append(
            (
                "BUDGET_RUNTIME_EXCEEDED",
                "Estimated runtime exceeds the configured runtime cap.",
            )
        )
    return failures


def _check_evidence_legality(
    certificate: Step2DecisionCertificate,
    matrix: ActionByEvidenceMatrix,
) -> list[Failure]:
    legal_refs = {card.evidence_id for card in matrix.evidence_cards}
    failures: list[Failure] = []
    for claim in _all_claims(certificate):
        for ref in claim.evidence_refs:
            if ref in legal_refs or ref.startswith("step1."):
                continue
            failures.append((f"UNRESOLVABLE_REF:{ref}", f"Evidence reference cannot be resolved: {ref}."))
    return failures


def _action_type(
    certificate: Step2DecisionCertificate,
    matrix: ActionByEvidenceMatrix,
) -> str:
    action = _selected_action(certificate, matrix)
    return action.action_type if action is not None else certificate.decision_type


def _selected_tools(certificate: Step2DecisionCertificate) -> set[str]:
    return {item.tool for item in certificate.selected_plan}


def _check_evidence_completeness(
    certificate: Step2DecisionCertificate,
    matrix: ActionByEvidenceMatrix,
) -> list[Failure]:
    action_type = _action_type(certificate, matrix)

    if action_type == "RUN_ROBUST_SINGLE":
        has_ranking_or_bias_ref = any(
            ref.startswith("ev_scene_")
            or ref.startswith("step1.score_panel")
            or ref.startswith("step1.category_diagnostics")
            for claim in _all_claims(certificate)
            for ref in claim.evidence_refs
        )
        if not has_ranking_or_bias_ref:
            return [
                (
                    "NO_RANKING_OR_BIAS_EVIDENCE",
                    "RUN_ROBUST_SINGLE requires ranking or category-bias evidence.",
                )
            ]
    return []


def _has_composition_fields(certificate: Step2DecisionCertificate) -> bool:
    return bool(
        certificate.primary_tool
        or certificate.tool_categories
    )


def _is_all_category(category: str) -> bool:
    return category.upper() == ALL_CATEGORY


def _rag_assignment_refs(matrix: ActionByEvidenceMatrix, *, category: str, tool: str) -> set[str]:
    return set(category_capability_pro_refs(matrix, category=category, tool=tool))


def _has_direction_evidence(
    certificate: Step2DecisionCertificate,
    matrix: ActionByEvidenceMatrix,
    *,
    category: str,
    tool: str,
) -> bool:
    """Direction check: does the cert cite ≥1 card that SUPPORTS this owner for this category?

    Scoped to the matching assignment's FOR + COMPARE slots only (paper §III-B2): a
    supporting ref placed only in AGAINST/GAP does NOT satisfy direction. Any
    recall-coverage card for the same tool+category counts (ANY rate); RAG pro/
    owner-stronger refs also count.
    """
    assignment = next(
        (
            a
            for a in certificate.category_assignments
            if a.category == category and a.owner_tool == tool
        ),
        None,
    )
    if assignment is None:
        return False
    refs = {
        ref
        for claim in (assignment.for_claims + assignment.compare_claims)
        for ref in claim.evidence_refs
    }
    for card in matrix.evidence_cards:
        if card.evidence_id not in refs:
            continue
        if (
            card.evidence_type == "per_category_detected_total"
            and card.tool == tool
            and card.category == category
            and card.value is not None
        ):
            return True
    return bool(refs & _rag_assignment_refs(matrix, category=category, tool=tool))



def _check_assignment_caveats(certificate: Step2DecisionCertificate) -> list[Failure]:
    failures: list[Failure] = []
    for assignment in certificate.category_assignments:
        if assignment.assignment_type in {"gap", "stop_with_gap"} or not assignment.owner_tool:
            continue
        if assignment.unrelated_external_only and not assignment.caveat_refs:
            failures.append(
                (
                    f"unrelated_external_only_assignment_missing_caveat:{assignment.owner_tool}/{assignment.category}",
                    f"Unrelated-external-only assignment is missing caveat refs: {assignment.owner_tool}/{assignment.category}.",
                )
            )
    return failures


def _check_composition_action_legality(
    certificate: Step2DecisionCertificate,
    packet: Step1EvidencePacket,
    matrix: ActionByEvidenceMatrix,
) -> list[Failure]:
    if not _has_composition_fields(certificate):
        return []
    action = _selected_action(certificate, matrix)
    if action is None:
        return []

    step1_anchor = packet.primary_attention.primary_tool
    if step1_anchor:
        pass
    elif packet.certification.certified_primary:
        step1_anchor = packet.certification.certified_primary
    elif packet.certification.candidate_set:
        step1_anchor = packet.certification.candidate_set[0]
    elif packet.score_panel.nominal_scores:
        step1_anchor = sorted(packet.score_panel.nominal_scores, key=lambda item: item.rank)[0].tool
    if step1_anchor and certificate.primary_tool != step1_anchor:
        return [
            (
                "PRIMARY_TOOL_NOT_STEP1_ANCHOR",
                "Composition primary_tool must equal the Step1 anchor.",
            )
        ]

    if action.action_type != "PLAN_COMPOSITION" and action.tools and certificate.primary_tool != action.tools[0]:
        return [
            (
                "PRIMARY_TOOL_NOT_ACTION_ANCHOR",
                "Composition primary_tool must equal the first tool in the selected action.",
            )
        ]
    return []


def _check_composition_completeness(
    certificate: Step2DecisionCertificate,
    packet: Step1EvidencePacket,
    matrix: ActionByEvidenceMatrix,
) -> list[Failure]:
    if not _has_composition_fields(certificate):
        return []
    action = _selected_action(certificate, matrix)
    if action is None:
        return []

    failures: list[Failure] = []
    primary = certificate.primary_tool
    selected_tools = _selected_tools(certificate)
    packet_primary_attention_categories = (
        set(packet.primary_attention.confirmed_weak_categories)
        | set(packet.primary_attention.low_support_categories)
        | set(packet.primary_attention.user_mandated_categories)
    )
    if primary and primary not in selected_tools:
        failures.append(
            (
                "PRIMARY_TOOL_NOT_SELECTED",
                "Primary tool must be included in selected_plan.",
            )
        )
    primary_categories = certificate.tool_categories.get(primary or "", [])
    if primary and not any(_is_all_category(category) for category in primary_categories):
        failures.append(
            (
                "PRIMARY_TOOL_MISSING_ALL",
                "Primary tool must own ALL in tool_categories.",
            )
        )

    for tool, categories in certificate.tool_categories.items():
        if tool == primary:
            continue
        if any(_is_all_category(category) for category in categories):
            failures.append(
                (
                    f"COMPLEMENT_TOOL_HAS_ALL:{tool}",
                    "Complement tools must own specific vulnerability categories, not ALL.",
                )
            )

    for tool, categories in certificate.tool_categories.items():
        if tool == primary:
            continue
        for category in categories:
            if _is_all_category(category):
                continue
            if category not in DASP10_CATEGORIES:
                failures.append(
                    (
                        f"UNKNOWN_ASSIGNED_CATEGORY:{category}",
                        f"Assigned category is not a DASP10 category: {category}.",
                    )
                )
                continue
            if packet_primary_attention_categories and category not in packet_primary_attention_categories:
                failures.append(
                    (
                        f"ASSIGNED_CATEGORY_NOT_PRIMARY_ATTENTION:{category}",
                        "Assigned category is not in Step1 primary confirmed-weak or low-support set.",
                    )
                )
            if tool not in selected_tools:
                failures.append(
                    (
                        f"ASSIGNED_TOOL_NOT_SELECTED:{tool}",
                        "Assigned tool is not part of the selected action.",
                    )
                )
            if not _has_direction_evidence(
                certificate,
                matrix,
                category=category,
                tool=tool,
            ):
                failures.append(
                    (
                        f"ASSIGNMENT_MISSING_EVIDENCE:{category}:{tool}",
                        "Assigned category must cite recall-coverage or RAG comparison/recommendation evidence.",
                    )
                )
    return failures


def _check_forbidden_claims(certificate: Step2DecisionCertificate) -> list[Failure]:
    failures: list[Failure] = []
    attestation = certificate.forbidden_claims_attestation
    for field_name in (
        "no_target_vulnerability_claim",
        "no_code_semantic_inference",
        "no_precision_from_detected_total",
        "absence_of_findings_not_treated_as_safe",
        "no_unsourced_numeric_gain",
    ):
        if not getattr(attestation, field_name):
            failures.append(
                (
                    f"ATTESTATION_VIOLATED:{field_name}",
                    f"Forbidden-claims attestation is false for {field_name}.",
                )
            )

    for item in _all_claims(certificate):
        claim = item.claim.lower()
        if "target" in claim and any(
            marker in claim
            for marker in ("vulnerable", "vulnerability", "has risk", "is at risk")
        ):
            failures.append(
                (
                    "FORBIDDEN_TARGET_VULNERABILITY_CLAIM",
                    "Claim asserts a target-contract vulnerability status.",
                )
            )
        if (
            ("no findings" in claim or "no vulnerabilities" in claim)
            and ("safe" in claim or "secure" in claim)
        ):
            failures.append(
                (
                    "FORBIDDEN_ABSENCE_MEANS_SAFE",
                    "Claim treats absence of findings as proof of safety.",
                )
            )
        if (
            ("precision" in claim or "f1" in claim)
            and "detected" in claim
            and "total" in claim
        ):
            failures.append(
                (
                    "FORBIDDEN_PRECISION_FROM_DETECTED_TOTAL",
                    "Claim derives precision or F1 from detected/total evidence.",
                )
            )
    return failures


def _verdict(
    status: str,
    certificate: Step2DecisionCertificate,
    failures: list[Failure],
) -> CheckerVerdict:
    verdict = CheckerVerdict(
        status=status,
        checked_action_id=certificate.selected_action_id,
        rule_failures=[code for code, _reason in failures],
        reasons=[reason for _code, reason in failures],
    )
    if status == "REJECT":
        verdict.hard_failures = list(verdict.rule_failures)
    elif status == "REQUEST_REGENERATION":
        verdict.regeneration_reasons = list(verdict.rule_failures)
    return verdict


def _check_mandatory_coverage(
    certificate: Step2DecisionCertificate,
    packet: Step1EvidencePacket,
    matrix: ActionByEvidenceMatrix,
) -> list[Failure]:
    """Every user-mandated category that is also a primary weakness (origin=both)
    must have an augmenting owner or a recorded gap; silent omission is rejected.

    Unlike the composition-only checks, this applies to every decision type
    (including RUN_PRIMARY and the stop-with-gaps fallback): a decision that runs
    only the weak primary must still record the mandated category as a gap rather
    than drop it silently.
    """
    # STOP = explicit StopWithUncovered: categories are recorded uncovered by design,
    # not silently dropped from a composition plan — coverage check does not apply.
    if certificate.decision_type == "STOP":
        return []
    primary = certificate.primary_tool
    weak = set(packet.primary_attention.confirmed_weak_categories) | set(
        packet.primary_attention.low_support_categories
    )
    mandated_weak = set(packet.primary_attention.user_mandated_categories) & weak
    gap = set(matrix.gap_categories)
    failures: list[Failure] = []
    for category in sorted(mandated_weak):
        has_augmenting_owner = any(
            tool != primary and category in categories
            for tool, categories in certificate.tool_categories.items()
        )
        if has_augmenting_owner or category in gap:
            continue
        failures.append(
            (
                f"MANDATORY_CATEGORY_UNCOVERED:{category}",
                "User-mandated weak category has no augmenting owner and no recorded gap.",
            )
        )
    return failures


def check_decision(
    certificate: Step2DecisionCertificate,
    packet: Step1EvidencePacket,
    matrix: ActionByEvidenceMatrix,
) -> CheckerVerdict:
    """对 CEGO 决策证书做多类合法性审计。"""
    action_failures = _check_action_legality(certificate, packet, matrix)
    evidence_failures = _check_evidence_legality(certificate, matrix)
    completeness_failures = _check_evidence_completeness(certificate, matrix)
    composition_action_failures = _check_composition_action_legality(certificate, packet, matrix)
    assignment_caveat_failures = _check_assignment_caveats(certificate)
    composition_failures = _check_composition_completeness(certificate, packet, matrix)
    forbidden_failures = _check_forbidden_claims(certificate)
    coverage_failures = _check_mandatory_coverage(certificate, packet, matrix)

    all_failures = (
        action_failures
        + composition_action_failures
        + evidence_failures
        + completeness_failures
        + assignment_caveat_failures
        + composition_failures
        + forbidden_failures
        + coverage_failures
    )
    if not all_failures:
        return CheckerVerdict(
            status="ACCEPT",
            checked_action_id=certificate.selected_action_id,
        )
    if (
        action_failures
        or composition_action_failures
        or forbidden_failures
        or coverage_failures
    ):
        verdict = _verdict("REJECT", certificate, all_failures)
    else:
        verdict = _verdict("REQUEST_REGENERATION", certificate, all_failures)
    return verdict
