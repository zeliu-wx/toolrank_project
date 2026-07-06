"""CEGO: Constrained Evidence-Grounded Orchestration LLM decision protocol."""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from pydantic import ValidationError

from toolrank.assignment_evidence import (
    count_text,
    is_assignment_eligible,
    is_close_local_margin,
    rate_text,
)
from toolrank.openai_compat import (
    DEFAULT_OPENAI_MODEL,
    OpenAICompatClient,
    OpenAICompatError,
    create_json_chat_completion,
)
from toolrank.precision_gate import candidate_passes_precision_gate
from toolrank.ownership_evidence import (
    attention_categories,
    card_scene_priority,
    card_scene_tier,
    card_scene_weight,
    card_scope_text,
    category_capability_pro_refs,
    category_group,
    rcov_evidence_id,
    scheduling_evidence_priority,
)
from toolrank.schemas_v2 import (
    ActionByEvidenceMatrix,
    ActionEvidenceClaim,
    BudgetProfile,
    BudgetUsage,
    CandidateAction,
    CategoryAssignment,
    CheckerVerdict,
    EvidenceCard,
    ForbiddenClaimsAttestation,
    SelectedToolEntry,
    Step1EvidencePacket,
    Step2DecisionCertificate,
    ToolRunSummary,
)


class CegoError(RuntimeError):
    """Raised when CEGO cannot produce a valid decision certificate."""


def _build_system_prompt() -> str:
    return """You are a smart-contract security tool scheduler.
Your job: for each target vulnerability category, decide whether to replace the default primary tool with a complement tool, and if so which one. The primary tool is fixed and covers every category by default; you only decide complements.

How to read the evidence (## Per-Category Evidence Matrix): one block per target category. The primary tool's recall is in the block header. Each candidate tool is a row with four slots:
- FOR: recall support for selecting it;
- AGAINST: category-specific false-positive risk or opposition;
- COMPARE: its strength versus the primary tool;
- GAP: no evidence.
Evidence rows carry `scene_w=` (Gower-KDE scene relevance to the target, 0-1; `local` = cross-benchmark aggregate). Weight evidence by `scene_w`: near-scene evidence outweighs distant evidence.

For each target category choose one of two options:
- KEEP the primary (default): do not list the category.
- REPLACE with a candidate: add {"category": <id>, "tool": <tool>} to `replacements`, where <tool> is one of the candidate rows shown in that category's block.

Decision rules:
1. The primary tool is the Step1 anchor and is retained by default; never replace a category unless a candidate is credibly stronger than the primary on it (see its COMPARE slot) and worth a tool slot.
2. Do not select by highest recall alone: if a candidate's recall is strong but its AGAINST slot flags a category-specific false-positive burden, judge whether that burden applies to THIS target contract; if it does, prefer a candidate without it or keep the primary. A candidate's `PRECISION: overall-precision percentile=X` line gives X in [0,1] = the tool's per-dataset rank-normalized, scene-weighted precision standing among peers (0 = least precise, 1 = most). Read it strictly ONE-WAY and use judgment, not a fixed cutoff: a LOW percentile is negative evidence of broad over-reporting / high-FP risk, to be weighed against the candidate's recall and the category's coverage need; a HIGH percentile is NOT positive evidence that the tool is precise on THIS category (overall precision does not transfer per-category). When the user prefers precision, treat a low percentile more harshly; when the user prefers recall, tolerate it more.
3. RAG passages with source_reliability=manual_curated are human-authored scheduling rules - authoritative regardless of scene_w. Passages span trust tiers (see rule 3a); lower tiers are shown but should be weighted down.
3a. Each RAG passage carries trust_tier: tier1 (manual_curated or scene-linked) is authoritative and may overturn a recall-based pick; tier2 (premise-gated by solc:/scale: and the premise holds for THIS contract) is full evidence to weigh; tier3 (retrieval-relevant only, no scene link or verified premise) is a weak secondary hint - use it to corroborate, not to drive a replacement alone. A false-positive (FP) passage is a WARNING, not a veto: weigh it against recall and coverage; an explicit coverage requirement for the category can outweigh an FP warning.
4. You may replace ONLY categories listed under step1.primary_attention.confirmed_weak_categories or step1.primary_attention.low_support_categories, using the exact lower-case category ids; <tool> MUST be a candidate shown in that category's matrix block.
5. budget.tool_slots is a hard upper bound on the TOTAL number of tools (primary + distinct complements). Prefer a single tool that owns several target categories over many single-category tools, to stay within budget.
6. You MUST NOT claim the target contract has or lacks any vulnerability, infer vulnerability types from code or function names, interpret detected/total as precision or F1, or treat absence of findings as proof of safety.

Output a JSON object with exactly one field:
- replacements: array of {"category": string, "tool": string}. List ONLY the categories you replace; every category you omit keeps the primary tool."""


def _build_percategory_system_prompt() -> str:
    return """You are a smart-contract security tool scheduler deciding ONE vulnerability category.
For the single target category shown, decide whether to KEEP the default primary tool or REPLACE it with one candidate tool from that category's matrix block.

Reason step by step and FILL EVERY FIELD in this exact order — do not skip to the decision:
- q1_best_recall: name the candidate with the best recall (R_hat) and state it.
- q2_fp_warnings: list every false-positive / precision warning you see (cite the [evidence_id]); say "none" if there are none.
- q3_fp_applicability: for EACH warning in q2, judge its trust_tier. tier1 (manual_curated or scene-linked) is authoritative and may overturn a recall-based pick; tier2 (solc:/scale: premise that holds for THIS contract) is full evidence; tier3 (retrieval-relevant only, no scene link or verified premise) is a WEAK secondary hint that must NOT alone sink a high-recall candidate — use it only to corroborate.
- q4_primary_compare: compare the best candidate to the PRIMARY tool (shown in the block header as `primary=<tool>(R_hat=.. <support>  precision_pctl=..)`). State three things: (a) CAPABILITY — does the primary itself detect this category? Header support 'strong'/'weak' = capable (it has eligible recall here); 'unsupported' (or no usable R_hat) = NOT capable. (b) RECALL GAP — how much higher is the candidate's recall than the primary's (see the candidate's COMPARE slot). (c) PRECISION — compare the candidate's `PRECISION: ... percentile=X` to the primary's `precision_pctl` in the header: is the candidate MORE or LESS precise than the primary?
- q5_tradeoff: weigh recall against the APPLICABLE (tier1/tier2) FP warnings using the user preference weights w_recall/w_precision given in the prompt. Read the `PRECISION: overall-precision percentile=X` line (X in [0,1]) strictly ONE-WAY: when w_precision is high, treat a LOW X more harshly (low X = broad over-reporting / high-FP risk); when w_recall is high, tolerate it more. A HIGH percentile is NOT positive evidence that the tool is precise on THIS category. An explicit coverage need can outweigh an FP warning (a false-positive passage is a WARNING, not a veto).
- decision: {"action": "keep_primary"} to keep, or {"action": "replace", "tool": <candidate>} where <candidate> MUST be one of the candidate rows shown in this category's block.

Hard prohibitions: you MUST NOT claim the target contract has or lacks any vulnerability, infer vulnerability types from code or function names, interpret detected/total as precision or F1, or treat absence of findings as proof of safety.
Output JSON only, matching the given schema exactly."""


def _percategory_response_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "q1_best_recall",
            "q2_fp_warnings",
            "q3_fp_applicability",
            "q4_primary_compare",
            "q5_tradeoff",
            "decision",
        ],
        "properties": {
            "q1_best_recall": {"type": "string"},
            "q2_fp_warnings": {"type": "string"},
            "q3_fp_applicability": {"type": "string"},
            "q4_primary_compare": {"type": "string"},
            "q5_tradeoff": {"type": "string"},
            "decision": {
                "type": "object",
                "additionalProperties": False,
                "required": ["action"],
                "properties": {
                    "action": {"type": "string", "enum": ["keep_primary", "replace"]},
                    "tool": {"type": ["string", "null"]},
                },
            },
        },
    }


def _card_assignment_eligible(card: EvidenceCard, packet: Step1EvidencePacket | None = None) -> bool:
    if card.value is None:
        return False
    # Experiment toggle: drop the Wilson-CI "strong" recall gate (which excludes mid-recall tools
    # whose estimate is imprecise at small scene samples). When on, any positive recall qualifies.
    if os.getenv("TOOLRANK_CEGO_NO_CI_GATE", "").strip().lower() in {"1", "true", "yes", "on"}:
        if card.value.rate is None or card.value.rate <= 0:
            return False
    elif not is_assignment_eligible(card.value.detected, card.value.effective_total, card.value.rate):
        return False
    if packet is not None and card.tool is not None:
        return candidate_passes_precision_gate(packet, card.tool)
    return True


def _top_cards_by_tool(cards: list[EvidenceCard], limit: int = 5) -> list[EvidenceCard]:
    selected: list[EvidenceCard] = []
    seen_tools: set[str] = set()
    for card in cards:
        if card.tool is None or card.tool in seen_tools:
            continue
        selected.append(card)
        seen_tools.add(card.tool)
        if len(selected) >= limit:
            break
    return selected


def _matched_dataset_lines(packet: Step1EvidencePacket) -> list[str]:
    lines = ["## Matched Dataset Knowledge", "Scene neighbors:"]
    if packet.scene_pool.neighbors:
        for neighbor in packet.scene_pool.neighbors:
            lines.append(
                (
                    f"- slice={neighbor.slice_id} source={neighbor.paper_id} "
                    f"weight={neighbor.weight:.4f} distance={neighbor.distance:.4f}"
                )
            )
    else:
        lines.append("- none")

    lines.extend(["", "Primary scene tool scores:"])
    if packet.score_panel.nominal_scores:
        for score in sorted(packet.score_panel.nominal_scores, key=lambda item: item.rank):
            f1 = f"{score.F1_scene:.4f}" if score.F1_scene is not None else "None"
            lines.append(
                (
                    f"- {score.tool}: S_scene={score.S_scene:.4f} "
                    f"F1={f1} evidence_level={score.evidence_level}"
                )
            )
    else:
        lines.append("- none")

    lines.extend(["", "Per-category recall-side hints:"])
    by_category: dict[str, list] = {}
    for row in packet.recall_coverage.matrix:
        if row.R_hat is None:
            continue
        by_category.setdefault(row.category, []).append(row)
    if by_category:
        for category in sorted(by_category):
            values = [
                f"{row.tool}={row.R_hat:.4f}({row.support_level})"
                for row in sorted(by_category[category], key=lambda item: item.tool)
            ]
            lines.append(f"- {category}: {'; '.join(values)}")
    else:
        lines.append("- none")
    return lines


def _scene_weighted_precision_percentile(packet: Step1EvidencePacket) -> dict[str, float]:
    """Per-tool scene-weighted mean of WITHIN-DATASET overall-precision percentiles.

    For each in-scene dataset (scene neighbour weight w_s > 0) with >=2 tools reporting
    overall precision, every tool is rank-normalised inside that dataset to a percentile in
    [0,1] (0 = worst precision on that dataset, 1 = best; ties share the average position).
    A tool's score is the w_s-weighted mean of its per-dataset percentiles. Per-dataset
    normalisation removes "this dataset is hard/easy for everyone", so the score reflects a
    tool's relative standing among peers on scene-relevant data, not absolute precision.
    Tools with no qualifying in-scene dataset are absent (not judged), to avoid mistaking
    missing data for a low rank.
    """
    src_w: dict[str, float] = {}
    for n in packet.scene_pool.neighbors:
        if n.weight <= 0:
            continue
        for sid in [n.paper_id, *(n.provenance_refs or [])]:
            if sid:
                src_w[sid] = max(src_w.get(sid, 0.0), n.weight)
    by_dataset: dict[str, list[tuple[str, float]]] = {}
    for row in packet.tool_overall_metrics:
        if row.precision is None or row.source_id not in src_w:
            continue
        by_dataset.setdefault(row.source_id, []).append((row.tool, row.precision))
    num: dict[str, float] = {}
    den: dict[str, float] = {}
    for source_id, rows in by_dataset.items():
        if len(rows) < 2:
            continue
        w = src_w[source_id]
        precisions = [p for _, p in rows]
        denom = len(precisions) - 1
        for tool, precision in rows:
            lower = sum(1 for q in precisions if q < precision)
            equal = sum(1 for q in precisions if q == precision) - 1  # exclude self; ties -> avg
            percentile = (lower + 0.5 * equal) / denom
            num[tool] = num.get(tool, 0.0) + w * percentile
            den[tool] = den.get(tool, 0.0) + w
    return {t: num[t] / den[t] for t in num if den[t] > 0}


def _overall_precision_percentile_text(
    packet: Step1EvidencePacket, tool: str, pct_by_tool: dict[str, float] | None = None
) -> str | None:
    """One-sided overall-precision percentile token for a candidate (None if not judged).

    Surfaces the tool's per-dataset rank-normalised, scene-weighted precision percentile in
    [0,1] for the LLM to weigh ONE-WAY (no hard cutoff): a low value is negative evidence of
    broad over-reporting / high-FP risk; a high value is NOT positive evidence that the tool
    is precise on THIS category. Returns None when the tool has no in-scene precision data.
    """
    if pct_by_tool is None:
        pct_by_tool = _scene_weighted_precision_percentile(packet)
    score = pct_by_tool.get(tool)
    if score is None or len(pct_by_tool) < 2:
        return None
    n = len(pct_by_tool)
    rank = sum(1 for v in pct_by_tool.values() if v < score) + 1  # 1 = worst
    return (
        f"overall-precision percentile={score:.2f} "
        f"(rank {rank}/{n} among judged tools, per-dataset rank-normalized, scene-weighted)"
    )


def _rcov_by_tool_category(matrix) -> dict[tuple[str, str], object]:
    return {(row.tool, row.category): row for row in matrix.matrix}


def _primary_local_support(
    primary_tool: str,
    category: str,
    local_by_key: dict[tuple[str, str], object],
) -> str:
    entry = local_by_key.get((primary_tool, category))
    support_level = str(getattr(entry, "support_level", "") or "")
    if support_level in {"strong", "medium", "weak"}:
        return support_level
    return "none"


def _candidate_prompt_scope(packet: Step1EvidencePacket, card: EvidenceCard) -> str:
    if card_scope_text(card) == "local":
        return "local"
    scene_tier = card_scene_tier(packet, card)
    if scene_tier in {"primary", "near_scene"}:
        return "near_scene"
    return "unrelated"


def _scene_w_text(packet: Step1EvidencePacket, card: EvidenceCard) -> str:
    """Render the scene_w= token for a card."""
    if card_scope_text(card) == "local":
        return "scene_w=local"
    w = card_scene_weight(packet, card)
    if w is not None:
        return f"scene_w={w:.4f}"
    return "scene_w=unlinked"


def _rag_refs_by_slot(
    matrix: ActionByEvidenceMatrix,
    *,
    category: str,
    tool: str,
) -> dict[str, list[str]]:
    """Bucket RAG passage refs for (tool, category) into paper §III slots by relation_to_owner."""
    slots: dict[str, list[str]] = {"FOR": [], "AGAINST": [], "COMPARE": [], "GAP": []}
    for card in matrix.evidence_cards:
        if card.evidence_type != "rag_passage" or card.tool != tool:
            continue
        if category not in _scope_list(card.scope, "categories") and card.category != category:
            continue
        relation = str(card.scope.get("relation_to_owner") or "")
        if relation in {"supports_owner", "owner_complements"}:
            slots["FOR"].append(card.evidence_id)
        elif relation in {"opposes_owner", "owner_ineligible"}:
            slots["AGAINST"].append(card.evidence_id)
        elif relation in {"owner_stronger", "owner_weaker"}:
            slots["COMPARE"].append(card.evidence_id)
        elif relation == "evidence_gap":
            slots["GAP"].append(card.evidence_id)
    return slots


def _rag_ref_inline_tag(
    matrix: ActionByEvidenceMatrix, evidence_id: str, *, full: bool = True
) -> str:
    """Decision-adjacent annotation for a RAG ref id; '' if id is not a rag card.

    `full=True` -> ' tierN "<complete claim text>" (limitations: ...)' so the slot carries the
    passage's tier AND its whole text + limitations right next to the ref (no need to jump to a
    separate section, and nothing is truncated). `full=False` -> ' tierN' only, used when the
    same passage already appeared earlier in the SAME candidate row (avoids repeating the text).
    """
    for card in matrix.evidence_cards:
        if card.evidence_type == "rag_passage" and card.evidence_id == evidence_id:
            tier = str(card.scope.get("trust_tier") or "tier3")
            if not full:
                return f" {tier}"
            claim = str(card.scope.get("text") or card.scope.get("claim_text") or "").strip()
            # The fuller curator rationale often lives in source_excerpt (e.g. "VulHunter ...
            # false-positive burden is high") while claim_text is a sanitized one-liner; surface
            # it so the model sees the real reason, not just the headline.
            excerpt = str(card.scope.get("source_excerpt") or "").strip()
            text_part = f' "{claim}"' if claim else ""
            if excerpt and excerpt != claim:
                text_part += f' note: "{excerpt}"'
            lims = card.scope.get("limitations") or list(card.limitations)
            if isinstance(lims, str):
                lims = [lims]
            lim_text = ""
            if lims:
                lim_text = " (limitations: " + "; ".join(str(x) for x in lims) + ")"
            return f" {tier}" + text_part + lim_text
    return ""


def _evidence_matrix_block(
    packet: Step1EvidencePacket,
    matrix: ActionByEvidenceMatrix,
    category: str,
    pct_by_tool: dict[str, float] | None = None,
    inline_rag: bool = False,
) -> list[str]:
    """One category's block: '### {category} ...' header + per-candidate FOR/AGAINST/COMPARE/GAP/PRECISION.

    Caller prepends the '## Per-Category Evidence Matrix' section header. `pct_by_tool`
    is the precomputed scene-weighted precision percentile map (None -> computed per call,
    preserving single-path byte-identical output). When `inline_rag` is True (per-category
    path only), each RAG ref is annotated inline with its trust_tier + a short claim; when
    False (single path) the output is byte-identical to before.
    """
    local_by_key = _rcov_by_tool_category(packet.recall_coverage)
    primary_tool = packet.primary_attention.primary_tool
    group = category_group(packet, category)
    sorted_cards = _sorted_candidate_cards(packet, matrix, category)
    cards = _top_cards_by_tool(sorted_cards)
    primary_entry = local_by_key.get((primary_tool, category))
    primary_rate = getattr(primary_entry, "R_hat", None)
    primary_support = _primary_local_support(primary_tool, category, local_by_key)
    header = (
        f"### {category}  group={group}  "
        f"primary={primary_tool}(R_hat={rate_text(primary_rate)} {primary_support})"
    )
    # Per-category path only: surface the primary's own precision percentile in the header so the
    # model can compare it against each candidate's PRECISION line (the primary has no candidate
    # row). Guarded by inline_rag to keep the single path's output byte-identical.
    if inline_rag and pct_by_tool is not None:
        _pp = pct_by_tool.get(primary_tool)
        if _pp is not None:
            header = header[:-1] + f"  precision_pctl={_pp:.2f})"
    local_cards = [c for c in sorted_cards if card_scope_text(c) == "local"]
    if cards and group == "confirmed_weak" and len(local_cards) >= 2:
        top_value = local_cards[0].value
        next_value = local_cards[1].value
        if (
            top_value is not None
            and next_value is not None
            and top_value.rate is not None
            and next_value.rate is not None
            and is_close_local_margin(
                top_value.rate,
                top_value.effective_total,
                next_value.rate,
                next_value.effective_total,
            )
        ):
            header += f"  margin=close({(top_value.rate - next_value.rate):.4f})"
    lines = [header]
    if not cards:
        lines.append("- (no feasible non-primary candidate with eligible evidence)")
        return lines

    for card in cards:
        tool = card.tool or ""
        value = card.value
        rag = _rag_refs_by_slot(matrix, category=category, tool=tool)
        _seen_refs: set[str] = set()

        def _tag(ref: str) -> str:
            if not inline_rag:
                return ""
            tag = _rag_ref_inline_tag(matrix, ref, full=ref not in _seen_refs)
            _seen_refs.add(ref)
            return tag

        for_parts = [
            f"{_candidate_prompt_scope(packet, card)} R_hat={rate_text(value.rate)} "
            f"tp/GT={count_text(value.detected, value.total)} "
            f"[{card.evidence_id} {_scene_w_text(packet, card)}]"
        ]
        for ref in category_capability_pro_refs(matrix, category=category, tool=tool):
            for_parts.append(f"RAG-pro [{ref}]{_tag(ref)}")
        # Inline full-text priority FOR -> AGAINST -> COMPARE -> GAP: when a passage is shared
        # across slots (e.g. an fp_precision_risk that is also a comparison), the full text is
        # emitted in the higher-priority slot and later slots show tier only. AGAINST is built
        # before COMPARE so FP evidence (what q2/q3 reads) keeps the full text.
        against_parts = [
            f"FP-risk [{ref}]{_tag(ref)}"
            for ref in _fp_precision_risk_refs(matrix, category=category, tool=tool)
        ]
        against_parts += [f"RAG-against [{ref}]{_tag(ref)}" for ref in rag["AGAINST"]]
        compare_parts: list[str] = []
        cand_rate = value.rate if value is not None else None
        if cand_rate is not None:
            if primary_rate is None:
                rel, prim_text = "stronger than", "unsupported"
            elif cand_rate > primary_rate:
                rel, prim_text = "stronger than", rate_text(primary_rate)
            elif cand_rate < primary_rate:
                rel, prim_text = "weaker than", rate_text(primary_rate)
            else:
                rel, prim_text = "comparable to", rate_text(primary_rate)
            compare_parts.append(
                f"{rel} {primary_tool} ({rate_text(cand_rate)} vs {prim_text}) [{card.evidence_id}]"
            )
        for ref in rag["COMPARE"]:
            compare_parts.append(f"RAG-compare [{ref}]{_tag(ref)}")
        gap_parts = [f"RAG-gap [{ref}]{_tag(ref)}" for ref in rag["GAP"]]
        lines.append(f"- {tool}:")
        lines.append(f"    FOR: {'; '.join(for_parts) if for_parts else 'none'}")
        lines.append(f"    AGAINST: {'; '.join(against_parts) if against_parts else 'none'}")
        lines.append(f"    COMPARE: {'; '.join(compare_parts) if compare_parts else 'none'}")
        lines.append(f"    GAP: {'; '.join(gap_parts) if gap_parts else 'none'}")
        precision_line = _overall_precision_percentile_text(packet, tool, pct_by_tool)
        if precision_line:
            lines.append(f"    PRECISION: {precision_line}")
    return lines


def _evidence_matrix_lines(
    packet: Step1EvidencePacket,
    matrix: ActionByEvidenceMatrix,
) -> list[str]:
    """Paper §III-B1 per-category x per-candidate-tool four-slot matrix (one block per category)."""
    lines = ["## Per-Category Evidence Matrix"]
    if not packet.primary_attention.primary_tool:
        return lines + ["- none"]
    categories = attention_categories(packet)
    if not categories:
        return lines + ["- none"]
    for category in categories:
        lines.extend(_evidence_matrix_block(packet, matrix, category))
    return lines


def _gap_category_lines(matrix: ActionByEvidenceMatrix) -> list[str]:
    lines = ["## Gap Categories"]
    if not matrix.gap_categories:
        return lines + ["- none"]
    for category in matrix.gap_categories:
        panel = matrix.ownership_panel.get(category)
        reason = panel.gap_reason if panel else "gap"
        lines.append(f"- {category}: {reason}")
    return lines


def _feasible_tool_space_lines(packet: Step1EvidencePacket) -> list[str]:
    lines = ["## Feasible Tool Space"]
    ranks = {score.tool: score.rank for score in packet.score_panel.nominal_scores}
    feasible_entries = [entry for entry in packet.tool_table if entry.feasible]
    if not feasible_entries:
        lines.append("- none")
        return lines
    for entry in sorted(feasible_entries, key=lambda item: (ranks.get(item.tool, 9999), item.tool)):
        cost = entry.tool_cost
        runtime = cost.expected_runtime_minutes
        runtime_text = "unknown" if runtime is None else f"{runtime:.1f}"
        rank_text = ranks.get(entry.tool, "unranked")
        lines.append(
            (
                f"- {entry.tool}: rank={rank_text} family={entry.family} "
                f"runtime_min={runtime_text} alert={cost.alert_risk}"
            )
        )
    return lines


def _scope_list(scope: dict, key: str) -> list[str]:
    value = scope.get(key)
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _rag_scope_polarity(scope: dict) -> str:
    relation_to_owner = str(scope.get("relation_to_owner") or "")
    if relation_to_owner in {"opposes_owner", "owner_ineligible", "owner_weaker"}:
        return "con"
    if relation_to_owner == "evidence_gap":
        return "gap"
    if relation_to_owner == "owner_stronger":
        return "comparative"
    if relation_to_owner in {"supports_owner", "owner_complements"}:
        return "pro"
    return ""


_FP_AGAINST_KINDS = {"fp_precision_risk", "failure_mode"}


def _fp_precision_risk_refs(
    matrix: ActionByEvidenceMatrix,
    *,
    category: str,
    tool: str | None,
) -> list[str]:
    if not tool:
        return []
    refs: list[str] = []
    for card in matrix.evidence_cards:
        if card.evidence_type != "rag_passage":
            continue
        if card.tool != tool:
            continue
        if (
            card.category != "__GLOBAL__"
            and category not in _scope_list(card.scope, "categories")
            and card.category != category
        ):
            continue
        if str(card.scope.get("knowledge_kind") or "") not in _FP_AGAINST_KINDS:
            continue
        if _rag_scope_polarity(card.scope) != "con":
            continue
        refs.append(card.evidence_id)
    return refs


def _rag_scope_passage_type(scope: dict) -> str:
    passage_type = str(scope.get("passage_type") or "")
    if passage_type:
        return passage_type
    relation_to_owner = str(scope.get("relation_to_owner") or "")
    if relation_to_owner == "owner_ineligible":
        return "limitation"
    if relation_to_owner in {"owner_stronger", "owner_weaker"}:
        return "comparison"
    if relation_to_owner == "owner_complements":
        return "recommendation"
    if relation_to_owner == "evidence_gap":
        return "gap"
    if relation_to_owner:
        return "performance"
    return ""


def _rag_scope_scene_constraints(scope: dict) -> list[str]:
    scene_constraints = _scope_list(scope, "scene_constraints")
    if scene_constraints:
        return scene_constraints
    return [
        tag.removeprefix("scene:")
        for tag in _scope_list(scope, "applicability_tags")
        if tag.startswith("scene:")
    ]


def _rag_tool_knowledge_lines(
    matrix: ActionByEvidenceMatrix,
    packet: Step1EvidencePacket | None = None,
    category: str | None = None,
) -> list[str]:
    rag_cards = [card for card in matrix.evidence_cards if card.evidence_type == "rag_passage"]
    if category is not None:
        rag_cards = [
            card
            for card in rag_cards
            if card.category == category
            or category in _scope_list(card.scope, "categories")
        ]

    lines = [
        "## RAG Tool Knowledge",
        "RAG passages are decision evidence; applicable hard passages may justify LLM-declared overrides but are not pre-applied owners.",
    ]
    if not rag_cards:
        lines.append("- none")
        return lines
    for card in rag_cards:
        passage_type = _rag_scope_passage_type(card.scope)
        knowledge_kind = card.scope.get("knowledge_kind") or ""
        polarity = _rag_scope_polarity(card.scope)
        counterpart_tool_ids = _scope_list(card.scope, "counterpart_tool_ids")
        primary_tool = card.scope.get("primary_tool") or (
            counterpart_tool_ids[0]
            if card.scope.get("relation_to_owner") == "owner_complements" and counterpart_tool_ids
            else ""
        )
        complement_tool = card.scope.get("complement_tool") or (
            card.tool if card.scope.get("relation_to_owner") == "owner_complements" else ""
        )
        scene_constraints = _rag_scope_scene_constraints(card.scope)
        evidence_basis = card.scope.get("evidence_basis") or ""
        priority = scheduling_evidence_priority(card, category=card.category or "")
        limitations = _scope_list(card.scope, "limitations") or list(card.limitations)
        text = str(card.scope.get("text") or card.scope.get("claim_text") or "")
        scene_text = ", ".join(scene_constraints)
        limitations_text = ", ".join(str(item) for item in limitations)
        scene_w_token = _scene_w_text(packet, card) if packet is not None else "scene_w=unlinked"
        trust_tier = card.scope.get("trust_tier", "tier3")
        lines.append(
            (
                f"- {card.evidence_id}: [POLARITY={polarity}] kind={knowledge_kind} polarity={polarity} paper={card.source.paper_id} "
                f"primary={primary_tool} complement={complement_tool} tool={card.tool} category={card.category} "
                f"scene={scene_text} limitations={limitations_text} basis={evidence_basis} type={passage_type} "
                f"priority={priority} source_reliability={card.source_reliability} {scene_w_token} trust_tier={trust_tier}"
            )
        )
        if text:
            lines.append(f"  text={text}")
    return lines


def _build_user_prompt(
    packet: Step1EvidencePacket,
    matrix: ActionByEvidenceMatrix,
    run_history: list[ToolRunSummary] | None,
    prev_verdict: CheckerVerdict | None = None,
) -> str:
    budget = matrix.budget_profile
    primary_tool = _step1_anchor_tool(packet)
    lines = [
        f"## Budget: tool_slots={budget.tool_slots}, runtime_cap_minutes={budget.runtime_cap_minutes}, alert_cap={budget.alert_cap}",
        "",
        "## Category Ownership",
        f"Step1 anchor primary_tool={primary_tool}",
        f"step1.primary_attention.confirmed_weak_categories={packet.primary_attention.confirmed_weak_categories}",
        f"step1.primary_attention.low_support_categories={packet.primary_attention.low_support_categories}",
        "Confirmed-weak categories are where a peer tool's recall is credibly higher than the primary's on the matched scene (Newcombe 95% CI lower bound of the gap > 0). Low-support categories are where the primary's own recall estimate is too imprecise to judge (Wilson CI half-width > 0.15). Complement tools may own categories from either group, decided by cross-dataset performance refs and RAG Tool Knowledge.",
        "",
        "## Step1 Field Refs",
        "Use the exact ref before '=' when citing these fields.",
        f"step1.certification.status={packet.certification.status}",
        f"step1.certification.certified_primary={packet.certification.certified_primary}",
        f"step1.certification.candidate_set={packet.certification.candidate_set}",
        f"step1.certification.reason_codes={packet.certification.reason_codes}",
        "",
    ]
    lines.extend(_matched_dataset_lines(packet))
    lines.extend([""])
    lines.extend(_evidence_matrix_lines(packet, matrix))
    lines.extend([""])
    lines.extend(_gap_category_lines(matrix))
    lines.extend([""])
    lines.extend(_feasible_tool_space_lines(packet))
    lines.extend([""])
    lines.extend(_rag_tool_knowledge_lines(matrix, packet))
    lines.extend(["", "## Legal Action Envelopes"])

    for action in matrix.actions:
        if not action.legal:
            continue
        lines.extend(
            [
                f"### {action.action_id} ({action.action_type})",
                f"Tools: {action.tools}",
                (
                    f"Estimated: slots={action.estimated_budget.tool_slots}, "
                    f"runtime={action.estimated_budget.runtime_cap_minutes} min, "
                    f"alert={action.estimated_budget.alert_cap}"
                ),
            ]
        )
        lines.append("")

    if run_history:
        lines.extend(["", "## Run History"])
        for item in run_history:
            lines.append(
                (
                    f"- {item.tool}: status={item.run_status}, "
                    f"runtime={item.runtime_minutes} min, findings={item.total_findings}"
                )
            )

    if prev_verdict is not None and prev_verdict.status != "ACCEPT":
        lines.extend(["", "## Previous Attempt Failures"])
        lines.append(
            "Your previous decision was rejected for the reasons below. "
            "Produce a NEW, corrected decision that resolves every one of them."
        )
        for label, items in (
            ("hard_failures", prev_verdict.hard_failures),
            ("regeneration_reasons", prev_verdict.regeneration_reasons),
            ("rule_failures", prev_verdict.rule_failures),
            ("reasons", prev_verdict.reasons),
        ):
            for item in items:
                lines.append(f"- {label}: {item}")

    return "\n".join(lines)


def _build_percategory_user_prompt(
    packet: Step1EvidencePacket,
    matrix: ActionByEvidenceMatrix,
    category: str,
    w_recall: float,
    w_precision: float,
    pct_by_tool: dict[str, float],
) -> str:
    if w_recall > w_precision:
        lean = "recall-leaning"
    elif w_recall < w_precision:
        lean = "precision-leaning"
    else:
        lean = "balanced"
    features = (packet.target_contract or {}).get("features", {}) or {}
    solc = features.get("primary_solidity_version") or packet.target_contract.get("solidity_version") or "unknown"
    loc = features.get("loc_total", "unknown")
    lines = [
        f"## User Preference: w_recall={w_recall:.2f}, w_precision={w_precision:.2f} ({lean})",
        f"## Target Contract (φ): solc={solc} loc_total={loc}",
        f"## Budget: tool_slots={matrix.budget_profile.tool_slots} "
        "(context only; the global tool budget across categories is reconciled after all categories decide)",
        "",
        "## Per-Category Evidence Matrix",
    ]
    # RAG evidence is inlined into the matrix slots above (tier + full text + limitations),
    # so the candidate's whole decision sits in one place — no separate ## RAG Tool Knowledge
    # section to cross-reference. (`_rag_tool_knowledge_lines` is still used by the single path.)
    lines.extend(_evidence_matrix_block(packet, matrix, category, pct_by_tool, inline_rag=True))
    return "\n".join(lines)


def _step1_anchor_tool(packet: Step1EvidencePacket) -> str | None:
    if packet.primary_attention.primary_tool:
        return packet.primary_attention.primary_tool
    if packet.certification.certified_primary:
        return packet.certification.certified_primary
    if packet.certification.candidate_set:
        return packet.certification.candidate_set[0]
    for score in sorted(packet.score_panel.nominal_scores, key=lambda item: item.rank):
        return score.tool
    return None


def _response_schema() -> dict:
    """Minimal output contract: per target category, only the replace-with-whom decision.

    Categories absent from `replacements` mean "keep the primary"; everything else
    (tool_categories, selected_tools, primary_tool, action, four-slot evidence) is
    assembled deterministically from the matrix in `_parse_and_assemble`.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "replacements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "category": {"type": "string"},
                        "tool": {"type": "string"},
                    },
                    "required": ["category", "tool"],
                },
            },
        },
        "required": ["replacements"],
    }


def _build_selected_plan(action: CandidateAction) -> list[SelectedToolEntry]:
    if action.action_type == "RUN_PRIMARY":
        return [SelectedToolEntry(tool=action.tools[0], role="STARTER", execution_order=1)]
    if action.action_type == "RUN_ROBUST_SINGLE":
        return [SelectedToolEntry(tool=action.tools[0], role="SINGLE", execution_order=1)]
    if action.action_type == "CONTINUE_HEDGE":
        return [SelectedToolEntry(tool=action.tools[0], role="CONTINUATION", execution_order=1)]
    return []


def _build_planned_selected_plan(
    selected_tools: list[str],
    primary_tool: str | None,
) -> list[SelectedToolEntry]:
    if not selected_tools:
        return []
    ordered_tools: list[str] = []
    if primary_tool and primary_tool in selected_tools:
        ordered_tools.append(primary_tool)
    for tool in selected_tools:
        if tool not in ordered_tools:
            ordered_tools.append(tool)
    entries: list[SelectedToolEntry] = []
    for index, tool in enumerate(ordered_tools, start=1):
        role = "STARTER" if index == 1 else "COMPLEMENT"
        entries.append(SelectedToolEntry(tool=tool, role=role, execution_order=index))
    return entries


def _build_budget_usage(action: CandidateAction, budget: BudgetProfile) -> BudgetUsage:
    return BudgetUsage(
        limit=budget,
        estimated_use=action.estimated_budget,
        remaining_after_plan=BudgetProfile(
            tool_slots=budget.tool_slots - action.estimated_budget.tool_slots,
            runtime_cap_minutes=budget.runtime_cap_minutes - action.estimated_budget.runtime_cap_minutes,
            alert_cap=budget.alert_cap,
        ),
    )


_ALERT_ORDER = {"low": 0, "medium": 1, "high": 2}


def _planned_budget_usage(
    selected_tools: list[str],
    packet: Step1EvidencePacket,
    budget: BudgetProfile,
) -> BudgetUsage:
    table = {entry.tool: entry for entry in packet.tool_table}
    runtime = 0.0
    alert = "low"
    for tool in selected_tools:
        entry = table.get(tool)
        if entry is None:
            continue
        runtime += entry.tool_cost.expected_runtime_minutes or 0.0
        if _ALERT_ORDER[entry.tool_cost.alert_risk] > _ALERT_ORDER[alert]:
            alert = entry.tool_cost.alert_risk
    estimated = BudgetProfile(
        tool_slots=len(selected_tools),
        runtime_cap_minutes=runtime,
        alert_cap=alert,
    )
    return BudgetUsage(
        limit=budget,
        estimated_use=estimated,
        remaining_after_plan=BudgetProfile(
            tool_slots=budget.tool_slots - estimated.tool_slots,
            runtime_cap_minutes=budget.runtime_cap_minutes - estimated.runtime_cap_minutes,
            alert_cap=budget.alert_cap,
        ),
    )


def _sorted_candidate_cards(
    packet: Step1EvidencePacket, matrix: ActionByEvidenceMatrix, category: str
) -> list[EvidenceCard]:
    """Eligible non-primary feasible candidate cards for one category, sorted (pre top-by-tool)."""
    primary_tool = packet.primary_attention.primary_tool
    feasible_tools = {entry.tool for entry in packet.tool_table if entry.feasible}
    cat_cards = [
        card
        for card in matrix.evidence_cards
        if card.evidence_type == "per_category_detected_total"
        and card.category == category
        and card.tool != primary_tool
        and card.tool in feasible_tools
        and _card_assignment_eligible(card, packet)
    ]
    if category_group(packet, category) == "low_support":
        local_cards = [c for c in cat_cards if card_scope_text(c) == "local"]
        cat_cards = local_cards or [
            c for c in cat_cards if card_scope_text(c) == "external_dataset"
        ]
    return sorted(
        cat_cards,
        key=lambda card: (
            card_scene_priority(packet, card),
            -(card.value.rate if card.value and card.value.rate is not None else -1.0),
            -(card.value.total if card.value and card.value.total is not None else 0),
            card.tool or "",
            card.evidence_id,
        ),
    )


def _candidate_cards_by_category(
    packet: Step1EvidencePacket, matrix: ActionByEvidenceMatrix
) -> dict[str, list[EvidenceCard]]:
    """Top eligible non-primary candidate recall cards per target category.

    Single source of truth shared with `_evidence_matrix_block` via
    `_sorted_candidate_cards`, so the assembler binds exactly to the candidates the
    LLM saw in the prompt matrix.
    """
    return {
        category: _top_cards_by_tool(_sorted_candidate_cards(packet, matrix, category))
        for category in attention_categories(packet)
    }


def _caveat_ref_for_group(packet: Step1EvidencePacket, category: str) -> list[str]:
    if category_group(packet, category) == "confirmed_weak":
        return ["step1.primary_attention.confirmed_weak_categories"]
    return ["step1.primary_attention.low_support_categories"]


def _owner_assignment(
    packet: Step1EvidencePacket,
    matrix: ActionByEvidenceMatrix,
    category: str,
    card: EvidenceCard,
    primary_tool: str,
    primary_rate: float | None,
) -> CategoryAssignment:
    """Assemble a complement-owner assignment from the chosen matrix candidate row.

    Evidence refs are taken from the matrix, never authored by the LLM, so every
    citation is real by construction.
    """
    tool = card.tool or ""
    value = card.value
    rag = _rag_refs_by_slot(matrix, category=category, tool=tool)

    for_refs = [card.evidence_id] + list(category_capability_pro_refs(matrix, category=category, tool=tool))
    for_claims = [
        ActionEvidenceClaim(
            claim=(
                f"{tool} has {_candidate_prompt_scope(packet, card)} recall "
                f"R_hat={rate_text(getattr(value, 'rate', None))} "
                f"(tp/GT={count_text(getattr(value, 'detected', None), getattr(value, 'total', None))}) "
                f"for {category}."
            ),
            evidence_refs=for_refs,
        )
    ]

    cand_rate = getattr(value, "rate", None)
    compare_claims: list[ActionEvidenceClaim] = []
    if cand_rate is not None:
        if primary_rate is None:
            rel, prim_text = "stronger than", "unsupported"
        elif cand_rate > primary_rate:
            rel, prim_text = "stronger than", rate_text(primary_rate)
        elif cand_rate < primary_rate:
            rel, prim_text = "weaker than", rate_text(primary_rate)
        else:
            rel, prim_text = "comparable to", rate_text(primary_rate)
        compare_claims.append(
            ActionEvidenceClaim(
                claim=f"{tool} is {rel} {primary_tool} on {category} ({rate_text(cand_rate)} vs {prim_text}).",
                evidence_refs=[card.evidence_id] + list(rag["COMPARE"]),
            )
        )

    against_claims = [
        ActionEvidenceClaim(
            claim=f"{tool} carries a category-specific false-positive risk on {category}.",
            evidence_refs=[ref],
        )
        for ref in _fp_precision_risk_refs(matrix, category=category, tool=tool)
    ]
    against_claims += [
        ActionEvidenceClaim(claim=f"A passage opposes {tool} on {category}.", evidence_refs=[ref])
        for ref in rag["AGAINST"]
    ]
    gap_claims = [
        ActionEvidenceClaim(claim=f"No-evidence note for {tool} on {category}.", evidence_refs=[ref])
        for ref in rag["GAP"]
    ]
    assignment_type = "local_owner" if card_scope_text(card) == "local" else "near_scene_owner"
    return CategoryAssignment(
        category=category,
        owner_tool=tool,
        assignment_type=assignment_type,
        for_claims=for_claims,
        against_claims=against_claims,
        compare_claims=compare_claims,
        gap_claims=gap_claims,
        caveat_refs=_caveat_ref_for_group(packet, category),
        unrelated_external_only=False,
    )


def _primary_assignment(
    packet: Step1EvidencePacket,
    matrix: ActionByEvidenceMatrix,
    category: str,
    primary_tool: str,
    primary_rate: float | None,
) -> CategoryAssignment:
    ref = rcov_evidence_id(primary_tool, category)
    refs = [ref] if any(c.evidence_id == ref for c in matrix.evidence_cards) else ["step1.recall_coverage.matrix"]
    return CategoryAssignment(
        category=category,
        owner_tool=primary_tool,
        assignment_type="primary_all",
        for_claims=[
            ActionEvidenceClaim(
                claim=f"{primary_tool} retains {category} at matched-scene recall R_hat={rate_text(primary_rate)}.",
                evidence_refs=refs,
            )
        ],
        against_claims=[],
        compare_claims=[],
        gap_claims=[],
        caveat_refs=_caveat_ref_for_group(packet, category),
        unrelated_external_only=False,
    )


def _gap_assignment(
    packet: Step1EvidencePacket,
    category: str,
    candidate_cards: list[EvidenceCard],
) -> CategoryAssignment:
    refs = [c.evidence_id for c in candidate_cards] or ["step1.primary_attention.low_support_categories"]
    return CategoryAssignment(
        category=category,
        owner_tool=None,
        assignment_type="gap",
        for_claims=[],
        against_claims=[],
        compare_claims=[],
        gap_claims=[
            ActionEvidenceClaim(
                claim=(
                    f"No complement owner is assigned for {category}; the available non-primary rows "
                    f"are weak or unsupported."
                ),
                evidence_refs=refs,
            )
        ],
        caveat_refs=_caveat_ref_for_group(packet, category),
        unrelated_external_only=False,
    )


def _primary_has_eligible_recall(entry) -> bool:
    if entry is None:
        return False
    return is_assignment_eligible(
        getattr(entry, "detected", None),
        getattr(entry, "effective_total", None),
        getattr(entry, "R_hat", None),
    )


def _parse_and_assemble(
    raw: dict,
    matrix: ActionByEvidenceMatrix,
    budget: BudgetProfile,
    packet: Step1EvidencePacket | None = None,
) -> Step2DecisionCertificate:
    if packet is None:
        raise CegoError("CEGO assembly requires the Step1 evidence packet.")
    primary_tool = _step1_anchor_tool(packet)
    if not primary_tool:
        raise CegoError("CEGO assembly has no Step1 anchor primary tool.")

    target_categories = attention_categories(packet)
    candidate_cards = _candidate_cards_by_category(packet, matrix)
    local_by_key = _rcov_by_tool_category(packet.recall_coverage)

    # 1. parse + validate the LLM's replace-with-whom decisions.
    #    category absent from `replacements` (or naming a non-candidate) => keep the primary.
    chosen: dict[str, EvidenceCard] = {}
    for item in raw.get("replacements", []):
        if not isinstance(item, dict):
            continue
        category = item.get("category")
        tool = item.get("tool")
        if category not in target_categories or not isinstance(tool, str):
            continue
        card = next((c for c in candidate_cards.get(category, []) if c.tool == tool), None)
        if card is not None:
            chosen[category] = card

    # 2. budget: distinct complement tools <= tool_slots - 1 (the primary occupies one slot).
    #    if exceeded, keep the highest-recall complement tools and revert the rest to keep-primary.
    max_complements = max(0, budget.tool_slots - 1)
    if len(set(card.tool for card in chosen.values())) > max_complements:
        best_rate: dict[str, float] = {}
        for card in chosen.values():
            rate = card.value.rate if card.value and card.value.rate is not None else -1.0
            best_rate[card.tool] = max(best_rate.get(card.tool, -1.0), rate)
        keep = set(sorted(best_rate, key=lambda t: -best_rate[t])[:max_complements])
        chosen = {cat: card for cat, card in chosen.items() if card.tool in keep}

    try:
        # 3. assemble one assignment for every target category (evidence bound from the matrix).
        assignments: list[CategoryAssignment] = []
        for category in target_categories:
            primary_entry = local_by_key.get((primary_tool, category))
            primary_rate = getattr(primary_entry, "R_hat", None)
            if category in chosen:
                assignments.append(
                    _owner_assignment(packet, matrix, category, chosen[category], primary_tool, primary_rate)
                )
            elif _primary_has_eligible_recall(primary_entry):
                assignments.append(_primary_assignment(packet, matrix, category, primary_tool, primary_rate))
            else:
                assignments.append(_gap_assignment(packet, category, candidate_cards.get(category, [])))

        # 4. derive everything else deterministically from the picks.
        tool_categories: dict[str, list[str]] = {primary_tool: ["ALL"]}
        for category, card in chosen.items():
            tool_categories.setdefault(card.tool, [])
            if category not in tool_categories[card.tool]:
                tool_categories[card.tool].append(category)
        complement_tools = list(dict.fromkeys(card.tool for card in chosen.values()))
        selected_tools = [primary_tool] + complement_tools

        if chosen:
            decision_type, selected_action_id = "PLAN_COMPOSITION", "plan_tool_composition"
            owned = ", ".join(f"{card.tool}:{cat}" for cat, card in chosen.items())
            summary = f"Composition anchored on {primary_tool}; complement owners {owned}."
        else:
            decision_type, selected_action_id = "RUN_PRIMARY", "run_primary"
            summary = f"No complement beats the primary on the target categories; running {primary_tool} alone."

        return Step2DecisionCertificate(
            decision_type=decision_type,
            selected_action_id=selected_action_id,
            selected_plan=_build_planned_selected_plan(selected_tools, primary_tool),
            primary_tool=primary_tool,
            tool_categories=tool_categories,
            category_assignments=assignments,
            budget=_planned_budget_usage(selected_tools, packet, budget),
            forbidden_claims_attestation=ForbiddenClaimsAttestation(),
            short_summary=summary,
        )
    except (IndexError, TypeError, ValidationError, ValueError) as exc:
        raise CegoError(f"CEGO response could not be assembled: {exc}") from exc


def _run_cego_per_category(
    client: OpenAICompatClient,
    model: str,
    packet: Step1EvidencePacket,
    matrix: ActionByEvidenceMatrix,
    w_recall: float,
    w_precision: float,
) -> dict:
    """Per-category scaffolded fan-out -> merged {"replacements":[...]}.

    One parallel LLM call per attention category that has >=1 candidate. A single
    category's failure degrades to keep-primary; if EVERY attempted category fails,
    raise CegoError (likely endpoint outage). The merged replacements are validated
    against each category's candidate slate before being returned.
    """
    explain = os.getenv("TOOLRANK_CEGO_EXPLAIN", "").lower() in {"1", "true", "yes"}
    cards_by_cat = _candidate_cards_by_category(packet, matrix)
    targets = [c for c, cards in cards_by_cat.items() if cards]
    if not targets:
        return {"replacements": []}
    pct = _scene_weighted_precision_percentile(packet)
    system_prompt = _build_percategory_system_prompt()
    schema = _percategory_response_schema()

    def _one(category: str) -> tuple[str, dict | None]:
        user_prompt = _build_percategory_user_prompt(
            packet, matrix, category, w_recall, w_precision, pct
        )
        raw = create_json_chat_completion(
            client=client, model=model, system_prompt=system_prompt,
            user_prompt=user_prompt, schema=schema, raise_on_error=True,
        )
        return category, raw

    results: dict[str, dict | None] = {}
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
        futures = {pool.submit(_one, c): c for c in targets}
        for fut in futures:
            category = futures[fut]
            try:
                cat, raw = fut.result()
                results[cat] = raw
            except Exception as exc:  # per-category degrade
                failures.append(category)
                if explain:
                    print(f"[cego per-category] {category}: FAILED -> keep_primary ({exc})", file=sys.stderr)

    if failures and len(failures) == len(targets):
        raise CegoError(f"All per-category CEGO calls failed: {failures}")

    replacements: list[dict] = []
    for category in targets:
        raw = results.get(category)
        if not isinstance(raw, dict):
            continue
        decision = raw.get("decision") or {}
        if explain:
            print(
                f"[cego per-category] {category}: "
                f"q1={raw.get('q1_best_recall')!r} q2={raw.get('q2_fp_warnings')!r} "
                f"q3={raw.get('q3_fp_applicability')!r} "
                f"q4_primary_compare={raw.get('q4_primary_compare')!r} "
                f"q5_tradeoff={raw.get('q5_tradeoff')!r} "
                f"decision={decision}",
                file=sys.stderr,
            )
        if decision.get("action") != "replace":
            continue
        tool = decision.get("tool")
        allowed = {c.tool for c in cards_by_cat.get(category, [])}
        if isinstance(tool, str) and tool in allowed:
            replacements.append({"category": category, "tool": tool})
    return {"replacements": replacements}


def run_cego(
    client: OpenAICompatClient,
    model: str,
    packet: Step1EvidencePacket,
    matrix: ActionByEvidenceMatrix,
    run_history: list[ToolRunSummary] | None = None,
    prev_verdict: CheckerVerdict | None = None,
    w_recall: float | None = None,
    w_precision: float | None = None,
) -> Step2DecisionCertificate:
    """Top-level entry point: build the prompt, call the LLM, parse the response, and assemble the certificate."""
    mode = os.getenv("TOOLRANK_CEGO_MODE", "per_category").strip().lower()
    if mode == "single":
        try:
            raw = create_json_chat_completion(
                client=client,
                model=model or DEFAULT_OPENAI_MODEL,
                system_prompt=_build_system_prompt(),
                user_prompt=_build_user_prompt(packet, matrix, run_history, prev_verdict),
                schema=_response_schema(),
                raise_on_error=True,
            )
        except OpenAICompatError as exc:
            raise CegoError(f"CEGO LLM call failed: {exc}") from exc

        if raw is None:
            raise CegoError("CEGO LLM returned no data.")
        if not isinstance(raw, dict):
            raise CegoError(f"CEGO LLM returned invalid data: {json.dumps(raw, ensure_ascii=False)}")
        return _parse_and_assemble(raw, matrix, matrix.budget_profile, packet)

    # per_category (default)
    wr = 0.5 if w_recall is None else w_recall
    wp = 0.5 if w_precision is None else w_precision
    try:
        merged = _run_cego_per_category(client, model or DEFAULT_OPENAI_MODEL, packet, matrix, wr, wp)
    except OpenAICompatError as exc:
        raise CegoError(f"CEGO LLM call failed: {exc}") from exc
    return _parse_and_assemble(merged, matrix, matrix.budget_profile, packet)
