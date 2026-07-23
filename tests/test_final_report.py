from __future__ import annotations

import json

import pytest

import toolrank.engine as engine
import toolrank.report_explanation as report_explanation
from toolrank.cego import build_primary_only_certificate
from toolrank.checker import check_decision
from toolrank.dace_rag import build_action_evidence_matrix
from toolrank.openai_compat import OpenAICompatClient, OpenAICompatError
from toolrank.report_explanation import generate_combination_explanation
from toolrank.report_parser import PARSER_PROJECTION_MARKER
from toolrank.schemas import (
    CombinationExplanation,
    CompositionPlan,
    ExecutionResult,
    ToolExecutionStatus,
)
from tests.stage2_fixtures import budget, stage2_context


_EXPECTED_QUALITATIVE_TEXT_CONTRACT = (
    "The `text` field must be a qualitative explanation of the checked plan. It may "
    "discuss only the accepted primary, accepted complements, checked category owners, "
    "RuleChecker acceptance, and the certificate's plan and budget conclusions. Never "
    "include the raw audit fields `detected` or `total`, `R_hat`, `n_eff`, a category "
    "rate, any other ambiguous `rate`, or their values in `text`. Never name an "
    "unselected tool or infer why any candidate was rejected. Statistical details "
    "remain in machine evidence."
)


def _checked_primary_only_plan():
    context = stage2_context()
    limit = budget()
    matrix = build_action_evidence_matrix(context, limit)
    certificate = build_primary_only_certificate(context, matrix, limit)
    verdict = check_decision(certificate, context, matrix)
    assert verdict.status == "ACCEPT"
    return matrix, certificate, verdict


def test_successful_llm_explanation_is_separate_structured_post_checker_call(
    monkeypatch,
) -> None:
    matrix, certificate, verdict = _checked_primary_only_plan()
    certificate_before = certificate.model_dump(mode="json")
    matrix_before = matrix.model_dump(mode="json")
    captured: dict = {}
    valid_text = (
        "The RuleChecker-accepted plan keeps a as the immutable primary and sole "
        "owner of reentrancy, and the certificate records that the total runtime "
        "remains within the fixed budget."
    )

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return {
            "text": valid_text,
            "limitations": ["This explains planning evidence only."],
        }

    monkeypatch.setattr(
        report_explanation,
        "create_json_chat_completion",
        fake_completion,
    )
    client = OpenAICompatClient(
        base_url="https://example.invalid/v1",
        api_key="secret-sentinel",
        timeout_sec=1.0,
    )

    explanation = generate_combination_explanation(
        client=client,
        model="fake-explainer",
        certificate=certificate,
        checker_verdict=verdict,
        matrix=matrix,
        checker_enabled=True,
    )

    assert explanation.source == "LLM"
    assert explanation.model == "fake-explainer"
    assert explanation.text == valid_text
    assert captured["temperature"] == 0.0
    assert captured["model"] == "fake-explainer"
    assert captured["raise_on_error"] is True
    assert _EXPECTED_QUALITATIVE_TEXT_CONTRACT in captured["system_prompt"]
    assert _EXPECTED_QUALITATIVE_TEXT_CONTRACT in captured["user_prompt"]
    prompt_payload = json.loads(captured["user_prompt"])
    assert prompt_payload["explanation_text_contract"] == (
        _EXPECTED_QUALITATIVE_TEXT_CONTRACT
    )
    assert "matrix_owned_evidence" in prompt_payload
    assert "secret-sentinel" not in captured["user_prompt"]
    assert "api_key" not in captured["user_prompt"].lower()
    assert "raw_findings" not in captured["user_prompt"].lower()
    assert certificate.model_dump(mode="json") == certificate_before
    assert matrix.model_dump(mode="json") == matrix_before


@pytest.mark.parametrize(
    "text",
    [
        "The record has detected=120 and total=9406.",
        "The raw audit total=9406.",
        "The weighted R_hat is 0.005064 with n_eff=15.",
        "The category rate is 0.005064.",
        "The supporting evidence value is 0.005064.",
        "The supporting evidence value is 80%.",
        "The supporting evidence value is 12/15.",
        "The accepted plan uses a because B lacked ownership and budget.",
    ],
)
def test_llm_explanation_semantics_violation_has_honest_fallback(
    monkeypatch,
    text: str,
) -> None:
    matrix, certificate, verdict = _checked_primary_only_plan()
    certificate_before = certificate.model_dump(mode="json")
    matrix_before = matrix.model_dump(mode="json")

    monkeypatch.setattr(
        report_explanation,
        "create_json_chat_completion",
        lambda **_kwargs: {"text": text, "limitations": []},
    )

    explanation = generate_combination_explanation(
        client=OpenAICompatClient(
            base_url="https://example.invalid/v1",
            api_key="secret-sentinel",
            timeout_sec=1.0,
        ),
        model="fake-explainer",
        certificate=certificate,
        checker_verdict=verdict,
        matrix=matrix,
        checker_enabled=True,
    )

    assert explanation.source == "DETERMINISTIC_FALLBACK"
    assert explanation.model is None
    assert explanation.limitations == ["LLM_RESPONSE_SEMANTICS_INVALID"]
    assert certificate.model_dump(mode="json") == certificate_before
    assert matrix.model_dump(mode="json") == matrix_before


@pytest.mark.parametrize(
    ("response", "expected_reason"),
    [
        (OpenAICompatError("transport failed"), "LLM_REQUEST_FAILED"),
        ({"text": "", "limitations": []}, "LLM_RESPONSE_SCHEMA_INVALID"),
        (
            {
                "text": "Looks valid but attempts to emit plan controls.",
                "limitations": [],
                "tools": ["b"],
            },
            "LLM_RESPONSE_SCHEMA_INVALID",
        ),
        (
            {
                "text": "First paragraph.\n\nSecond paragraph.",
                "limitations": [],
            },
            "LLM_RESPONSE_SCHEMA_INVALID",
        ),
    ],
)
def test_failing_or_invalid_llm_explanation_has_honest_fallback(
    monkeypatch,
    response,
    expected_reason: str,
) -> None:
    matrix, certificate, verdict = _checked_primary_only_plan()

    def fake_completion(**_kwargs):
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(
        report_explanation,
        "create_json_chat_completion",
        fake_completion,
    )
    explanation = generate_combination_explanation(
        client=OpenAICompatClient(
            base_url="https://example.invalid/v1",
            api_key="secret-sentinel",
            timeout_sec=1.0,
        ),
        model="fake-explainer",
        certificate=certificate,
        checker_verdict=verdict,
        matrix=matrix,
        checker_enabled=True,
    )

    assert explanation.source == "DETERMINISTIC_FALLBACK"
    assert explanation.model is None
    assert expected_reason in explanation.limitations
    assert explanation.text


def test_missing_client_and_disabled_checker_never_fabricate_llm_provenance() -> None:
    matrix, certificate, verdict = _checked_primary_only_plan()

    missing_client = generate_combination_explanation(
        client=None,
        model="fake-explainer",
        certificate=certificate,
        checker_verdict=verdict,
        matrix=matrix,
        checker_enabled=True,
    )
    unchecked = generate_combination_explanation(
        client=OpenAICompatClient(
            base_url="https://example.invalid/v1",
            api_key="secret-sentinel",
            timeout_sec=1.0,
        ),
        model="fake-explainer",
        certificate=certificate,
        checker_verdict=verdict,
        matrix=matrix,
        checker_enabled=False,
    )

    assert missing_client.source == "DETERMINISTIC_FALLBACK"
    assert missing_client.model is None
    assert "LLM_CLIENT_UNAVAILABLE" in missing_client.limitations
    assert unchecked.source == "DETERMINISTIC_FALLBACK"
    assert unchecked.model is None
    assert "CHECKER_DISABLED" in unchecked.limitations


def test_invalid_client_and_nonaccepted_checker_do_not_make_a_request(monkeypatch) -> None:
    matrix, certificate, verdict = _checked_primary_only_plan()
    calls = 0

    def unexpected_completion(**_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("completion must not be called")

    monkeypatch.setattr(
        report_explanation,
        "create_json_chat_completion",
        unexpected_completion,
    )
    invalid_client = generate_combination_explanation(
        client=object(),  # type: ignore[arg-type]
        model="fake-explainer",
        certificate=certificate,
        checker_verdict=verdict,
        matrix=matrix,
        checker_enabled=True,
    )
    rejected = generate_combination_explanation(
        client=OpenAICompatClient(
            base_url="https://example.invalid/v1",
            api_key="secret-sentinel",
            timeout_sec=1.0,
        ),
        model="fake-explainer",
        certificate=certificate,
        checker_verdict=verdict.model_copy(update={"status": "REJECT"}),
        matrix=matrix,
        checker_enabled=True,
    )

    assert calls == 0
    assert invalid_client.source == "DETERMINISTIC_FALLBACK"
    assert invalid_client.model is None
    assert invalid_client.limitations == ["LLM_CLIENT_INVALID"]
    assert rejected.source == "DETERMINISTIC_FALLBACK"
    assert rejected.model is None
    assert rejected.limitations == ["CHECKER_NOT_ACCEPTED"]


def test_unexpected_explanation_programming_error_is_not_hidden(monkeypatch) -> None:
    matrix, certificate, verdict = _checked_primary_only_plan()

    def broken_completion(**_kwargs):
        raise AssertionError("programming defect")

    monkeypatch.setattr(
        report_explanation,
        "create_json_chat_completion",
        broken_completion,
    )

    with pytest.raises(AssertionError, match="programming defect"):
        generate_combination_explanation(
            client=OpenAICompatClient(
                base_url="https://example.invalid/v1",
                api_key="secret-sentinel",
                timeout_sec=1.0,
            ),
            model="fake-explainer",
            certificate=certificate,
            checker_verdict=verdict,
            matrix=matrix,
            checker_enabled=True,
        )


def test_persisted_report_keeps_raw_finding_empty_category_and_existing_fused_view(
    monkeypatch,
    tmp_path,
) -> None:
    original = {
        "check": "controlled-delegatecall",
        "category": "access_control",
        "confidence": "Medium",
        "description": "Controlled delegatecall",
        "tool_specific": {"sentinel": ["exact", {"nested": True}]},
    }
    composition = CompositionPlan(
        selected_tool_ids=["slither"],
        primary_tool_id="slither",
        complementary_tool_ids=[],
        category_owners={"arithmetic": ["slither"]},
    )
    explanation = CombinationExplanation(
        text="The checked plan keeps Slither as the sole selected primary.",
        source="LLM",
        model="fake-explainer",
        limitations=[],
    )
    execution = ExecutionResult(
        status="executed",
        selected_tool_ids=["slither"],
        primary_tool_id="slither",
        tool_statuses={"slither": ToolExecutionStatus(status="SUCCESS")},
        per_tool_findings={
            "slither": [
                {
                    PARSER_PROJECTION_MARKER: True,
                    "source_tool": "slither",
                    "category": "access_control",
                    "location": "Vault.sol:23",
                    "severity": "medium",
                    "confidence": None,
                    "explanation": "Controlled delegatecall",
                    "raw": original,
                }
            ]
        },
    )
    monkeypatch.setattr(engine, "build_execution_plan", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(engine, "execute_plan", lambda *_args, **_kwargs: execution)

    completed, fused, output_dir = engine._run_execution_pipeline(
        target_path=tmp_path / "Arithmetic.sol",
        composition=composition,
        combination_explanation=explanation,
        results_root=tmp_path / "results",
        runner_script=None,
        runner_cwd=None,
        gptscan_timeout_sec=10,
        openai_api_key=None,
        openai_api_base=None,
    )

    payload = json.loads((output_dir / "fused_report.json").read_text(encoding="utf-8"))
    categories = {result["category"]: result for result in payload["category_results"]}

    assert completed.status == "executed"
    assert fused.combination_explanation == explanation
    assert payload["combination_explanation"] == explanation.model_dump(mode="json")
    assert categories["arithmetic"]["owner_tools"] == ["slither"]
    assert categories["arithmetic"]["tools"]["slither"]["findings"] == []
    assert categories["access_control"]["owner_tools"] == ["slither"]
    assert categories["access_control"]["tools"]["slither"]["findings"] == [original]
    assert payload["findings"][0]["raw_findings"][0]["raw"] == original
