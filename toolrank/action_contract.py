"""Single source of truth for executable Stage 2 action identifiers."""

from __future__ import annotations

from toolrank.schemas_v2 import ActionType


_ACTION_IDS: dict[ActionType, str] = {
    "RUN_PRIMARY": "run_primary",
    "PLAN_COMPOSITION": "plan_composition",
}


def action_id_for(action_type: ActionType) -> str:
    return _ACTION_IDS[action_type]
