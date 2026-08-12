from __future__ import annotations

import pytest
from pydantic import ValidationError

import toolrank.cego as cego_module
from toolrank.cego import (
    CEGO_TEMPERATURE,
    CegoError,
    _response_schema,
    run_cego,
)
from toolrank.dace_rag import build_action_evidence_matrix
from toolrank.openai_compat import (
    DEFAULT_DEEPSEEK_MODEL,
    OpenAICompatClient,
    OpenAICompatError,
)
from toolrank.schemas_v2 import CegoProposal
from tests.stage2_fixtures import budget, stage2_context


def _client() -> OpenAICompatClient:
    return OpenAICompatClient("https://example.test/v1", "key", 1.0)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "complements": [
                {"category": "reentrancy", "tool": "b", "evidence_refs": ["one"]},
                {"category": "reentrancy", "tool": "c", "evidence_refs": ["two"]},
            ]
        },
        {
            "complements": [
                {"category": "reentrancy", "tool": "b", "evidence_refs": []}
            ]
        },
        {
            "complements": [
                {"category": " ", "tool": "b", "evidence_refs": ["one"]}
            ]
        },
        {
            "complements": [
                {"category": "reentrancy", "tool": " ", "evidence_refs": ["one"]}
            ]
        },
        {
            "complements": [
                {"category": "reentrancy", "tool": "b", "evidence_refs": [" "]}
            ]
        },
        {
            "complements": [
                {
                    "category": "reentrancy",
                    "tool": "b",
                    "evidence_refs": ["one"],
                    "weight": 1.0,
                }
            ]
        },
    ],
)
def test_strict_proposal_model_rejects_ambiguous_or_out_of_schema_payloads(
    payload: dict,
) -> None:
    with pytest.raises(ValidationError):
        CegoProposal.model_validate(payload)


def test_response_schema_is_derived_from_the_strict_proposal_model() -> None:
    assert _response_schema() == CegoProposal.model_json_schema()


def test_run_cego_makes_one_temperature_zero_request_and_uses_proposal_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = {
        "complements": [
            {
                "category": "reentrancy",
                "tool": "b",
                "evidence_refs": ["z", "b", "a", "z"],
            }
        ]
    }
    calls: list[dict] = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return response

    monkeypatch.setattr(cego_module, "create_json_chat_completion", fake_completion)
    context = stage2_context()
    limit = budget()
    matrix = build_action_evidence_matrix(context, limit)

    certificate = run_cego(_client(), "test-model", context, matrix)

    assert len(calls) == 1
    assert calls[0]["temperature"] == CEGO_TEMPERATURE == 0.0
    assert calls[0]["raise_on_error"] is True
    assert "n" not in calls[0]
    assert certificate.category_assignments[0].owner_tools == ["a", "b"]
    assert certificate.category_assignments[0].for_claims[0].evidence_refs == [
        "z",
        "b",
        "a",
    ]


def test_run_cego_uses_the_official_deepseek_model_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return {"complements": []}

    monkeypatch.setattr(cego_module, "create_json_chat_completion", fake_completion)
    monkeypatch.setattr(
        cego_module,
        "DEFAULT_OPENAI_MODEL",
        DEFAULT_DEEPSEEK_MODEL,
    )
    context = stage2_context()
    limit = budget()
    matrix = build_action_evidence_matrix(context, limit)

    run_cego(_client(), "", context, matrix)

    assert len(calls) == 1
    assert calls[0]["model"] == DEFAULT_DEEPSEEK_MODEL


def test_run_cego_request_failure_raises_after_one_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_completion(**_kwargs):
        nonlocal calls
        calls += 1
        raise OpenAICompatError("transport failed")

    monkeypatch.setattr(cego_module, "create_json_chat_completion", fake_completion)
    context = stage2_context()
    limit = budget()
    matrix = build_action_evidence_matrix(context, limit)

    with pytest.raises(CegoError, match="CEGO LLM call failed") as exc_info:
        run_cego(_client(), "test-model", context, matrix)

    assert calls == 1
    assert isinstance(exc_info.value.__cause__, OpenAICompatError)


@pytest.mark.parametrize(
    "response",
    [
        None,
        {},
        {
            "complements": [
                {"category": "reentrancy", "tool": "b", "evidence_refs": ["one"]},
                {"category": "reentrancy", "tool": "c", "evidence_refs": ["two"]},
            ]
        },
    ],
)
def test_run_cego_malformed_response_fails_without_assembly(
    monkeypatch: pytest.MonkeyPatch,
    response: object,
) -> None:
    calls = 0

    def fake_completion(**_kwargs):
        nonlocal calls
        calls += 1
        return response

    def fail_assembly(*_args, **_kwargs):
        raise AssertionError("malformed responses must not reach assembly")

    monkeypatch.setattr(cego_module, "create_json_chat_completion", fake_completion)
    monkeypatch.setattr(cego_module, "assemble_decision", fail_assembly)
    context = stage2_context()
    limit = budget()
    matrix = build_action_evidence_matrix(context, limit)

    with pytest.raises(CegoError, match="malformed proposal") as exc_info:
        run_cego(_client(), "test-model", context, matrix)

    assert calls == 1
    assert isinstance(exc_info.value.__cause__, ValidationError)


def test_single_proposal_still_uses_existing_assembly_constraints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_completion(**_kwargs):
        return {
            "complements": [
                {
                    "category": "reentrancy",
                    "tool": "c",
                    "evidence_refs": ["ev_rcov_c_reentrancy"],
                }
            ]
        }

    monkeypatch.setattr(cego_module, "create_json_chat_completion", fake_completion)
    context = stage2_context()
    limit = budget()
    matrix = build_action_evidence_matrix(context, limit)

    certificate = run_cego(_client(), "test-model", context, matrix)

    assert certificate.selected_action_id == "run_primary"
    assert certificate.category_assignments[0].owner_tools == ["a"]
