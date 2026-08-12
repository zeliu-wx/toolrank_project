"""Post-Checker explanation for the immutable selected tool combination."""

from __future__ import annotations

import json
import math
import re
from typing import Final
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from toolrank.openai_compat import (
    DEFAULT_OPENAI_MODEL,
    OpenAICompatClient,
    OpenAICompatError,
    create_json_chat_completion,
)
from toolrank.schemas import CombinationExplanation, CompositionPlan
from toolrank.schemas_v2 import (
    ActionByEvidenceMatrix,
    CheckerVerdict,
    Step2DecisionCertificate,
)


EXPLANATION_TEMPERATURE: Final = 0.0
EXPLANATION_TEXT_CONTRACT: Final = (
    "The `text` field must be a qualitative explanation of the checked plan. It may "
    "discuss only the accepted primary, accepted complements, checked category owners, "
    "RuleChecker acceptance, and the certificate's plan and budget conclusions. Never "
    "include the raw audit fields `detected` or `total`, `R_hat`, `n_eff`, a category "
    "rate, any other ambiguous `rate`, or statistical values in `text`. Ordinary "
    "decimal durations such as `0.5 minutes` are allowed. Never name an "
    "unselected tool or infer why any candidate was rejected. Statistical details "
    "remain in machine evidence."
)
_FORBIDDEN_EXPLANATION_STATISTICS: Final = re.compile(
    r"(?<!\w)(?:detected|r[_\s-]*hat|n[_\s-]*eff|rates?)(?!\w)",
    re.IGNORECASE,
)
_FORBIDDEN_TOTAL_AUDIT_FIELD: Final = re.compile(
    r"(?:`total`|(?<!\w)total(?!\w)(?=\s*(?:[=:]|\b(?:audit|counts?|field|is|was)\b)))",
    re.IGNORECASE,
)
_INHERENTLY_RATE_LIKE_VALUE: Final = re.compile(
    r"(?<![\w.-])(?:"
    r"(?:\d+(?:\.\d+)?|\.\d+)\s*%"
    r"|\d+\s*/\s*\d+"
    r")(?!\w|\.\d)",
)
_DECIMAL_VALUE: Final = re.compile(
    r"(?<![\w.-])(?:\d+\.\d+|\.\d+)(?!\w|\.\d)"
)
_DURATION_UNIT: Final = re.compile(
    r"^\s*(?:seconds?|minutes?|hours?)\b",
    re.IGNORECASE,
)
_STATISTICAL_VALUE_CONTEXT: Final = re.compile(
    r"(?<!\w)(?:"
    r"audit|categor(?:y|ies)|confidence|detect(?:ion|ed)?|evidence|metric|"
    r"precision|probability|proportion|rate|ratio|recall|score|statistic(?:al)?|"
    r"support(?:ing)?|value|weight"
    r")(?!\w)",
    re.IGNORECASE,
)

_SYSTEM_PROMPT = f"""You explain an already-fixed, RuleChecker-accepted tool combination.
Use the supplied immutable certificate and matrix-owned evidence only to describe the
accepted primary, accepted complements, checked category owners, Checker acceptance, and
the certificate's qualitative plan and budget conclusions. Do not propose alternatives,
change owners, tools, weights, action, checker result, or execution. Do not infer that the
target contains or lacks a vulnerability, and do not treat an empty result as evidence of
safety. {EXPLANATION_TEXT_CONTRACT} Return JSON only."""


class _ExplanationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def _text_is_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("explanation text cannot be blank")
        if "\n" in stripped or "\r" in stripped:
            raise ValueError("explanation text must be exactly one paragraph")
        return stripped

    @field_validator("limitations")
    @classmethod
    def _limitations_are_not_blank(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if len(normalized) != len(values):
            raise ValueError("explanation limitations cannot be blank")
        return normalized


def _deterministic_text(
    certificate: Step2DecisionCertificate,
    *,
    checked: bool,
) -> str:
    primary = certificate.primary_tool
    additions = [
        assignment
        for assignment in certificate.category_assignments
        if assignment.complement_tool is not None
    ]
    if additions:
        roles = "; ".join(
            f"{assignment.complement_tool} complements {primary} for {assignment.category}"
            for assignment in additions
        )
        selection = f"The fixed plan keeps {primary} as the immutable primary, while {roles}."
    else:
        selection = (
            f"The fixed plan keeps {primary} as the sole selected tool; the certificate "
            "adds no complement."
        )
    validation = (
        "The combination satisfies the RuleChecker-accepted certificate's recorded "
        "ownership and budget constraints."
        if checked
        else "This fallback does not claim independent RuleChecker acceptance."
    )
    return (
        f"{selection} {validation} This explanation describes planning evidence only and "
        "makes no claim about vulnerabilities in the target."
    )


def deterministic_combination_explanation(
    composition: CompositionPlan,
    *,
    reason: str = "CHECKED_PLANNING_CONTEXT_UNAVAILABLE",
) -> CombinationExplanation:
    """Build an honest fallback when only an executable composition is available."""
    complements = ", ".join(composition.complementary_tool_ids)
    if complements:
        selection = (
            f"The supplied composition keeps {composition.primary_tool_id} as primary and "
            f"adds {complements} only in the recorded owner sets."
        )
    else:
        selection = (
            f"The supplied composition keeps {composition.primary_tool_id} as the sole "
            "selected tool."
        )
    return CombinationExplanation(
        text=(
            f"{selection} This deterministic explanation reflects the fixed composition "
            "only and makes no claim about vulnerabilities in the target."
        ),
        source="DETERMINISTIC_FALLBACK",
        model=None,
        limitations=[reason],
    )


def _fallback(
    certificate: Step2DecisionCertificate,
    reason: str,
    *,
    checked: bool,
) -> CombinationExplanation:
    return CombinationExplanation(
        text=_deterministic_text(certificate, checked=checked),
        source="DETERMINISTIC_FALLBACK",
        model=None,
        limitations=[reason],
    )


def _prompt_payload(
    certificate: Step2DecisionCertificate,
    checker_verdict: CheckerVerdict,
    matrix: ActionByEvidenceMatrix,
) -> str:
    payload = {
        "schema": "checked_combination_explanation_v1",
        "explanation_text_contract": EXPLANATION_TEXT_CONTRACT,
        "immutable_checked_certificate": certificate.model_dump(mode="json"),
        "checker_verdict": checker_verdict.model_dump(mode="json"),
        "matrix_owned_evidence": {
            "stage1_evidence": matrix.stage1_evidence.model_dump(mode="json"),
            "ownership_panel": {
                category: panel.model_dump(mode="json")
                for category, panel in matrix.ownership_panel.items()
            },
            "budget_profile": matrix.budget_profile.model_dump(mode="json"),
            "evidence_cards": [
                card.model_dump(mode="json") for card in matrix.evidence_cards
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _matrix_tool_ids(matrix: ActionByEvidenceMatrix) -> set[str]:
    tool_ids = set(matrix.stage1_evidence.tools)
    tool_ids.add(matrix.stage1_evidence.primary_tool)
    for action in matrix.actions:
        tool_ids.update(action.tools)
    tool_ids.update(card.tool for card in matrix.evidence_cards if card.tool)
    for panel in matrix.ownership_panel.values():
        for candidates in (
            panel.eligible_candidates,
            panel.not_shortlisted_candidates,
            panel.under_evidenced_candidates,
            panel.rejected_candidates,
        ):
            tool_ids.update(candidate.tool for candidate in candidates)
    return tool_ids


def _text_satisfies_semantics(
    text: str,
    certificate: Step2DecisionCertificate,
    matrix: ActionByEvidenceMatrix,
) -> bool:
    if (
        _FORBIDDEN_EXPLANATION_STATISTICS.search(text)
        or _FORBIDDEN_TOTAL_AUDIT_FIELD.search(text)
        or _has_forbidden_statistical_value(text)
    ):
        return False

    selected_tool_ids = {certificate.primary_tool.casefold()}
    selected_tool_ids.update(entry.tool.casefold() for entry in certificate.selected_plan)
    selected_tool_ids.update(
        tool.casefold()
        for assignment in certificate.category_assignments
        for tool in assignment.owner_tools
    )
    unselected_tool_ids = sorted(
        (
            tool_id
            for tool_id in _matrix_tool_ids(matrix)
            if tool_id.casefold() not in selected_tool_ids
        ),
        key=len,
        reverse=True,
    )
    return not any(
        re.search(
            rf"(?<![\w.-]){re.escape(tool_id)}(?![\w.-])",
            text,
            re.IGNORECASE,
        )
        for tool_id in unselected_tool_ids
    )


def _has_forbidden_statistical_value(text: str) -> bool:
    """Reject rate-shaped values, but permit ordinary decimal durations."""
    if _INHERENTLY_RATE_LIKE_VALUE.search(text):
        return True
    for match in _DECIMAL_VALUE.finditer(text):
        if _DURATION_UNIT.match(text[match.end() :]):
            continue
        context = text[max(0, match.start() - 64) : match.end() + 64]
        if _STATISTICAL_VALUE_CONTEXT.search(context):
            return True
    return False


def _client_is_valid(client: object) -> bool:
    if not isinstance(client, OpenAICompatClient):
        return False
    if not isinstance(client.base_url, str) or not isinstance(client.api_key, str):
        return False
    parsed = urlparse(client.base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if not client.api_key.strip():
        return False
    return (
        isinstance(client.timeout_sec, (int, float))
        and not isinstance(client.timeout_sec, bool)
        and math.isfinite(float(client.timeout_sec))
        and client.timeout_sec > 0
    )


def generate_combination_explanation(
    *,
    client: OpenAICompatClient | None,
    model: str,
    certificate: Step2DecisionCertificate,
    checker_verdict: CheckerVerdict,
    matrix: ActionByEvidenceMatrix,
    checker_enabled: bool,
) -> CombinationExplanation:
    """Explain a fixed checked plan without creating any planning control fields."""
    if not checker_enabled:
        return _fallback(certificate, "CHECKER_DISABLED", checked=False)
    if checker_verdict.status != "ACCEPT":
        return _fallback(certificate, "CHECKER_NOT_ACCEPTED", checked=False)
    if client is None:
        return _fallback(certificate, "LLM_CLIENT_UNAVAILABLE", checked=True)
    if not _client_is_valid(client):
        return _fallback(certificate, "LLM_CLIENT_INVALID", checked=True)

    effective_model = (model or DEFAULT_OPENAI_MODEL).strip()
    if not effective_model:
        return _fallback(certificate, "LLM_MODEL_INVALID", checked=True)
    try:
        raw = create_json_chat_completion(
            client=client,
            model=effective_model,
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=_prompt_payload(certificate, checker_verdict, matrix),
            temperature=EXPLANATION_TEMPERATURE,
            schema=_ExplanationDraft.model_json_schema(),
            raise_on_error=True,
        )
    except OpenAICompatError:
        return _fallback(certificate, "LLM_REQUEST_FAILED", checked=True)

    try:
        draft = _ExplanationDraft.model_validate(raw)
    except (ValidationError, TypeError, ValueError):
        return _fallback(certificate, "LLM_RESPONSE_SCHEMA_INVALID", checked=True)
    if not _text_satisfies_semantics(draft.text, certificate, matrix):
        return _fallback(certificate, "LLM_RESPONSE_SEMANTICS_INVALID", checked=True)
    return CombinationExplanation(
        text=draft.text,
        source="LLM",
        model=effective_model,
        limitations=draft.limitations,
    )
