from __future__ import annotations

import json
from pathlib import Path
import pytest

from toolrank.cego import _prompt_payload
from toolrank.dace_rag import _runtime_cards, build_action_evidence_matrix
from toolrank.evidence_packet import build_tool_table
from toolrank.dataset_kb import load_performance_db
from toolrank.retrieval import load_toolcards
from toolrank.schemas import (
    ContractFeatures,
    D1Metric,
    DatasetProfile,
    PerformanceEntry,
    PerformanceKnowledgeBase,
    ToolCard,
    ToolPerformanceObservation,
)
from toolrank.schemas_v2 import BudgetProfile, SceneNeighbor, ScenePool
from tests.stage2_fixtures import budget, stage2_context


def _card() -> ToolCard:
    return ToolCard(
        tool_id="a",
        tool_name="a",
        d7_input_support={"sol": True},
        d8_mode="static",
        d2_solidity_versions="0.4.0-0.8.99",
        d3_multifile_support="yes",
    )


def _entry(
    source_id: str,
    seconds: float,
    *,
    solc: list[str] | None = None,
    loc_count: int | None = None,
    basis: str | None = None,
    metadata: dict[str, int] | None = None,
) -> PerformanceEntry:
    loc_profile = {}
    if loc_count is not None:
        loc_profile = {
            "loc_bin_counts_by_solc": {
                "100-200": {"0.8.x": loc_count},
            }
        }
    metric = {"execution_time_avg": seconds, **(metadata or {})}
    if basis is not None:
        metric["runtime_basis"] = basis
    return PerformanceEntry(
        source_id=source_id,
        dataset_profile=DatasetProfile(
            dataset_name=f"dataset-{source_id}",
            solc=solc if solc is not None else ["0.8.x"],
            loc_profile=loc_profile,
        ),
        tool_performance_data=[
            ToolPerformanceObservation(
                tool_name="a",
                metrics=D1Metric.model_validate(metric),
            )
        ],
    )


def _kb(*entries: PerformanceEntry) -> PerformanceKnowledgeBase:
    return PerformanceKnowledgeBase(
        knowledge_base_type="performance",
        criteria={
            "runtime_unit": "seconds",
            "runtime_basis_default": "per_contract",
            "loc_bins": [
                {"label": "0-100", "min_inclusive": 0, "max_exclusive": 100},
                {"label": "100-200", "min_inclusive": 100, "max_exclusive": 200},
            ],
        },
        entries=list(entries),
    )


def _scene(source_id: str, weight: float) -> ScenePool:
    return ScenePool(
        neighbors=[
            SceneNeighbor(
                slice_id=source_id,
                benchmark_family=source_id,
                paper_id=source_id,
                weight=weight,
                distance=0.0,
            )
        ]
    )


def _cost(
    kb: PerformanceKnowledgeBase,
    scene: ScenePool,
    *,
    loc_total: int = 150,
    target_version: str = "0.8.20",
):
    table = build_tool_table(
        [_card()],
        ContractFeatures(
            source_kind="sol",
            primary_solidity_version=target_version,
            loc_total=loc_total,
            file_count=1,
        ),
        BudgetProfile(tool_slots=2, runtime_cap_minutes=30.0),
        kb,
        scene,
    )
    return table[0].tool_cost


@pytest.mark.parametrize(
    ("weight", "known"),
    [(0.199999, False), (0.2, True), (0.200001, True)],
)
def test_runtime_support_uses_original_scene_mass(weight: float, known: bool) -> None:
    cost = _cost(_kb(_entry("paper", 60.0)), _scene("paper", weight))

    assert (cost.expected_runtime_minutes is not None) is known
    assert cost.runtime_evidence.support_mass == pytest.approx(weight)
    assert cost.runtime_evidence.support_threshold == 0.2


def test_same_source_scene_weight_roundoff_is_clamped_before_candidate_validation() -> None:
    weights = [0.197, 0.687, 0.116]
    raw_total = 0.0
    for weight in weights:
        raw_total += weight
    assert raw_total == 1.0000000000000002
    scene = ScenePool(
        neighbors=[
            SceneNeighbor(
                slice_id=f"paper-{index}",
                benchmark_family="paper",
                paper_id="paper",
                weight=weight,
                distance=0.0,
            )
            for index, weight in enumerate(weights)
        ]
    )

    cost = _cost(_kb(_entry("paper", 60.0)), scene)

    assert cost.runtime_evidence.candidates[0].scene_weight == 1.0
    assert cost.runtime_evidence.support_mass == 1.0


def test_materially_invalid_same_source_scene_mass_is_not_clamped() -> None:
    scene = ScenePool(
        neighbors=[
            SceneNeighbor(
                slice_id=f"paper-{index}",
                benchmark_family="paper",
                paper_id="paper",
                weight=weight,
                distance=0.0,
            )
            for index, weight in enumerate([0.6, 0.401])
        ]
    )

    with pytest.raises(ValueError):
        _cost(_kb(_entry("paper", 60.0)), scene)


def test_compiler_mismatch_and_unlinked_global_row_remain_unknown() -> None:
    mismatch = _cost(
        _kb(_entry("paper", 60.0, solc=["0.4.x"])),
        _scene("paper", 1.0),
    )
    unrelated = _cost(
        _kb(_entry("historical", 600.0)),
        _scene("different-paper", 1.0),
    )

    assert mismatch.expected_runtime_minutes is None
    assert mismatch.runtime_evidence.status == "NO_COMPATIBLE_RUNTIME_EVIDENCE"
    assert mismatch.runtime_evidence.candidates[0].compiler_match is False
    assert unrelated.expected_runtime_minutes is None
    assert unrelated.runtime_evidence.support_mass == 0.0


def test_non_contiguous_compiler_buckets_do_not_form_an_implicit_range() -> None:
    cost = _cost(
        _kb(_entry("paper", 60.0, solc=["0.4.x", "0.6.x"])),
        _scene("paper", 1.0),
        target_version="0.5.17",
    )

    assert cost.expected_runtime_minutes is None
    assert cost.runtime_evidence.candidates[0].compiler_match is False


def test_loc_match_and_failure_metadata_survive_candidate_provenance() -> None:
    metadata = {
        "sample_count": 100,
        "success_count": 80,
        "timeout_count": 5,
        "compilation_failure_count": 10,
        "failure_count": 20,
    }
    cost = _cost(
        _kb(_entry("paper", 120.0, loc_count=4, metadata=metadata)),
        _scene("paper", 1.0),
    )

    candidate = cost.runtime_provenance.candidates[0]
    assert cost.expected_runtime_minutes == 2.0
    assert cost.runtime_provenance.target_compiler_bucket == "0.8.x"
    assert cost.runtime_provenance.target_loc_bucket == "100-200"
    assert candidate.loc_match is True
    assert candidate.scene_weight == 1.0
    assert candidate.sample_count == 100
    assert candidate.success_count == 80
    assert candidate.timeout_count == 5
    assert candidate.compilation_failure_count == 10
    assert candidate.failure_count == 20


@pytest.mark.parametrize(
    ("basis", "expected_minutes"),
    [("per_contract", 1.0), ("per_kloc", 0.5), ("campaign_cap", None)],
)
def test_runtime_basis_is_typed_and_campaign_cap_is_unschedulable(
    basis: str,
    expected_minutes: float | None,
) -> None:
    cost = _cost(
        _kb(_entry("paper", 60.0, basis=basis)),
        _scene("paper", 1.0),
        loc_total=500,
    )

    assert cost.expected_runtime_minutes == expected_minutes
    assert cost.runtime_evidence.candidates[0].runtime_basis == basis
    if basis == "campaign_cap":
        assert cost.runtime_provenance is None
        assert "CAMPAIGN_CAP_NOT_SCHEDULABLE" in cost.runtime_evidence.candidates[0].limitations


def test_runtime_provenance_and_limitations_reach_dace_and_cego() -> None:
    cost = _cost(
        _kb(
            _entry(
                "paper",
                120.0,
                metadata={"success_count": 8, "timeout_count": 2},
            )
        ),
        _scene("paper", 1.0),
    )
    context = stage2_context()
    context.stage1.tool_table[0].tool_cost = cost
    matrix = build_action_evidence_matrix(context, budget())

    card = next(card for card in _runtime_cards(context) if card.tool == "a")
    assert card.category is None
    assert card.scope["runtime_candidates"][0]["success_count"] == 8
    assert card.scope["runtime_candidates"][0]["timeout_count"] == 2

    payload = json.loads(
        _prompt_payload(
            context,
            matrix,
            None,
            w_recall=0.5,
            w_precision=0.5,
        )
    )
    runtime = payload["tool_runtime_evidence"]
    assert set(runtime) == {"a", "b", "c"}
    assert runtime["a"]["expected_runtime_minutes"] == 2.0
    assert runtime["a"]["provenance"]["support_mass"] == 1.0
    assert runtime["a"]["evidence_quality"]["candidates"][0]["timeout_count"] == 2


def test_packaged_paper_runtime_rows_keep_their_own_sources_and_basis() -> None:
    root = Path(__file__).resolve().parents[1]
    kb = load_performance_db(root / "toolcards" / "performance_db.json")
    expected = {
        "gptscan": ("GPTScan", 14.39, "per_kloc"),
        "honeybadger": ("HoneyBadger", 142.0, "per_contract"),
        "sailfish": ("SAILFISH", 30.79, "per_contract"),
        "VulHunter": ("VulHunter", 4.4, "per_contract"),
        "smartian": ("SMARTIAN", 3600.0, "campaign_cap"),
    }

    entries = {entry.source_id: entry for entry in kb.entries}
    for source_id, (tool, seconds, basis) in expected.items():
        entry = entries[source_id]
        observation = next(
            item for item in entry.tool_performance_data if item.tool_name == tool
        )
        assert observation.metrics.resolved_time_sec == seconds
        assert observation.metrics.runtime_unit == "seconds"
        assert observation.metrics.runtime_basis == basis
        assert entry.source_id != "smartbugsdb"

    mando_rows = [
        observation
        for entry in kb.entries
        for observation in entry.tool_performance_data
        if observation.tool_name.lower() == "mando-hgt"
    ]
    assert mando_rows
    assert all(row.metrics.resolved_time_sec is None for row in mando_rows)


def test_packaged_paper_rows_without_compiler_profile_stay_unschedulable() -> None:
    root = Path(__file__).resolve().parents[1]
    kb = load_performance_db(root / "toolcards" / "performance_db.json")
    cards = load_toolcards(root / "toolcards")
    selected = [
        card
        for card in cards
        if card.tool_id in {"gptscan", "honeybadger", "sailfish", "vulhunter", "smartian"}
    ]
    scene = ScenePool(
        neighbors=[
            SceneNeighbor(
                slice_id=source_id,
                benchmark_family=source_id,
                paper_id=source_id,
                weight=0.2,
                distance=0.0,
            )
            for source_id in ("gptscan", "honeybadger", "sailfish", "VulHunter", "smartian")
        ]
    )
    table = build_tool_table(
        selected,
        ContractFeatures(
            source_kind="sol",
            primary_solidity_version="0.8.20",
            loc_total=1000,
            file_count=1,
        ),
        BudgetProfile(tool_slots=5, runtime_cap_minutes=60.0),
        kb,
        scene,
    )

    assert all(entry.tool_cost.expected_runtime_minutes is None for entry in table)
    smartian = next(entry for entry in table if entry.tool == "smartian")
    candidate = next(
        item
        for item in smartian.tool_cost.runtime_evidence.candidates
        if item.source_id == "smartian"
    )
    assert candidate.runtime_basis == "campaign_cap"
    assert "CAMPAIGN_CAP_NOT_SCHEDULABLE" in candidate.limitations
