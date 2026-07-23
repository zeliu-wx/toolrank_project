from __future__ import annotations

import json

import pytest

import toolrank.cego as cego_module
from toolrank.cego import assemble_decision, run_cego
from toolrank.checker import check_decision
from toolrank.dace_rag import build_action_evidence_matrix
from toolrank.engine import decide_with_ceiling_fallback
from toolrank.openai_compat import OpenAICompatClient
from toolrank.schemas_v2 import CheckerVerdict
from tests.stage2_fixtures import budget, stage2_context


def test_exhausted_repairs_return_checked_primary_only_plan() -> None:
    context = stage2_context()
    limit = budget()
    matrix = build_action_evidence_matrix(context, limit)
    invalid = assemble_decision(
        {
            "complements": [
                {
                    "category": "reentrancy",
                    "tool": "b",
                    "evidence_refs": ["missing_ref"],
                }
            ]
        },
        context,
        matrix,
        limit,
    )

    calls = 0

    def run_cego(_context, _matrix, _previous):
        nonlocal calls
        calls += 1
        return invalid

    def check(certificate, checked_context, checked_matrix):
        return check_decision(certificate, checked_context, checked_matrix)

    certificate, verdict = decide_with_ceiling_fallback(
        context=context,
        matrix=matrix,
        budget=limit,
        max_cego_retries=2,
        run_cego_fn=run_cego,
        check_fn=check,
    )

    assert calls == 3
    assert verdict.status == "ACCEPT"
    assert certificate.selected_action_id == "run_primary"
    assert certificate.category_assignments[0].owner_tools == ["a"]


def _proposal(ref: str) -> dict:
    return {
        "complements": [
            {
                "category": "reentrancy",
                "tool": "b",
                "evidence_refs": [ref],
            }
        ]
    }


def test_checker_repair_checks_one_aggregate_per_round_and_uses_fresh_votes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = stage2_context()
    limit = budget()
    matrix = build_action_evidence_matrix(context, limit)
    responses = [
        *[_proposal("missing_ref") for _ in range(3)],
        *[_proposal("ev_rcov_b_reentrancy") for _ in range(3)],
    ]
    prompts: list[dict] = []
    checker_verdicts: list[CheckerVerdict] = []

    def fake_completion(**kwargs):
        prompts.append(json.loads(kwargs["user_prompt"]))
        return responses[len(prompts) - 1]

    def run_round(current_context, current_matrix, previous):
        return run_cego(
            OpenAICompatClient("https://example.test/v1", "key", 1.0),
            "test-model",
            current_context,
            current_matrix,
            previous,
        )

    def check(certificate, checked_context, checked_matrix):
        verdict = check_decision(certificate, checked_context, checked_matrix)
        checker_verdicts.append(verdict)
        return verdict

    monkeypatch.setattr(cego_module, "create_json_chat_completion", fake_completion)
    certificate, verdict = decide_with_ceiling_fallback(
        context=context,
        matrix=matrix,
        budget=limit,
        max_cego_retries=2,
        run_cego_fn=run_round,
        check_fn=check,
    )

    assert len(prompts) == 6
    assert len(checker_verdicts) == 2
    assert checker_verdicts[0].status == "REJECT"
    assert verdict.status == "ACCEPT"
    assert [prompt["previous_checker_failures"] for prompt in prompts[:3]] == [
        [],
        [],
        [],
    ]
    assert [prompt["previous_checker_failures"] for prompt in prompts[3:]] == [
        checker_verdicts[0].rule_failures,
        checker_verdicts[0].rule_failures,
        checker_verdicts[0].rule_failures,
    ]
    assert certificate.category_assignments[0].for_claims[0].evidence_refs == [
        "ev_rcov_b_reentrancy"
    ]
    assert "missing_ref" not in certificate.model_dump_json()


def test_three_rejected_k3_rounds_make_nine_samples_then_check_primary_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = stage2_context()
    limit = budget()
    matrix = build_action_evidence_matrix(context, limit)
    calls = 0
    checker_verdicts: list[CheckerVerdict] = []

    def fake_completion(**_kwargs):
        nonlocal calls
        calls += 1
        return _proposal(f"missing_ref_round_{(calls - 1) // 3}")

    def run_round(current_context, current_matrix, previous):
        return run_cego(
            OpenAICompatClient("https://example.test/v1", "key", 1.0),
            "test-model",
            current_context,
            current_matrix,
            previous,
        )

    def check(certificate, checked_context, checked_matrix):
        verdict = check_decision(certificate, checked_context, checked_matrix)
        checker_verdicts.append(verdict)
        return verdict

    monkeypatch.setattr(cego_module, "create_json_chat_completion", fake_completion)
    certificate, verdict = decide_with_ceiling_fallback(
        context=context,
        matrix=matrix,
        budget=limit,
        max_cego_retries=2,
        run_cego_fn=run_round,
        check_fn=check,
    )

    assert calls == 9
    assert [item.status for item in checker_verdicts] == [
        "REJECT",
        "REJECT",
        "REJECT",
        "ACCEPT",
    ]
    assert verdict.status == "ACCEPT"
    assert certificate.selected_action_id == "run_primary"
    assert certificate.category_assignments[0].owner_tools == ["a"]
