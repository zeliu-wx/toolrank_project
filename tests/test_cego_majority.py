from __future__ import annotations

import pytest
from pydantic import ValidationError

import toolrank.cego as cego_module
from toolrank.cego import (
    CEGO_SAMPLE_COUNT,
    CEGO_TEMPERATURE,
    CegoError,
    _SampleOutcome,
    _aggregate_proposals,
    _response_schema,
    assemble_decision,
    run_cego,
)
from toolrank.dace_rag import build_action_evidence_matrix
from toolrank.openai_compat import OpenAICompatClient, OpenAICompatError
from toolrank.schemas_v2 import (
    CegoProposalSample,
    PrimaryAttention,
    RecallCoverageMatrix,
    Stage2EvidenceContext,
)
from tests.stage2_fixtures import budget, stage2_context


def _valid(index: int, complements: list[dict]) -> _SampleOutcome:
    return _SampleOutcome(
        index=index,
        status="VALID",
        proposal=CegoProposalSample.model_validate({"complements": complements}),
    )


def _unusable(index: int, status: str) -> _SampleOutcome:
    return _SampleOutcome(index=index, status=status, proposal=None)


def _two_category_context() -> Stage2EvidenceContext:
    base = stage2_context()
    second_category = "access_control"
    cloned_rows = [
        row.model_copy(
            update={
                "category": second_category,
                **(
                    {"n_eff": 15.0, "support_level": "eligible"}
                    if row.tool == "c"
                    else {}
                ),
            }
        )
        for row in base.recall_coverage.matrix
    ]
    cloned_performance = [
        row.model_copy(
            update={
                "category": second_category,
                "evidence_id": row.evidence_id.replace("reentrancy", second_category),
                **({"n_eff": 15.0} if row.tool == "c" else {}),
            }
        )
        for row in base.performance_db_view
    ]
    cloned_decision = base.primary_category_decisions[0].model_copy(
        update={"category": second_category}
    )
    return Stage2EvidenceContext(
        stage1=base.stage1,
        required_categories=["reentrancy", second_category],
        category_diagnostics=base.category_diagnostics,
        recall_coverage=RecallCoverageMatrix(
            matrix=[*base.recall_coverage.matrix, *cloned_rows]
        ),
        performance_db_view=[*base.performance_db_view, *cloned_performance],
        tool_overall_metrics=base.tool_overall_metrics,
        primary_category_decisions=[
            *base.primary_category_decisions,
            cloned_decision,
        ],
        primary_attention=PrimaryAttention(
            primary_tool="a",
            required_categories=["reentrancy", second_category],
            under_evidenced_categories=["reentrancy", second_category],
        ),
        dace_rag_focus=base.dace_rag_focus,
    )


def test_k3_majority_is_independent_per_category_and_merges_winner_refs() -> None:
    outcomes = [
        _valid(
            0,
            [
                {
                    "category": "reentrancy",
                    "tool": "b",
                    "evidence_refs": ["z", "a", "a"],
                },
                {
                    "category": "access_control",
                    "tool": "c",
                    "evidence_refs": ["c1"],
                },
            ],
        ),
        _valid(
            1,
            [
                {
                    "category": "reentrancy",
                    "tool": "b",
                    "evidence_refs": ["b", "a"],
                }
            ],
        ),
        _valid(
            2,
            [
                {
                    "category": "reentrancy",
                    "tool": "c",
                    "evidence_refs": ["loser"],
                },
                {
                    "category": "access_control",
                    "tool": "c",
                    "evidence_refs": ["c2"],
                },
            ],
        ),
    ]

    aggregate = _aggregate_proposals(
        outcomes,
        ["reentrancy", "access_control", "reentrancy"],
    )

    assert aggregate.model_dump() == {
        "complements": [
            {
                "category": "reentrancy",
                "tool": "b",
                "evidence_refs": ["a", "b", "z"],
            },
            {
                "category": "access_control",
                "tool": "c",
                "evidence_refs": ["c1", "c2"],
            },
        ]
    }
    assert "loser" not in {
        ref
        for proposal in aggregate.complements
        for ref in proposal.evidence_refs
    }

    context = _two_category_context()
    limit = budget(slots=3)
    matrix = build_action_evidence_matrix(context, limit)
    certificate = assemble_decision(
        aggregate.model_dump(),
        context,
        matrix,
        limit,
    )
    assert [assignment.category for assignment in certificate.category_assignments] == [
        "reentrancy",
        "access_control",
    ]
    assert certificate.category_assignments[0].owner_tools == ["a", "b"]
    assert certificate.category_assignments[1].owner_tools == ["a", "c"]


def test_valid_omission_is_a_primary_only_vote() -> None:
    aggregate = _aggregate_proposals(
        [
            _valid(0, []),
            _valid(1, []),
            _valid(
                2,
                [
                    {
                        "category": "reentrancy",
                        "tool": "b",
                        "evidence_refs": ["ev_rcov_b_reentrancy"],
                    }
                ],
            ),
        ],
        ["reentrancy"],
    )
    assert aggregate.complements == []

    context = stage2_context()
    limit = budget()
    matrix = build_action_evidence_matrix(context, limit)
    certificate = assemble_decision(aggregate.model_dump(), context, matrix, limit)
    assert certificate.selected_action_id == "run_primary"
    assert certificate.category_assignments[0].owner_tools == ["a"]


@pytest.mark.parametrize(
    ("ballots", "expected_tool"),
    [
        (("b", "b", "failed"), "b"),
        (("b", "failed", "malformed"), None),
        (("b", "c", "failed"), None),
    ],
)
def test_unusable_samples_abstain_without_lowering_the_two_vote_threshold(
    ballots: tuple[str, str, str],
    expected_tool: str | None,
) -> None:
    outcomes: list[_SampleOutcome] = []
    for index, ballot in enumerate(ballots):
        if ballot == "failed":
            outcomes.append(_unusable(index, "REQUEST_FAILED"))
        elif ballot == "malformed":
            outcomes.append(_unusable(index, "MALFORMED"))
        else:
            outcomes.append(
                _valid(
                    index,
                    [
                        {
                            "category": "reentrancy",
                            "tool": ballot,
                            "evidence_refs": [f"ref_{index}"],
                        }
                    ],
                )
            )

    aggregate = _aggregate_proposals(outcomes, ["reentrancy"])
    assert [proposal.tool for proposal in aggregate.complements] == (
        [expected_tool] if expected_tool else []
    )


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
def test_strict_sample_model_rejects_ambiguous_or_out_of_schema_payloads(
    payload: dict,
) -> None:
    with pytest.raises(ValidationError):
        CegoProposalSample.model_validate(payload)


def test_response_schema_is_derived_from_the_strict_sample_model() -> None:
    assert _response_schema() == CegoProposalSample.model_json_schema()


def test_run_cego_makes_exactly_three_sequential_calls_after_early_agreement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        {
            "complements": [
                {"category": "reentrancy", "tool": "b", "evidence_refs": [ref]}
            ]
        }
        for ref in ("z", "b", "a")
    ]
    calls: list[dict] = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return responses[len(calls) - 1]

    monkeypatch.setattr(cego_module, "create_json_chat_completion", fake_completion)
    context = stage2_context()
    limit = budget()
    matrix = build_action_evidence_matrix(context, limit)

    certificate = run_cego(
        OpenAICompatClient("https://example.test/v1", "key", 1.0),
        "test-model",
        context,
        matrix,
    )

    assert CEGO_SAMPLE_COUNT == 3
    assert len(calls) == 3
    assert [call["temperature"] for call in calls] == [CEGO_TEMPERATURE] * 3
    assert CEGO_TEMPERATURE == 0.0
    assert all("n" not in call for call in calls)
    for field in ("model", "system_prompt", "user_prompt", "schema"):
        assert [call[field] for call in calls] == [calls[0][field]] * 3
    assert certificate.category_assignments[0].owner_tools == ["a", "b"]
    assert certificate.category_assignments[0].for_claims[0].evidence_refs == [
        "a",
        "b",
        "z",
    ]


def test_run_cego_all_unusable_samples_raises_after_three_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_completion(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OpenAICompatError("transport failed")
        if calls == 2:
            return None
        return {
            "complements": [
                {"category": "reentrancy", "tool": "b", "evidence_refs": ["one"]},
                {"category": "reentrancy", "tool": "c", "evidence_refs": ["two"]},
            ]
        }

    def fail_assembly(*_args, **_kwargs):
        raise AssertionError("unusable raw samples must not be assembled")

    monkeypatch.setattr(cego_module, "create_json_chat_completion", fake_completion)
    monkeypatch.setattr(cego_module, "assemble_decision", fail_assembly)
    context = stage2_context()
    limit = budget()
    matrix = build_action_evidence_matrix(context, limit)

    with pytest.raises(CegoError, match="three CEGO samples were unusable"):
        run_cego(
            OpenAICompatClient("https://example.test/v1", "key", 1.0),
            "test-model",
            context,
            matrix,
        )

    assert calls == 3
