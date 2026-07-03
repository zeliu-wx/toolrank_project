"""Certify the Step 1 primary tool, or fall back to a candidate set.

Candidates are taken in nominal-score order (preference-weighted, scene
normalized); the first one that is feasible and has sufficient scene evidence
becomes the certified primary.
"""

from __future__ import annotations

from toolrank.schemas_v2 import (
    CertificationVerdict,
    NominalToolScore,
    RecallCoverageMatrix,
    ScorePanel,
    ToolTableEntry,
)


# scene_scoring._evidence_level grades by the recall 95% CI half-width on the
# similarity-effective sample: local_strong if half-width <= epsilon_r, local_weak if
# the CI is too wide, unsupported if there are no count-bearing observations. So
# sufficient evidence == local_strong.
_SUFFICIENT_EVIDENCE = {"local_strong"}


def _feasible_tools(tool_table: list[ToolTableEntry]) -> set[str]:
    return {entry.tool for entry in tool_table if entry.feasible}


def _ranked_nominal_scores(score_panel: ScorePanel) -> list[NominalToolScore]:
    return sorted(score_panel.nominal_scores, key=lambda item: (item.rank, -item.S_scene, item.tool))


def certify(
    score_panel: ScorePanel,
    rcov: RecallCoverageMatrix,
    tool_table: list[ToolTableEntry],
) -> CertificationVerdict:
    if not score_panel.nominal_scores:
        return CertificationVerdict(status="no_feasible_tool", reason_codes=["NO_NOMINAL_SCORES"])

    feasible = _feasible_tools(tool_table)
    first_feasible: NominalToolScore | None = None

    for score in _ranked_nominal_scores(score_panel):
        if score.tool not in feasible:
            continue
        if first_feasible is None:
            first_feasible = score
        if score.evidence_level in _SUFFICIENT_EVIDENCE:
            return CertificationVerdict(
                status="certified_primary",
                certified_primary=score.tool,
                reason_codes=["FEASIBLE_TOOL", "SUFFICIENT_EVIDENCE"],
            )

    if first_feasible is None:
        return CertificationVerdict(status="no_feasible_tool", reason_codes=["NO_FEASIBLE_TOOL"])

    reason_codes = ["FEASIBLE_TOOL"]
    if first_feasible.evidence_level not in _SUFFICIENT_EVIDENCE:
        reason_codes.append("INSUFFICIENT_EVIDENCE")
    return CertificationVerdict(
        status="candidate_set",
        candidate_set=[first_feasible.tool],
        reason_codes=reason_codes,
    )
