from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from toolrank.cego import _prompt_payload
from toolrank.dace_rag import _runtime_cards, build_action_evidence_matrix
from toolrank.dataset_kb import load_performance_db
from toolrank.evidence_packet import build_tool_table
from toolrank.engine import _primary_runtime_outcome
from toolrank.plan_runtime import plan_constraint_reasons
from toolrank.retrieval import load_toolcards
from toolrank.scene_scoring import select_primary
from toolrank.schemas import (
    ContractFeatures,
    DatasetProfile,
    ExecutionSchedule,
    PerformanceEntry,
    PerformanceKnowledgeBase,
    RuntimeLiteratureObservation,
    RuntimeLiteratureSummary,
    ToolPerformanceObservation,
)
from toolrank.schemas_v2 import (
    BudgetProfile,
    NominalToolScore,
    SceneNeighbor,
    ScenePool,
    ScorePanel,
    Stage2Status,
)
from tests.stage2_fixtures import budget, stage2_context


ROOT = Path(__file__).resolve().parents[1]


def _observation(
    observation_id: str,
    *,
    paper_id: str,
    tool: str = "a",
    seconds: float = 10.0,
    basis: str = "per_contract",
) -> dict:
    return {
        "observation_id": observation_id,
        "tool": tool,
        "paper_id": paper_id,
        "title": f"Paper {paper_id}",
        "authors": ["Researcher"],
        "year": 2025,
        "venue": "Test venue",
        "doi": None,
        "source_url": "https://example.com/paper.pdf",
        "evidence_locator": "PDF p.1, Table 1",
        "tool_identity": "Exact evaluated tool",
        "dataset": "Test dataset",
        "input_profile": "Solidity source",
        "reported_value": seconds,
        "reported_unit": "seconds",
        "reported_basis": basis,
        "runtime_seconds": seconds,
        "runtime_basis": basis,
        "normalization_formula": "reported directly",
        "independent": True,
        "admitted_to_summary": True,
        "scheduling_eligible": False,
        "limitations": ["DESCRIPTIVE_ONLY"],
    }


def _summary(
    summary_id: str,
    observation_ids: list[str],
    *,
    tool: str = "a",
    basis: str | None = "per_contract",
    mean_seconds: float | None = 10.0,
    precision: int | None = 1,
    source_seconds: list[float] | None = None,
) -> dict:
    if not observation_ids:
        formula = "null (no admissible observations)"
    else:
        values = source_seconds or [float(mean_seconds)]
        terms = " + ".join(format(value, ".15g") for value in values)
        formula = (
            f"({terms}) / {len(observation_ids)}"
            if len(observation_ids) > 1
            else f"{terms} / 1"
        )
    return {
        "summary_id": summary_id,
        "tool": tool,
        "aggregation": "unweighted_arithmetic_mean_of_paper_level_means",
        "runtime_basis": basis,
        "runtime_unit": "seconds",
        "constituent_observation_ids": observation_ids,
        "n": len(observation_ids),
        "formula": formula,
        "precision_decimal_places": precision,
        "mean_seconds": mean_seconds,
        "cross_paper_mean": len(observation_ids) > 1,
        "inclusion_policy": "Independent homogeneous paper-level means only.",
        "exclusions": ["Unsupported evidence remains in the research audit."],
        "scheduling_eligible": False,
        "limitations": ["DESCRIPTIVE_SUMMARY_NOT_SCHEDULABLE"],
    }


def _literature_kb(
    observations: list[dict],
    summaries: list[dict],
    *,
    entries: list[PerformanceEntry] | None = None,
) -> PerformanceKnowledgeBase:
    return PerformanceKnowledgeBase.model_validate(
        {
            "knowledge_base_type": "performance",
            "criteria": {
                "runtime_unit": "seconds",
                "runtime_basis_default": "per_contract",
            },
            "runtime_literature_observations": observations,
            "runtime_literature_summaries": summaries,
            "entries": [entry.model_dump(mode="json") for entry in (entries or [])],
        }
    )


def test_packaged_literature_summaries_replay_exactly() -> None:
    kb = load_performance_db(ROOT / "toolcards" / "performance_db.json")
    summaries = {summary.tool: summary for summary in kb.runtime_literature_summaries}
    expected = {
        "gptscan": (21.845, 2, "per_kloc", True),
        "honeybadger": (78.57, 4, "per_contract", True),
        "sailfish": (23.6766667, 3, "per_contract", True),
        "vulhunter": (4.4, 1, "per_contract", False),
        "smartian": (None, 0, None, False),
        "mando-hgt": (None, 0, None, False),
    }

    assert len(kb.runtime_literature_observations) == 10
    assert set(summaries) == set(expected)
    observations = {
        observation.observation_id: observation
        for observation in kb.runtime_literature_observations
    }
    for tool, (mean, count, basis, cross_paper) in expected.items():
        summary = summaries[tool]
        assert summary.mean_seconds == mean
        assert summary.n == count
        assert summary.runtime_basis == basis
        assert summary.cross_paper_mean is cross_paper
        assert summary.scheduling_eligible is False
        if count:
            values = [
                observations[observation_id].runtime_seconds
                for observation_id in summary.constituent_observation_ids
            ]
            assert round(math.fsum(values) / count, summary.precision_decimal_places) == mean
        else:
            assert summary.constituent_observation_ids == []
            assert summary.precision_decimal_places is None


def test_literature_round_trip_preserves_atomic_provenance() -> None:
    kb = load_performance_db(ROOT / "toolcards" / "performance_db.json")
    replayed = PerformanceKnowledgeBase.model_validate_json(
        kb.model_dump_json(by_alias=True)
    )

    assert replayed.runtime_literature_observations == kb.runtime_literature_observations
    assert replayed.runtime_literature_summaries == kb.runtime_literature_summaries
    assert all(item.evidence_locator for item in replayed.runtime_literature_observations)
    assert all(item.source_url.startswith("https://") for item in replayed.runtime_literature_observations)


def test_summary_rejects_copied_paper_identity() -> None:
    observations = [
        _observation("lit_a", paper_id="paper_same", seconds=10.0),
        _observation("lit_b", paper_id="paper_same", seconds=20.0),
    ]
    summary = _summary(
        "summary_a",
        ["lit_a", "lit_b"],
        mean_seconds=15.0,
        precision=1,
        source_seconds=[10.0, 20.0],
    )

    with pytest.raises(ValidationError, match="independent paper identities"):
        _literature_kb(observations, [summary])


@pytest.mark.parametrize(
    "summary_update",
    [
        {"mean_seconds": 10.1},
        {"formula": "999 / 1"},
        {"n": 2},
        {"constituent_observation_ids": ["lit_missing"]},
    ],
)
def test_summary_rejects_non_replayable_arithmetic_or_membership(
    summary_update: dict,
) -> None:
    observation = _observation("lit_a", paper_id="paper_a")
    summary = {**_summary("summary_a", ["lit_a"]), **summary_update}

    with pytest.raises(ValidationError):
        _literature_kb([observation], [summary])


def test_summary_rejects_mixed_per_contract_and_per_kloc_constituents() -> None:
    observations = [
        _observation("lit_contract", paper_id="paper_contract"),
        _observation(
            "lit_kloc",
            paper_id="paper_kloc",
            seconds=20.0,
            basis="per_kloc",
        ),
    ]
    summary = _summary(
        "summary_mixed",
        ["lit_contract", "lit_kloc"],
        mean_seconds=15.0,
        source_seconds=[10.0, 20.0],
    )

    with pytest.raises(ValidationError, match="homogeneous runtime basis"):
        _literature_kb(observations, [summary])


@pytest.mark.parametrize("basis", ["campaign_cap", "component_only"])
def test_campaign_and_component_values_cannot_be_literature_mean_inputs(
    basis: str,
) -> None:
    with pytest.raises(ValidationError):
        RuntimeLiteratureObservation.model_validate(
            _observation("lit_bad", paper_id="paper_bad", basis=basis)
        )


def test_null_and_identity_summary_contracts_are_truthful() -> None:
    identity = RuntimeLiteratureSummary.model_validate(
        _summary("summary_identity", ["lit_a"], mean_seconds=4.4, precision=1)
    )
    null_summary = RuntimeLiteratureSummary.model_validate(
        _summary(
            "summary_null",
            [],
            basis=None,
            mean_seconds=None,
            precision=None,
        )
    )

    assert identity.cross_paper_mean is False
    assert null_summary.n == 0
    assert null_summary.mean_seconds is None
    assert null_summary.runtime_basis is None

    invalid = _summary(
        "summary_invalid", [], basis=None, mean_seconds=0.0, precision=None
    )
    with pytest.raises(ValidationError):
        RuntimeLiteratureSummary.model_validate(invalid)


def test_summary_exclusions_may_be_empty_but_limitations_remain_required() -> None:
    all_admissible = {
        **_summary("summary_all_admissible", ["lit_a"]),
        "exclusions": [],
    }

    summary = RuntimeLiteratureSummary.model_validate(all_admissible)

    assert summary.exclusions == []
    with pytest.raises(ValidationError):
        RuntimeLiteratureSummary.model_validate(
            {**all_admissible, "limitations": []}
        )


def test_packaged_cross_paper_means_are_absent_from_raw_runtime_fields() -> None:
    payload = json.loads(
        (ROOT / "toolcards" / "performance_db.json").read_text(encoding="utf-8")
    )
    cross_paper_means = {
        summary["tool"]: summary["mean_seconds"]
        for summary in payload["runtime_literature_summaries"]
        if summary["cross_paper_mean"]
    }
    raw_by_tool: dict[str, list[float]] = {}
    for entry in payload["entries"]:
        for observation in entry.get("tool_performance_data", []):
            tool = "".join(
                character
                for character in observation["tool_name"].lower()
                if character.isalnum()
            )
            metrics = observation.get("metrics", {})
            for field in (
                "time_sec",
                "execution_time_avg",
                "execution_time_avg_average_s",
            ):
                value = metrics.get(field)
                if isinstance(value, (int, float)):
                    raw_by_tool.setdefault(tool, []).append(float(value))

    for tool, mean_seconds in cross_paper_means.items():
        key = "".join(character for character in tool if character.isalnum())
        assert mean_seconds not in raw_by_tool.get(key, [])

    vulhunter = next(
        summary
        for summary in payload["runtime_literature_summaries"]
        if summary["tool"] == "vulhunter"
    )
    assert vulhunter["mean_seconds"] == 4.4
    assert vulhunter["cross_paper_mean"] is False


def test_packaged_summaries_remain_non_schedulable_and_do_not_create_provenance() -> None:
    kb = load_performance_db(ROOT / "toolcards" / "performance_db.json")
    selected_tools = {
        "gptscan",
        "honeybadger",
        "sailfish",
        "vulhunter",
        "smartian",
        "mando-hgt",
    }
    cards = [
        card for card in load_toolcards(ROOT / "toolcards") if card.tool_id in selected_tools
    ]
    table = build_tool_table(
        cards,
        ContractFeatures(
            source_kind="sol",
            primary_solidity_version="0.8.20",
            loc_total=1000,
            file_count=1,
        ),
        BudgetProfile(tool_slots=6, runtime_cap_minutes=60.0),
        kb,
        ScenePool(),
    )

    assert {entry.tool for entry in table} == selected_tools
    for entry in table:
        assert entry.tool_cost.expected_runtime_minutes is None
        assert entry.tool_cost.runtime_provenance is None
        summaries = entry.tool_cost.runtime_evidence.descriptive_literature_summaries
        assert len(summaries) == 1
        assert summaries[0].tool == entry.tool
        assert summaries[0].scheduling_eligible is False


def test_literature_summary_matches_toolcard_display_name_alias() -> None:
    observation = _observation(
        "lit_gptscan_alias",
        paper_id="paper_gptscan_alias",
        tool="GPTScan",
    )
    summary = _summary(
        "summary_gptscan_alias",
        ["lit_gptscan_alias"],
        tool="GPTScan",
    )
    kb = _literature_kb([observation], [summary])
    gptscan = next(
        card for card in load_toolcards(ROOT / "toolcards") if card.tool_id == "gptscan"
    )

    cost = build_tool_table(
        [gptscan],
        ContractFeatures(
            source_kind="sol",
            primary_solidity_version="0.8.20",
            loc_total=100,
            file_count=1,
        ),
        BudgetProfile(tool_slots=1, runtime_cap_minutes=1.0),
        kb,
        ScenePool(),
    )[0].tool_cost

    summaries = cost.runtime_evidence.descriptive_literature_summaries
    assert [item.tool for item in summaries] == ["GPTScan"]
    assert cost.expected_runtime_minutes is None
    assert cost.runtime_provenance is None


def test_literature_summary_reaches_dace_card_and_cego_payload_without_runtime_value() -> None:
    kb = load_performance_db(ROOT / "toolcards" / "performance_db.json")
    gptscan = next(
        card for card in load_toolcards(ROOT / "toolcards") if card.tool_id == "gptscan"
    )
    cost = build_tool_table(
        [gptscan],
        ContractFeatures(
            source_kind="sol",
            primary_solidity_version="0.8.20",
            loc_total=1000,
            file_count=1,
        ),
        BudgetProfile(tool_slots=1, runtime_cap_minutes=60.0),
        kb,
        ScenePool(),
    )[0].tool_cost
    context = stage2_context()
    context.stage1.tool_table[0].tool_cost = cost
    matrix = build_action_evidence_matrix(context, budget())

    card = next(card for card in _runtime_cards(context) if card.tool == "a")
    assert card.value.value is None
    assert card.scope["descriptive_literature_summaries"][0]["mean_seconds"] == 21.845
    assert card.scope["descriptive_literature_summaries"][0]["scheduling_eligible"] is False
    assert "LITERATURE_SUMMARY_DESCRIPTIVE_NOT_SCHEDULABLE" in card.limitations

    payload = json.loads(
        _prompt_payload(
            context,
            matrix,
            None,
            w_recall=0.5,
            w_precision=0.5,
        )
    )
    runtime = payload["tool_runtime_evidence"]["a"]
    assert runtime["expected_runtime_minutes"] is None
    assert runtime["provenance"] is None
    assert (
        runtime["evidence_quality"]["descriptive_literature_summaries"][0]["mean_seconds"]
        == 21.845
    )


def test_literature_summary_cannot_change_raw_runtime_selection() -> None:
    entry = PerformanceEntry(
        source_id="raw",
        dataset_profile=DatasetProfile(dataset_name="raw", solc=["0.8.x"]),
        tool_performance_data=[
            ToolPerformanceObservation(
                tool_name="a",
                metrics={
                    "execution_time_avg": 60.0,
                    "runtime_unit": "seconds",
                    "runtime_basis": "per_contract",
                },
            )
        ],
    )
    observation = _observation(
        "lit_a",
        paper_id="paper_a",
        seconds=999.0,
    )
    summary = _summary(
        "summary_a",
        ["lit_a"],
        mean_seconds=999.0,
        precision=1,
    )
    with_literature = _literature_kb([observation], [summary], entries=[entry])
    without_literature = PerformanceKnowledgeBase(
        knowledge_base_type="performance",
        criteria={
            "runtime_unit": "seconds",
            "runtime_basis_default": "per_contract",
        },
        entries=[entry],
    )
    scene = ScenePool(
        neighbors=[
            SceneNeighbor(
                slice_id="raw",
                benchmark_family="raw",
                paper_id="raw",
                weight=1.0,
                distance=0.0,
            )
        ]
    )
    features = ContractFeatures(
        source_kind="sol",
        primary_solidity_version="0.8.20",
        loc_total=100,
        file_count=1,
    )
    card = next(
        card for card in load_toolcards(ROOT / "toolcards") if card.tool_id == "solhint"
    ).model_copy(update={"tool_id": "a", "tool_name": "a"})
    costs = [
        build_tool_table(
            [card],
            features,
            BudgetProfile(tool_slots=1, runtime_cap_minutes=60.0),
            kb,
            scene,
        )[0].tool_cost
        for kb in (without_literature, with_literature)
    ]

    assert [cost.expected_runtime_minutes for cost in costs] == [1.0, 1.0]
    assert [cost.runtime_provenance.selected_source_id for cost in costs] == ["raw", "raw"]
    assert (
        costs[1].runtime_evidence.descriptive_literature_summaries[0].mean_seconds
        == 999.0
    )


def test_literature_only_mean_cannot_change_stage1_tie_or_stage2_budget() -> None:
    observation = _observation(
        "lit_b",
        paper_id="paper_b",
        tool="b",
        seconds=0.1,
    )
    summary = _summary(
        "summary_b",
        ["lit_b"],
        tool="b",
        mean_seconds=0.1,
        precision=1,
    )
    kb = _literature_kb([observation], [summary])
    base_card = next(
        card for card in load_toolcards(ROOT / "toolcards") if card.tool_id == "solhint"
    )
    cards = [
        base_card.model_copy(update={"tool_id": tool, "tool_name": tool})
        for tool in ("a", "b")
    ]
    scene = ScenePool(
        neighbors=[
            SceneNeighbor(
                slice_id="scene",
                benchmark_family="scene",
                paper_id="scene",
                weight=1.0,
                distance=0.0,
            )
        ]
    )
    table = build_tool_table(
        cards,
        ContractFeatures(
            source_kind="sol",
            primary_solidity_version="0.8.20",
            loc_total=100,
            file_count=1,
        ),
        BudgetProfile(tool_slots=2, runtime_cap_minutes=1.0),
        kb,
        scene,
    )
    scores = ScorePanel(
        nominal_scores=[
            NominalToolScore(
                tool=tool,
                S_scene=1.0,
                rank=1,
                support_mass=1.0,
                preferred_metric_value=1.0,
            )
            for tool in ("a", "b")
        ]
    )

    selection = select_primary(scene, scores, table)
    assert selection.primary_tool == "a"
    assert all(entry.tool_cost.expected_runtime_minutes is None for entry in table)
    timeout = ExecutionSchedule(
        tool_timeout_seconds=1.0,
        timeout_source="explicit",
    )
    assert plan_constraint_reasons(["b"], table, timeout) == ["RUNTIME_UNKNOWN:b"]
    assert timeout.tool_timeout_seconds == 1.0

    packet = stage2_context().stage1.model_copy(deep=True)
    packet.tool_table = table
    packet.primary_selection = packet.primary_selection.model_copy(
        update={"primary_tool": "b", "eligible_tools": ["a", "b"]}
    )
    outcome = _primary_runtime_outcome(
        packet,
        BudgetProfile(tool_slots=2, runtime_cap_minutes=1.0),
    )
    assert outcome.status == Stage2Status.NO_EXECUTABLE_PLAN
    assert outcome.reason_codes == ["PRIMARY_RUNTIME_UNKNOWN"]
