from __future__ import annotations

from toolrank.dace_rag import build_action_evidence_matrix
from toolrank.engine import _primary_runtime_outcome
from toolrank.schemas_v2 import (
    BudgetProfile,
    PrimarySelection,
    ScorePanel,
    Stage1EvidencePacket,
    Stage1Status,
    Stage2Status,
)
from toolrank.schemas import ExecutionSchedule
from tests.stage1_fixtures import scene_pool, tool_entry
from tests.stage2_fixtures import budget, stage2_context


def stage1_with_runtime(runtime: float | None) -> Stage1EvidencePacket:
    return Stage1EvidencePacket(
        tool_table=[tool_entry("a", runtime=runtime)],
        scene_pool=scene_pool(("d1", 1.0, 1.0)),
        score_panel=ScorePanel(),
        primary_selection=PrimarySelection(
            status=Stage1Status.PRIMARY_SELECTED,
            primary_tool="a",
            eligible_tools=["a"],
        ),
    )


def test_unknown_primary_runtime_is_terminal_without_changing_primary() -> None:
    packet = stage1_with_runtime(None)
    outcome = _primary_runtime_outcome(packet, budget())
    assert outcome.status == Stage2Status.NO_EXECUTABLE_PLAN
    assert outcome.reason_codes == ["PRIMARY_RUNTIME_UNKNOWN"]
    assert packet.primary_selection.primary_tool == "a"


def test_over_budget_primary_is_terminal_without_substitution() -> None:
    packet = stage1_with_runtime(11.0)
    outcome = _primary_runtime_outcome(packet, budget(runtime=10.0))
    assert outcome.status == Stage2Status.NO_EXECUTABLE_PLAN
    assert outcome.reason_codes == ["PRIMARY_EXCEEDS_STAGE2_BUDGET"]
    assert packet.primary_selection.primary_tool == "a"


def test_over_budget_complement_is_ineligible() -> None:
    context = stage2_context(b_runtime=11.0)
    matrix = build_action_evidence_matrix(context, budget(runtime=10.0))
    assert matrix.ownership_panel["reentrancy"].assignment_status == "PRIMARY_ONLY_NO_COMPLEMENT"
    assert matrix.ownership_panel["reentrancy"].eligible_candidates == []


def test_explicit_short_timeout_is_terminal_without_claiming_runtime_unknown() -> None:
    packet = stage1_with_runtime(2.0)
    limit = BudgetProfile(
        tool_slots=1,
        runtime_cap_minutes=10.0,
        execution_schedule=ExecutionSchedule(
            tool_timeout_seconds=60.0,
            timeout_source="explicit",
        ),
    )

    outcome = _primary_runtime_outcome(packet, limit)

    assert outcome.status == Stage2Status.NO_EXECUTABLE_PLAN
    assert outcome.reason_codes == ["PRIMARY_EXCEEDS_EXPLICIT_TOOL_TIMEOUT"]
