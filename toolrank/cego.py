"""CEGO: constrained, evidence-grounded complement planning."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from typing import Final, Literal

from pydantic import ValidationError

from toolrank.action_contract import action_id_for
from toolrank.openai_compat import (
    DEFAULT_OPENAI_MODEL,
    OpenAICompatClient,
    OpenAICompatError,
    create_json_chat_completion,
)
from toolrank.plan_runtime import (
    budget_usage,
    estimated_budget,
    planning_runtime_minutes,
    within_budget,
)
from toolrank.schemas_v2 import (
    ActionByEvidenceMatrix,
    ActionEvidenceClaim,
    BudgetProfile,
    CategoryAssignment,
    CheckerVerdict,
    CegoComplementProposal,
    CegoProposalSample,
    ForbiddenClaimsAttestation,
    SelectedToolEntry,
    Stage2EvidenceContext,
    Step2DecisionCertificate,
)


class CegoError(RuntimeError):
    """Raised when CEGO cannot produce a usable decision."""


CEGO_SAMPLE_COUNT: Final = 3
CEGO_TEMPERATURE: Final = 0.0
PRIMARY_ONLY_VOTE: Final = "PRIMARY_ONLY"
_MAJORITY_THRESHOLD: Final = CEGO_SAMPLE_COUNT // 2 + 1


@dataclass(frozen=True)
class _SampleOutcome:
    index: int
    status: Literal["VALID", "REQUEST_FAILED", "MALFORMED"]
    proposal: CegoProposalSample | None = None


_SYSTEM_PROMPT = """You schedule complementary smart-contract analysis tools.
The Stage 1 primary tool is immutable and remains an owner of every required category.
For each category, either keep the primary alone or add at most one eligible complement.
Only SEARCH_REQUIRED categories may receive a complement; PRIMARY_SUFFICIENT is closed.
Only choose tools shown in that category's eligible_candidates list.
Every complement must cite evidence IDs from the matrix. detected/total and R_hat are
recall-side evidence; never interpret them as precision. Respect the global tool-slot,
plan-runtime (maximum per-contract runtime times file count), and alert budgets. Never infer that the
target has or lacks a vulnerability and never treat no findings as proof of safety.
Use the matrix-owned w_D and s_t,D values attached to each evaluation link. Do not
invent or override weights. Unlinked qualitative passages may explain a choice but
cannot independently support a complement. Return JSON only."""


def _response_schema() -> dict:
    return CegoProposalSample.model_json_schema()


def _aggregate_proposals(
    outcomes: list[_SampleOutcome],
    required_categories: list[str],
) -> CegoProposalSample:
    """Reduce exactly three sample outcomes into category-level majority winners."""
    if len(outcomes) != CEGO_SAMPLE_COUNT:
        raise ValueError(f"CEGO voting requires exactly {CEGO_SAMPLE_COUNT} outcomes")
    valid = [
        outcome
        for outcome in outcomes
        if outcome.status == "VALID" and outcome.proposal is not None
    ]
    if not valid:
        raise CegoError("All three CEGO samples were unusable")

    proposals: list[CegoComplementProposal] = []
    for category in dict.fromkeys(required_categories):
        votes: Counter[str] = Counter()
        by_sample: list[CegoComplementProposal | None] = []
        for outcome in valid:
            sample_proposal = next(
                (
                    proposal
                    for proposal in outcome.proposal.complements
                    if proposal.category == category
                ),
                None,
            )
            by_sample.append(sample_proposal)
            votes[
                sample_proposal.tool
                if sample_proposal is not None
                else PRIMARY_ONLY_VOTE
            ] += 1

        if votes[PRIMARY_ONLY_VOTE] >= _MAJORITY_THRESHOLD:
            continue
        winner = next(
            (
                tool
                for tool, count in votes.items()
                if tool != PRIMARY_ONLY_VOTE and count >= _MAJORITY_THRESHOLD
            ),
            None,
        )
        if winner is None:
            continue
        evidence_refs = sorted(
            {
                ref
                for proposal in by_sample
                if proposal is not None and proposal.tool == winner
                for ref in proposal.evidence_refs
            }
        )
        proposals.append(
            CegoComplementProposal(
                category=category,
                tool=winner,
                evidence_refs=evidence_refs,
            )
        )
    return CegoProposalSample(complements=proposals)


def _prompt_payload(
    context: Stage2EvidenceContext,
    matrix: ActionByEvidenceMatrix,
    prev_verdict: CheckerVerdict | None,
    *,
    w_recall: float | None,
    w_precision: float | None,
) -> str:
    primary = context.stage1.primary_selection.primary_tool
    evaluations = {
        row.evaluation_id: row
        for tool in matrix.stage1_evidence.tools.values()
        for row in tool.benchmark_evaluations
    }
    categories: list[dict] = []
    for category in context.required_categories:
        panel = matrix.ownership_panel.get(category)
        candidates: list[dict] = []
        if panel is not None:
            for candidate in panel.eligible_candidates:
                relevant_cards = [
                    card
                    for card in matrix.evidence_cards
                    if card.tool == candidate.tool
                    and card.category in {category, "__GLOBAL__"}
                ]
                candidates.append(
                    {
                        "tool": candidate.tool,
                        "R_hat": candidate.rate,
                        "n_eff": candidate.n_eff,
                        "evidence_refs": candidate.evidence_refs,
                        "evidence": [
                            {
                                "id": card.evidence_id,
                                "evidence_type": card.evidence_type,
                                "source": card.source.model_dump(mode="json"),
                                "role": card.decision_role,
                                "value": card.value.model_dump(mode="json") if card.value else None,
                                "claim": card.scope.get("claim_text"),
                                "applies_to_target": card.scope.get("applies_to_target"),
                                "limitations": card.limitations,
                                "benchmark_relevance_weight": card.benchmark_relevance_weight,
                                "linked_evaluations": [
                                    evaluations[evaluation_id].model_dump(mode="json")
                                    for evaluation_id in card.linked_evaluation_ids
                                ],
                            }
                            for card in relevant_cards
                        ],
                        "caveat_refs": candidate.caveat_refs,
                    }
                )
        categories.append(
            {
                "category": category,
                "primary_decision": (
                    panel.primary_decision.model_dump(mode="json")
                    if panel
                    else None
                ),
                "assignment_status": (
                    panel.assignment_status
                    if panel
                    else "PRIMARY_ONLY_NO_COMPLEMENT"
                ),
                "eligible_candidates": candidates,
            }
        )
    runtime_by_tool = {
        entry.tool: {
            "expected_runtime_minutes": entry.tool_cost.expected_runtime_minutes,
            "historical_completion_runtime_minutes": (
                entry.tool_cost.expected_runtime_minutes
            ),
            "fuzz_campaign_budget": (
                entry.tool_cost.fuzz_campaign_budget.model_dump(mode="json")
                if entry.tool_cost.fuzz_campaign_budget
                else None
            ),
            "planning_runtime_minutes": planning_runtime_minutes(entry),
            "planning_runtime_source": (
                entry.tool_cost.fuzz_campaign_budget.method
                if entry.tool_cost.fuzz_campaign_budget is not None
                else "qualified_historical_completion_estimate"
                if entry.tool_cost.expected_runtime_minutes is not None
                else None
            ),
            "planning_runtime_semantics": (
                entry.tool_cost.fuzz_campaign_budget.runtime_semantics
                if entry.tool_cost.fuzz_campaign_budget is not None
                else "historical_completion_estimate"
                if entry.tool_cost.expected_runtime_minutes is not None
                else "unresolved"
            ),
            "provenance": (
                entry.tool_cost.runtime_provenance.model_dump(mode="json")
                if entry.tool_cost.runtime_provenance
                else None
            ),
            "evidence_quality": (
                entry.tool_cost.runtime_evidence.model_dump(mode="json")
                if entry.tool_cost.runtime_evidence
                else None
            ),
            "limitations": (
                entry.tool_cost.runtime_evidence.limitations
                if entry.tool_cost.runtime_evidence
                else ["NO_RUNTIME_EVIDENCE_ASSESSMENT"]
            ),
        }
        for entry in context.stage1.tool_table
    }
    payload = {
        "schema": "dace_context_v2",
        "primary_tool": primary,
        "stage1_evidence": matrix.stage1_evidence.model_dump(mode="json"),
        "required_categories": categories,
        "budget": matrix.budget_profile.model_dump(mode="json"),
        "tool_runtime_evidence": runtime_by_tool,
        "preference_weights": {"recall": w_recall, "precision": w_precision},
        "previous_checker_failures": prev_verdict.rule_failures if prev_verdict else [],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _requested_complements(raw: dict) -> dict[str, tuple[str, list[str]]]:
    requested: dict[str, tuple[str, list[str]]] = {}
    items = raw.get("complements")
    if not isinstance(items, list):
        return requested
    for item in items:
        if not isinstance(item, dict):
            continue
        category = item.get("category")
        tool = item.get("tool")
        refs = item.get("evidence_refs", [])
        if not isinstance(category, str) or not isinstance(tool, str) or category in requested:
            continue
        clean_refs = [ref for ref in refs if isinstance(ref, str)] if isinstance(refs, list) else []
        requested[category] = (tool, list(dict.fromkeys(clean_refs)))
    return requested


def _selected_plan(primary: str, complements: list[str]) -> list[SelectedToolEntry]:
    return [
        SelectedToolEntry(
            tool=primary,
            role="STARTER",
            execution_order=1,
            reason_codes=["STAGE1_PRIMARY"],
        ),
        *[
            SelectedToolEntry(
                tool=tool,
                role="COMPLEMENT",
                execution_order=1,
                reason_codes=["CATEGORY_COMPLEMENT"],
            )
            for tool in complements
        ],
    ]


def assemble_decision(
    raw: dict,
    context: Stage2EvidenceContext,
    matrix: ActionByEvidenceMatrix,
    budget: BudgetProfile,
) -> Step2DecisionCertificate:
    """Constrain an LLM proposal into the additive ownership contract.

    Invalid candidates are ignored and their categories deterministically retain
    the primary.  Evidence references are preserved verbatim for the independent
    checker; assembly never invents grounding for the model.
    """
    primary = context.stage1.primary_selection.primary_tool
    if not primary:
        raise CegoError("Stage 2 decision requires a Stage 1 primary tool")
    requested = _requested_complements(raw)
    selected_tools = [primary]
    assignments: list[CategoryAssignment] = []

    for category in dict.fromkeys(context.required_categories):
        panel = matrix.ownership_panel.get(category)
        allowed = {
            candidate.tool: candidate
            for candidate in (panel.eligible_candidates if panel else [])
        }
        request = requested.get(category)
        complement: str | None = None
        refs: list[str] = []
        if request is not None and request[0] in allowed:
            proposed_tools = list(dict.fromkeys([*selected_tools, request[0]]))
            estimate = estimated_budget(
                proposed_tools,
                context.stage1.tool_table,
                budget.execution_schedule,
            )
            if estimate is not None and within_budget(estimate, budget):
                complement, refs = request
                selected_tools = proposed_tools

        if complement is None:
            assignments.append(CategoryAssignment(category=category, owner_tools=[primary]))
            continue
        candidate = allowed[complement]
        assignments.append(
            CategoryAssignment(
                category=category,
                owner_tools=[primary, complement],
                complement_tool=complement,
                status="COMPLEMENT_ADDED",
                for_claims=[
                    ActionEvidenceClaim(
                        claim=f"Add {complement} as a complement for {category}",
                        evidence_refs=refs,
                    )
                ],
                caveat_refs=candidate.caveat_refs,
            )
        )

    complements = selected_tools[1:]
    usage = budget_usage(selected_tools, context.stage1.tool_table, budget)
    if usage is None:
        raise CegoError("Selected plan runtime cannot be verified")
    decision_type = "PLAN_COMPOSITION" if complements else "RUN_PRIMARY"
    if complements:
        summary = f"Keep {primary} for all categories and add: {', '.join(complements)}."
    else:
        summary = f"Keep {primary} as the sole owner for all required categories."
    return Step2DecisionCertificate(
        decision_type=decision_type,
        selected_action_id=action_id_for(decision_type),
        selected_plan=_selected_plan(primary, complements),
        primary_tool=primary,
        category_assignments=assignments,
        budget=usage,
        forbidden_claims_attestation=ForbiddenClaimsAttestation(),
        short_summary=summary,
    )


def build_primary_only_certificate(
    context: Stage2EvidenceContext,
    matrix: ActionByEvidenceMatrix,
    budget: BudgetProfile,
) -> Step2DecisionCertificate:
    """Return the paper-defined fallback: primary retains every category."""
    return assemble_decision({"complements": []}, context, matrix, budget)


def run_cego(
    client: OpenAICompatClient,
    model: str,
    context: Stage2EvidenceContext,
    matrix: ActionByEvidenceMatrix,
    prev_verdict: CheckerVerdict | None = None,
    *,
    w_recall: float | None = None,
    w_precision: float | None = None,
) -> Step2DecisionCertificate:
    """Collect three raw proposals, vote per category, and assemble one plan."""
    user_prompt = _prompt_payload(
        context,
        matrix,
        prev_verdict,
        w_recall=w_recall,
        w_precision=w_precision,
    )
    response_schema = _response_schema()
    outcomes: list[_SampleOutcome] = []
    for index in range(CEGO_SAMPLE_COUNT):
        try:
            raw = create_json_chat_completion(
                client=client,
                model=model or DEFAULT_OPENAI_MODEL,
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                schema=response_schema,
                temperature=CEGO_TEMPERATURE,
                raise_on_error=True,
            )
        except OpenAICompatError:
            outcomes.append(
                _SampleOutcome(index=index, status="REQUEST_FAILED")
            )
            continue
        try:
            proposal = CegoProposalSample.model_validate(raw)
        except ValidationError:
            outcomes.append(_SampleOutcome(index=index, status="MALFORMED"))
            continue
        outcomes.append(
            _SampleOutcome(index=index, status="VALID", proposal=proposal)
        )

    aggregate = _aggregate_proposals(outcomes, context.required_categories)
    return assemble_decision(
        aggregate.model_dump(mode="json"),
        context,
        matrix,
        matrix.budget_profile,
    )
