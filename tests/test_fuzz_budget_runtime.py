from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from toolrank import runner
from toolrank.cego import _prompt_payload, assemble_decision
from toolrank.checker import check_decision
from toolrank.composition import composition_from_certificate
from toolrank.dace_rag import _runtime_cards, build_action_evidence_matrix
from toolrank.engine import _primary_runtime_outcome
from toolrank.evidence_packet import build_tool_table
from toolrank.execution import build_execution_plan
from toolrank.plan_runtime import (
    plan_constraint_reasons,
    planning_runtime_minutes,
    plan_runtime_minutes,
)
from toolrank.process_deadline import DeadlineProcessResult
from toolrank.retrieval import load_toolcards
from toolrank.runner import prepare_smartbugs_invocation
from toolrank.scene_scoring import select_primary
from toolrank.schemas import (
    ContractFeatures,
    CompositionPlan,
    D1Metric,
    DatasetProfile,
    ExecutionSchedule,
    PerformanceEntry,
    PerformanceKnowledgeBase,
    ToolCard,
    ToolPerformanceObservation,
)
from toolrank.schemas_v2 import (
    BudgetProfile,
    FuzzCampaignBudget,
    NominalToolScore,
    PrimarySelection,
    RuntimeEvidenceAssessment,
    SceneNeighbor,
    ScenePool,
    ScorePanel,
    Stage1EvidencePacket,
    Stage1Status,
    Stage2Status,
    ToolCostEntry,
    ToolTableEntry,
)
from tests.stage1_fixtures import tool_entry
from tests.stage2_fixtures import stage2_context


ROOT = Path(__file__).resolve().parents[1]


def _card(
    tool_id: str,
    *,
    mode: str = "fuzz",
    tool_name: str | None = None,
) -> ToolCard:
    return ToolCard(
        tool_id=tool_id,
        tool_name=tool_name or tool_id,
        d7_input_support={"sol": True},
        d8_mode=mode,
        d2_solidity_versions="0.4.0-0.8.99",
        d3_multifile_support="yes",
    )


def _runtime_entry(*, basis: str = "per_contract") -> PerformanceEntry:
    return PerformanceEntry(
        source_id="paper",
        dataset_profile=DatasetProfile(
            dataset_name="paper-dataset",
            solc=["0.8.x"],
        ),
        tool_performance_data=[
            ToolPerformanceObservation(
                tool_name="Future Renamed Fuzzer",
                metrics=D1Metric(
                    execution_time_avg=120.0,
                    runtime_basis=basis,
                ),
            )
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


def _scene() -> ScenePool:
    return ScenePool(
        neighbors=[
            SceneNeighbor(
                slice_id="paper-slice",
                benchmark_family="paper",
                paper_id="paper",
                weight=1.0,
                distance=0.0,
            )
        ]
    )


def _budget(
    *,
    runtime_minutes: float = 10.0,
    timeout_seconds: float | None = None,
    contract_count: int = 1,
) -> BudgetProfile:
    explicit = timeout_seconds is not None
    return BudgetProfile(
        tool_slots=5,
        runtime_cap_minutes=runtime_minutes,
        execution_schedule=ExecutionSchedule(
            contract_count=contract_count,
            execution_jobs=0,
            tool_timeout_seconds=(
                timeout_seconds if explicit else runtime_minutes * 60.0
            ),
            timeout_source="explicit" if explicit else "budget_default",
        ),
    )


def _build(
    cards: list[ToolCard],
    *,
    budget: BudgetProfile | None = None,
    kb: PerformanceKnowledgeBase | None = None,
    scene: ScenePool | None = None,
) -> list[ToolTableEntry]:
    return build_tool_table(
        cards,
        ContractFeatures(
            source_kind="sol",
            present_input_kinds=["sol"],
            primary_solidity_version="0.8.20",
            gower_solc_bucket="0.8.x",
            file_count=1,
            execution_input_count=1,
        ),
        budget or _budget(),
        kb or _kb(),
        scene or ScenePool(),
    )


def _fuzz_tool_entry(
    tool: str,
    seconds: float,
    *,
    timeout_source: str = "explicit",
) -> ToolTableEntry:
    return ToolTableEntry(
        tool=tool,
        family="fuzz",
        feasible=True,
        tool_cost=ToolCostEntry(
            fuzz_campaign_budget=FuzzCampaignBudget(
                allocated_runtime_seconds=seconds,
                timeout_source=timeout_source,
            )
        ),
    )


def _fuzz_stage1(
    tool: str,
    seconds: float,
    *,
    timeout_source: str = "explicit",
) -> Stage1EvidencePacket:
    return Stage1EvidencePacket(
        tool_table=[
            _fuzz_tool_entry(tool, seconds, timeout_source=timeout_source)
        ],
        scene_pool=_scene(),
        score_panel=ScorePanel(),
        primary_selection=PrimarySelection(
            status=Stage1Status.PRIMARY_SELECTED,
            primary_tool=tool,
            eligible_tools=[tool],
        ),
    )


def test_fuzz_campaign_budget_is_typed_and_not_historical_provenance() -> None:
    campaign = FuzzCampaignBudget(
        allocated_runtime_seconds=90.0,
        timeout_source="explicit",
    )

    assert campaign.method == "user_budget_fuzz_campaign"
    assert campaign.runtime_semantics == "campaign_allocation_not_completion_estimate"
    assert campaign.allocated_runtime_seconds == 90.0

    historical = tool_entry("static", runtime=2.0).tool_cost
    with pytest.raises(ValidationError):
        ToolCostEntry(
            expected_runtime_minutes=2.0,
            runtime_provenance=historical.runtime_provenance,
            fuzz_campaign_budget=campaign,
        )
    with pytest.raises(ValidationError, match="requires family=fuzz"):
        ToolTableEntry(
            tool="static",
            family="static_source",
            feasible=True,
            tool_cost=ToolCostEntry(fuzz_campaign_budget=campaign),
        )
    with pytest.raises(ValidationError, match="historical completion runtime"):
        ToolTableEntry(
            tool="fuzz",
            family="fuzz",
            feasible=True,
            tool_cost=historical,
        )


def test_all_packaged_fuzz_modes_receive_the_full_default_allocation() -> None:
    cards = load_toolcards(ROOT / "toolcards")
    table = {entry.tool: entry for entry in _build(cards, budget=_budget(runtime_minutes=7.5))}
    fuzz_ids = {card.tool_id for card in cards if card.d8_mode.value == "fuzz"}

    assert fuzz_ids == {"confuzzius", "sfuzz", "smartian"}
    for tool in fuzz_ids:
        cost = table[tool].tool_cost
        assert cost.expected_runtime_minutes is None
        assert cost.runtime_provenance is None
        assert cost.fuzz_campaign_budget is not None
        assert cost.fuzz_campaign_budget.allocated_runtime_seconds == 450.0
        assert cost.fuzz_campaign_budget.timeout_source == "budget_default"

    assert all(
        table[card.tool_id].tool_cost.fuzz_campaign_budget is None
        for card in cards
        if card.d8_mode.value != "fuzz"
    )

    unresolved = _build(
        [_card("future-renamed")],
        budget=BudgetProfile(tool_slots=1, runtime_cap_minutes=0.0),
    )[0]
    assert unresolved.tool_cost.fuzz_campaign_budget is None
    assert planning_runtime_minutes(unresolved) is None

    inconsistent_default = BudgetProfile(
        tool_slots=1,
        runtime_cap_minutes=10.0,
        execution_schedule=ExecutionSchedule(
            tool_timeout_seconds=60.0,
            timeout_source="budget_default",
        ),
    )
    assert (
        _build([_card("future-renamed")], budget=inconsistent_default)[0]
        .tool_cost.fuzz_campaign_budget
        is None
    )


def test_fuzz_policy_uses_detection_mode_not_current_tool_names() -> None:
    cards = [
        _card("future-renamed", tool_name="Future Renamed Fuzzer"),
        _card("smartian", mode="static", tool_name="Misleading Static Name"),
    ]
    table = {entry.tool: entry for entry in _build(cards)}

    assert table["future-renamed"].tool_cost.fuzz_campaign_budget is not None
    assert table["smartian"].tool_cost.fuzz_campaign_budget is None


@pytest.mark.parametrize(
    ("basis", "expected_status"),
    [
        (None, "NO_RUNTIME_ROWS"),
        ("per_contract", "QUALIFIED"),
        ("campaign_cap", "NO_COMPATIBLE_RUNTIME_EVIDENCE"),
    ],
)
def test_fuzz_history_stays_descriptive_for_missing_qualified_and_cap_rows(
    basis: str | None,
    expected_status: str,
) -> None:
    card = _card("future-renamed", tool_name="Future Renamed Fuzzer")
    entries = [] if basis is None else [_runtime_entry(basis=basis)]
    cost = _build(
        [card],
        budget=_budget(timeout_seconds=75.0),
        kb=_kb(*entries),
        scene=_scene() if entries else ScenePool(),
    )[0].tool_cost

    assert cost.expected_runtime_minutes is None
    assert cost.runtime_provenance is None
    assert cost.runtime_evidence is not None
    assert cost.runtime_evidence.status == expected_status
    assert cost.fuzz_campaign_budget is not None
    assert cost.fuzz_campaign_budget.allocated_runtime_seconds == 75.0
    if basis is not None:
        assert cost.runtime_evidence.candidates[0].runtime_basis == basis
    if basis == "campaign_cap":
        assert cost.runtime_evidence.candidates[0].schedulable_runtime_seconds is None


def test_explicit_timeout_becomes_the_fuzz_campaign_duration() -> None:
    cost = _build(
        [_card("future-renamed")],
        budget=_budget(runtime_minutes=10.0, timeout_seconds=37.0),
    )[0].tool_cost

    assert cost.fuzz_campaign_budget is not None
    assert cost.fuzz_campaign_budget.allocated_runtime_seconds == 37.0
    assert cost.fuzz_campaign_budget.timeout_source == "explicit"

    zero_limit = BudgetProfile(
        tool_slots=1,
        runtime_cap_minutes=0.0,
        execution_schedule=ExecutionSchedule(
            tool_timeout_seconds=37.0,
            timeout_source="explicit",
        ),
    )
    zero_entry = _build([_card("future-renamed")], budget=zero_limit)[0]
    assert zero_entry.tool_cost.fuzz_campaign_budget is None
    zero_packet = _fuzz_stage1("future-renamed", 37.0).model_copy(
        update={"tool_table": [zero_entry]}
    )
    assert _primary_runtime_outcome(zero_packet, zero_limit).status == (
        Stage2Status.NO_EXECUTABLE_PLAN
    )

    long_limit = _budget(runtime_minutes=10.0, timeout_seconds=601.0)
    long_outcome = _primary_runtime_outcome(
        _fuzz_stage1("future-renamed", 601.0),
        long_limit,
    )
    assert long_outcome.status == Stage2Status.NO_EXECUTABLE_PLAN
    assert long_outcome.reason_codes == ["PRIMARY_EXCEEDS_STAGE2_BUDGET"]


def test_shared_projection_preserves_parallel_max_and_sequential_inputs() -> None:
    schedule = ExecutionSchedule(
        contract_count=3,
        execution_jobs=0,
        tool_timeout_seconds=300.0,
        timeout_source="budget_default",
    )
    table = [
        tool_entry("static", runtime=4.0),
        _fuzz_tool_entry("fuzz-a", 300.0, timeout_source="budget_default"),
        _fuzz_tool_entry("fuzz-b", 300.0, timeout_source="budget_default"),
    ]

    assert planning_runtime_minutes(table[0]) == 4.0
    assert planning_runtime_minutes(table[1]) == 5.0
    assert plan_runtime_minutes(["fuzz-a", "fuzz-b"], table, schedule) == 15.0
    assert plan_runtime_minutes(["static", "fuzz-a"], table, schedule) == 15.0

    source_mismatch = schedule.model_copy(update={"timeout_source": "explicit"})
    assert plan_runtime_minutes(["fuzz-a"], table, source_mismatch) is None
    assert plan_constraint_reasons(["fuzz-a"], table, source_mismatch) == [
        "FUZZ_CAMPAIGN_TIMEOUT_SOURCE_MISMATCH:fuzz-a"
    ]


def test_explicit_timeout_is_campaign_duration_but_static_constraint_is_unchanged() -> None:
    schedule = ExecutionSchedule(
        contract_count=1,
        execution_jobs=0,
        tool_timeout_seconds=60.0,
        timeout_source="explicit",
    )

    assert plan_runtime_minutes(
        ["fuzz"],
        [_fuzz_tool_entry("fuzz", 60.0)],
        schedule,
    ) == 1.0
    assert plan_runtime_minutes(
        ["static"],
        [tool_entry("static", runtime=2.0)],
        schedule,
    ) is None


@pytest.mark.parametrize(
    ("timeout_seconds", "contract_count", "expected_status", "expected_runtime"),
    [
        (None, 1, Stage2Status.PLAN_READY, 10.0),
        (90.0, 1, Stage2Status.PLAN_READY, 1.5),
        (None, 2, Stage2Status.NO_EXECUTABLE_PLAN, 20.0),
        (120.0, 2, Stage2Status.PLAN_READY, 4.0),
    ],
)
def test_fuzz_primary_uses_campaign_allocation_and_multi_input_budget(
    timeout_seconds: float | None,
    contract_count: int,
    expected_status: Stage2Status,
    expected_runtime: float,
) -> None:
    limit = _budget(
        runtime_minutes=10.0,
        timeout_seconds=timeout_seconds,
        contract_count=contract_count,
    )
    campaign_seconds = limit.execution_schedule.tool_timeout_seconds
    outcome = _primary_runtime_outcome(
        _fuzz_stage1(
            "future-renamed",
            campaign_seconds,
            timeout_source=limit.execution_schedule.timeout_source,
        ),
        limit,
    )

    assert outcome.status == expected_status
    assert outcome.estimated_plan_runtime_minutes == expected_runtime
    if expected_status == Stage2Status.NO_EXECUTABLE_PLAN:
        assert outcome.reason_codes == ["PRIMARY_EXCEEDS_STAGE2_BUDGET"]


def test_fuzz_complement_reaches_checker_certificate_and_composition() -> None:
    context = stage2_context(b_runtime=None)
    limit = _budget(runtime_minutes=10.0)
    context.stage1.tool_table[1] = _fuzz_tool_entry(
        "b",
        600.0,
        timeout_source="budget_default",
    )
    matrix = build_action_evidence_matrix(context, limit)

    assert [
        candidate.tool
        for candidate in matrix.ownership_panel["reentrancy"].eligible_candidates
    ] == ["b"]
    certificate = assemble_decision(
        {
            "complements": [
                {
                    "category": "reentrancy",
                    "tool": "b",
                    "evidence_refs": ["ev_rcov_b_reentrancy"],
                }
            ]
        },
        context,
        matrix,
        limit,
    )

    assert check_decision(certificate, context, matrix).status == "ACCEPT"
    assert certificate.budget.estimated_use.runtime_cap_minutes == 10.0
    composition = composition_from_certificate(certificate)
    assert composition.selected_tool_ids == ["a", "b"]
    assert composition.execution_schedule == limit.execution_schedule


def test_dace_and_cego_separate_history_from_campaign_allocation() -> None:
    context = stage2_context()
    limit = _budget(runtime_minutes=10.0, timeout_seconds=90.0)
    context.stage1.tool_table[0] = _fuzz_tool_entry("a", 90.0)
    context.stage1.tool_table[0].tool_cost.runtime_evidence = RuntimeEvidenceAssessment(
        status="NO_RUNTIME_ROWS",
        limitations=["NO_RUNTIME_ROWS"],
    )
    matrix = build_action_evidence_matrix(context, limit)

    runtime_cards = [card for card in _runtime_cards(context) if card.tool == "a"]
    historical = next(card for card in runtime_cards if card.evidence_id == "ev_runtime_a")
    campaign = next(
        card for card in runtime_cards if card.evidence_id == "ev_fuzz_campaign_a"
    )
    assert historical.value.value is None
    assert historical.source.source_type == "benchmark_metadata"
    assert historical.scope["historical_completion_runtime_minutes"] is None
    assert historical.scope["runtime_semantics"] == "historical_completion_estimate"
    assert campaign.value.value == 1.5
    assert campaign.source.source_type == "stage2_field"
    assert campaign.source.field_path == (
        "budget_profile.execution_schedule.tool_timeout_seconds"
    )
    assert campaign.scope["fuzz_campaign_budget"]["allocated_runtime_seconds"] == 90.0
    assert "ev_fuzz_campaign_a" in matrix.actions[0].evidence["FOR"][0].evidence_refs

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
    assert runtime["planning_runtime_minutes"] == 1.5
    assert runtime["planning_runtime_source"] == "user_budget_fuzz_campaign"
    assert runtime["planning_runtime_semantics"] == (
        "campaign_allocation_not_completion_estimate"
    )
    assert runtime["fuzz_campaign_budget"]["runtime_semantics"] == (
        "campaign_allocation_not_completion_estimate"
    )


def test_stage1_comparator_does_not_consume_fuzz_campaign_allocation() -> None:
    scores = ScorePanel(
        nominal_scores=[
            NominalToolScore(
                tool="fuzz",
                S_scene=1.0,
                rank=1,
                support_mass=1.0,
                preferred_metric_value=0.8,
            ),
            NominalToolScore(
                tool="static",
                S_scene=1.0,
                rank=2,
                support_mass=1.0,
                preferred_metric_value=0.8,
            ),
        ]
    )
    static = tool_entry("static", runtime=2.0)

    short = select_primary(
        _scene(),
        scores.model_copy(deep=True),
        [_fuzz_tool_entry("fuzz", 30.0), static],
    )
    long = select_primary(
        _scene(),
        scores.model_copy(deep=True),
        [_fuzz_tool_entry("fuzz", 600.0), static],
    )

    assert short.primary_tool == long.primary_tool == "static"


@pytest.mark.parametrize("tool", ["confuzzius", "sfuzz"])
def test_smartbugs_fuzz_wrappers_receive_the_resolved_outer_timeout(
    tool: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    contract = tmp_path / "Main.sol"
    contract.write_text("contract Main {}", encoding="utf-8")
    smartbugs = tmp_path / "smartbugs"
    smartbugs.mkdir()

    with prepare_smartbugs_invocation(
        tool,
        contract,
        tmp_path / "out",
        target_root=contract,
        smartbugs_dir=smartbugs,
        timeout=37.0,
        input_kind="sol",
    ) as invocation:
        assert invocation.command[invocation.command.index("--timeout") + 1] == "37"

    tiny_limit = _budget(runtime_minutes=1.0, timeout_seconds=0.25)
    entry = _build([_card(tool)], budget=tiny_limit)[0]
    assert entry.tool_cost.fuzz_campaign_budget is not None
    composition = CompositionPlan(
        selected_tool_ids=[tool],
        primary_tool_id=tool,
        estimated_plan_runtime_minutes=planning_runtime_minutes(entry) or 0.0,
        execution_schedule=tiny_limit.execution_schedule,
    )
    execution = build_execution_plan(
        contract,
        tmp_path / "results",
        composition,
        runner_script=tmp_path / "runner.py",
        runner_cwd=tmp_path,
    )
    assert execution.runner_command[
        execution.runner_command.index("--timeout") + 1
    ] == "0.25"
    parsed = runner.build_parser().parse_args(
        [str(contract), str(tmp_path / "parsed"), "--tool", tool, "--timeout", "0.25"]
    )
    assert parsed.timeout == 0.25

    captured: dict = {}

    def fake_deadline(_command, **kwargs):
        captured.update(kwargs)
        return DeadlineProcessResult(
            returncode=124,
            elapsed_seconds=0.25,
            timed_out=True,
        )

    monkeypatch.setattr(runner, "run_process_with_deadline", fake_deadline)
    rc = runner._run_adapter_with_deadline(
        tool,
        contract,
        tmp_path / "tiny-out",
        target_root=contract,
        smartbugs_dir=smartbugs,
        timeout=0.25,
        gptscan_timeout=7,
        openai_api_key="",
        openai_api_base="",
        mapping={},
        quarantine_root=tmp_path / ".quarantine",
    )
    request = json.loads(captured["input_text"])
    assert rc == 124
    assert captured["timeout_seconds"] == 0.25
    assert request["timeout"] == 1
