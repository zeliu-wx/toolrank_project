from __future__ import annotations

from toolrank.action_contract import action_id_for


def test_action_ids_have_one_owner() -> None:
    assert action_id_for("RUN_PRIMARY") == "run_primary"
    assert action_id_for("PLAN_COMPOSITION") == "plan_composition"
