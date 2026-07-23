from __future__ import annotations

from pathlib import Path

import pytest

from toolrank.dace_rag import _runtime_cards
from toolrank.dataset_kb import _gate_numeric_ranges, load_performance_db
from toolrank.engine import _primary_runtime_outcome
from toolrank.evidence_packet import build_tool_table
from toolrank.retrieval import load_toolcards
from toolrank.scene_scoring import compute_scene_scores, select_primary
from toolrank.schemas import (
    ContractFeatures,
    D1Metric,
    DatasetProfile,
    PerformanceEntry,
    PerformanceKnowledgeBase,
    ToolCard,
    ToolPerformanceObservation,
)
from toolrank.schemas_v2 import (
    BudgetProfile,
    SceneNeighbor,
    ScenePool,
    Stage1EvidencePacket,
    Stage2Status,
    ToolCostEntry,
)
from tests.stage2_fixtures import stage2_context


def _card(
    tool_id: str,
    tool_name: str | None = None,
    *,
    toolcard_runtime_seconds: float | None = None,
) -> ToolCard:
    metrics = None
    if toolcard_runtime_seconds is not None:
        metrics = {"default": D1Metric(time_sec=toolcard_runtime_seconds)}
    return ToolCard(
        tool_id=tool_id,
        tool_name=tool_name or tool_id,
        d7_input_support={"sol": True},
        d8_mode="static",
        d2_solidity_versions="0.4.0-0.8.99",
        d3_multifile_support="yes",
        d1_metrics=metrics,
    )


def _entry(
    source_id: str,
    observations: list[tuple[str, dict[str, float]]],
) -> PerformanceEntry:
    return PerformanceEntry(
        source_id=source_id,
        dataset_profile=DatasetProfile(
            dataset_name=f"dataset-{source_id}",
            solc=["0.8.x"],
        ),
        tool_performance_data=[
            ToolPerformanceObservation(
                tool_name=tool,
                metrics=D1Metric.model_validate(metrics),
            )
            for tool, metrics in observations
        ],
    )


def _kb(*entries: PerformanceEntry) -> PerformanceKnowledgeBase:
    return PerformanceKnowledgeBase(
        knowledge_base_type="performance",
        criteria={
            "runtime_unit": "seconds",
            "runtime_basis_default": "per_contract",
        },
        entries=list(entries),
    )


def _scene(*sources: tuple[str, float]) -> ScenePool:
    return ScenePool(
        neighbors=[
            SceneNeighbor(
                slice_id=f"{source_id}-{index}",
                benchmark_family=source_id,
                paper_id=source_id,
                weight=weight,
                distance=0.0,
            )
            for index, (source_id, weight) in enumerate(sources)
        ]
    )


def _build(
    cards: list[ToolCard],
    kb: PerformanceKnowledgeBase,
    scene: ScenePool | None = None,
):
    return build_tool_table(
        cards,
        ContractFeatures(
            source_kind="sol",
            primary_solidity_version="0.8.20",
            file_count=1,
        ),
        BudgetProfile(tool_slots=5, runtime_cap_minutes=1000.0),
        kb,
        scene
        if scene is not None
        else _scene(
            *[
                (entry.source_id, 1.0 / len(kb.entries))
                for entry in kb.entries
            ]
        )
        if kb.entries
        else ScenePool(),
    )


def _by_tool(table):
    return {entry.tool: entry for entry in table}


def _provenance(
    *,
    seconds: float = 120.0,
    source_id: str = "paper-1",
    dataset_name: str = "benchmark-1",
    candidate_source_ids: list[str] | None = None,
) -> dict:
    candidate_ids = candidate_source_ids if candidate_source_ids is not None else [source_id]
    return {
        "method": "scene_weighted_p90_compatible_dataset_proxy",
        "selected_source_id": source_id,
        "selected_dataset_name": dataset_name,
        "selected_metric_field": "execution_time_avg",
        "selected_source_runtime_seconds": seconds,
        "selected_runtime_seconds": seconds,
        "runtime_basis": "per_contract",
        "target_compiler_bucket": "0.8.x",
        "support_mass": 1.0,
        "candidate_source_ids": candidate_ids,
        "candidates": [
            {
                "source_id": candidate_id,
                "dataset_name": dataset_name,
                "metric_field": "execution_time_avg",
                "source_runtime_seconds": seconds,
                "schedulable_runtime_seconds": seconds,
                "runtime_unit": "seconds",
                "runtime_basis": "per_contract",
                "scene_weight": 1.0 / len(candidate_ids),
                "compiler_match": True,
                "included_in_quantile": True,
            }
            for candidate_id in candidate_ids
        ],
    }


def test_toolcard_runtime_is_ignored_when_performance_db_has_no_runtime() -> None:
    table = _build([_card("a", toolcard_runtime_seconds=600.0)], _kb())

    assert table[0].tool_cost.expected_runtime_minutes is None
    assert table[0].tool_cost.runtime_provenance is None


def test_runtime_field_priority_and_seconds_to_minutes_conversion() -> None:
    cards = [_card(tool) for tool in ("a", "b", "c", "d", "e", "f")]
    kb = _kb(
        _entry(
            "paper",
            [
                (
                    "a",
                    {
                        "time_sec": 120.0,
                        "execution_time_avg": 600.0,
                        "execution_time_avg_average_s": 900.0,
                    },
                ),
                (
                    "b",
                    {
                        "execution_time_avg": 180.0,
                        "execution_time_avg_average_s": 900.0,
                    },
                ),
                (
                    "c",
                    {
                        "execution_time_avg_average_s": 240.0,
                        "execution_time_avg_total_s": 999999.0,
                    },
                ),
                ("d", {"execution_time_avg_total_s": 999999.0}),
                (
                    "e",
                    {"time_sec": float("inf"), "execution_time_avg": 300.0},
                ),
                ("f", {"timeout_count": 42.0}),
            ],
        )
    )

    table = _by_tool(_build(cards, kb))

    assert table["a"].tool_cost.expected_runtime_minutes == 2.0
    assert table["a"].tool_cost.runtime_provenance.selected_metric_field == "time_sec"
    assert table["b"].tool_cost.expected_runtime_minutes == 3.0
    assert table["b"].tool_cost.runtime_provenance.selected_metric_field == "execution_time_avg"
    assert table["c"].tool_cost.expected_runtime_minutes == 4.0
    assert (
        table["c"].tool_cost.runtime_provenance.selected_metric_field
        == "execution_time_avg_average_s"
    )
    assert table["d"].tool_cost.expected_runtime_minutes is None
    assert table["e"].tool_cost.expected_runtime_minutes == 5.0
    assert table["e"].tool_cost.runtime_provenance.selected_metric_field == "execution_time_avg"
    assert table["f"].tool_cost.expected_runtime_minutes is None


@pytest.mark.parametrize(
    "field",
    ["time_sec", "execution_time_avg", "execution_time_avg_average_s"],
)
def test_dataset_gate_rejects_infinite_runtime_fields(field: str) -> None:
    entry = _entry("paper", [("a", {field: float("inf")})])

    reason = _gate_numeric_ranges(entry)

    assert reason is not None
    assert field in reason


def test_tool_name_alias_maps_runtime_to_canonical_tool_id() -> None:
    table = _build(
        [_card("canonical-tool", "Fancy Analyzer")],
        _kb(_entry("paper", [("Fancy Analyzer", {"execution_time_avg": 60.0})])),
    )

    assert table[0].tool == "canonical-tool"
    assert table[0].tool_cost.expected_runtime_minutes == 1.0


def test_ambiguous_tool_alias_is_not_assigned_to_either_owner() -> None:
    table = _by_tool(
        _build(
            [_card("alpha", "Shared"), _card("shared", "Beta")],
            _kb(_entry("paper", [("shared", {"execution_time_avg": 60.0})])),
        )
    )

    assert table["alpha"].tool_cost.expected_runtime_minutes is None
    assert table["shared"].tool_cost.expected_runtime_minutes is None


def test_duplicate_source_observations_use_maximum_seconds() -> None:
    table = _build(
        [_card("a")],
        _kb(
            _entry(
                "paper",
                [
                    ("a", {"execution_time_avg": 30.0}),
                    ("a", {"execution_time_avg": 90.0}),
                ],
            )
        ),
        _scene(("paper", 1.0)),
    )

    cost = table[0].tool_cost
    assert cost.expected_runtime_minutes == 1.5
    assert cost.runtime_provenance.candidate_source_ids == ["paper"]


def test_scene_linked_runtime_uses_weighted_p90_and_aggregates_source_weights() -> None:
    table = _build(
        [_card("a")],
        _kb(
            _entry("low", [("a", {"execution_time_avg": 60.0})]),
            _entry("p90", [("a", {"execution_time_avg": 120.0})]),
            _entry("tail", [("a", {"execution_time_avg": 600.0})]),
        ),
        _scene(("low", 0.2), ("low", 0.3), ("p90", 0.4), ("tail", 0.1)),
    )

    cost = table[0].tool_cost
    assert cost.expected_runtime_minutes == 2.0
    assert cost.runtime_provenance.method == "scene_weighted_p90_compatible_dataset_proxy"
    assert cost.runtime_provenance.selected_source_id == "p90"
    assert cost.runtime_provenance.selected_dataset_name == "dataset-p90"
    assert cost.runtime_provenance.candidate_source_ids == ["low", "p90", "tail"]


def test_zero_weight_scene_candidates_remain_unknown() -> None:
    table = _build(
        [_card("a")],
        _kb(
            _entry("one", [("a", {"execution_time_avg": 60.0})]),
            _entry("two", [("a", {"execution_time_avg": 180.0})]),
        ),
        _scene(("one", 0.0), ("two", 0.0)),
    )

    cost = table[0].tool_cost
    assert cost.expected_runtime_minutes is None
    assert cost.runtime_provenance is None
    assert cost.runtime_evidence.status == "INSUFFICIENT_RUNTIME_SUPPORT"


def test_no_scene_linked_runtime_does_not_use_global_max_fallback() -> None:
    table = _build(
        [_card("a")],
        _kb(
            _entry("one", [("a", {"execution_time_avg": 60.0})]),
            _entry("two", [("a", {"execution_time_avg": 180.0})]),
        ),
        _scene(("unrelated", 1.0)),
    )

    cost = table[0].tool_cost
    assert cost.expected_runtime_minutes is None
    assert cost.runtime_provenance is None
    assert cost.runtime_evidence.support_mass == 0.0


def test_kb_runtime_drives_stage1_tie_and_stage2_budget_without_reconversion() -> None:
    cards = [_card("a"), _card("b")]
    kb = _kb(
        _entry(
            "paper",
            [
                (
                    "a",
                    {"recall": 0.8, "precision": 0.8, "execution_time_avg": 120.0},
                ),
                (
                    "b",
                    {"recall": 0.8, "precision": 0.8, "execution_time_avg": 60.0},
                ),
            ],
        )
    )
    scene = _scene(("paper", 1.0))
    table = _build(cards, kb, scene)
    scores = compute_scene_scores(scene, kb, ["a", "b"], 0.5, 0.5)
    selection = select_primary(scene, scores, table)
    packet = Stage1EvidencePacket(
        tool_table=table,
        scene_pool=scene,
        score_panel=scores,
        primary_selection=selection,
    )

    assert _by_tool(table)["a"].tool_cost.expected_runtime_minutes == 2.0
    assert _by_tool(table)["b"].tool_cost.expected_runtime_minutes == 1.0
    assert selection.primary_tool == "b"

    outcome = _primary_runtime_outcome(
        packet,
        BudgetProfile(tool_slots=1, runtime_cap_minutes=0.75),
    )
    assert outcome.status == Stage2Status.NO_EXECUTABLE_PLAN
    assert outcome.reason_codes == ["PRIMARY_EXCEEDS_STAGE2_BUDGET"]
    assert outcome.estimated_plan_runtime_minutes == 1.0


def test_dace_runtime_card_cites_selected_performance_db_row() -> None:
    context = stage2_context()
    context.stage1.tool_table[0].tool_cost = ToolCostEntry(
        expected_runtime_minutes=2.0,
        runtime_provenance=_provenance(
            seconds=120.0,
            source_id="paper-1",
            dataset_name="benchmark-1",
            candidate_source_ids=["paper-1", "paper-2"],
        ),
    )

    card = next(card for card in _runtime_cards(context) if card.tool == "a")

    assert card.source.source_type == "paper_table_cell"
    assert card.source.paper_id == "paper-1"
    assert card.source.field_path == "tool_performance_data.metrics.execution_time_avg"
    assert card.scope["dataset_name"] == "benchmark-1"
    assert card.scope["runtime_estimation_method"] == "scene_weighted_p90_compatible_dataset_proxy"
    assert card.scope["candidate_source_ids"] == ["paper-1", "paper-2"]
    assert card.scope["runtime_unit"] == "minutes"
    assert card.scope["source_runtime_unit"] == "seconds"


def test_dace_unknown_runtime_card_has_minutes_unit_without_source_unit() -> None:
    context = stage2_context(b_runtime=None)

    card = next(card for card in _runtime_cards(context) if card.tool == "b")

    assert card.value.value is None
    assert card.source.source_type == "benchmark_metadata"
    assert card.scope["runtime_unit"] == "minutes"
    assert "source_runtime_unit" not in card.scope


def test_tool_cost_rejects_runtime_without_provenance() -> None:
    with pytest.raises(ValueError):
        ToolCostEntry(expected_runtime_minutes=2.0)


def test_tool_cost_rejects_provenance_without_runtime() -> None:
    with pytest.raises(ValueError):
        ToolCostEntry(runtime_provenance=_provenance())


@pytest.mark.parametrize("minutes", [0.0, float("inf")])
def test_tool_cost_rejects_non_positive_or_non_finite_minutes(minutes: float) -> None:
    with pytest.raises(ValueError):
        ToolCostEntry(
            expected_runtime_minutes=minutes,
            runtime_provenance=_provenance(seconds=120.0),
        )


@pytest.mark.parametrize("seconds", [0.0, float("inf")])
def test_tool_cost_rejects_non_positive_or_non_finite_seconds(seconds: float) -> None:
    with pytest.raises(ValueError):
        ToolCostEntry(
            expected_runtime_minutes=2.0,
            runtime_provenance=_provenance(seconds=seconds),
        )


def test_tool_cost_rejects_seconds_minutes_mismatch() -> None:
    with pytest.raises(ValueError):
        ToolCostEntry(
            expected_runtime_minutes=3.0,
            runtime_provenance=_provenance(seconds=120.0),
        )


def test_runtime_provenance_requires_selected_source_in_candidates() -> None:
    with pytest.raises(ValueError):
        ToolCostEntry(
            expected_runtime_minutes=2.0,
            runtime_provenance=_provenance(candidate_source_ids=["paper-2"]),
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"source_id": " "},
        {"dataset_name": " "},
        {"candidate_source_ids": ["paper-1", "paper-1"]},
        {"candidate_source_ids": ["paper-1", " "]},
    ],
)
def test_runtime_provenance_rejects_blank_or_duplicate_identity_fields(overrides: dict) -> None:
    with pytest.raises(ValueError):
        ToolCostEntry(
            expected_runtime_minutes=2.0,
            runtime_provenance=_provenance(**overrides),
        )


def test_packaged_performance_db_requires_scene_supported_runtime() -> None:
    project_root = Path(__file__).resolve().parents[1]
    cards = load_toolcards(project_root / "toolcards")
    kb = load_performance_db(project_root / "toolcards" / "performance_db.json")

    table = _build(cards, kb, ScenePool())
    known = {
        entry.tool
        for entry in table
        if entry.tool_cost.expected_runtime_minutes is not None
    }
    unknown = {entry.tool for entry in table} - known

    assert kb.criteria["runtime_unit"] == "seconds"
    assert kb.criteria["runtime_basis_default"] == "per_contract"
    assert known == set()
    assert unknown == {card.tool_id for card in cards}
