"""Feasibility gates for the SCREC tool dispatch pipeline."""

from __future__ import annotations

from toolrank.adapter_capabilities import adapter_input_capabilities
from toolrank.schemas import ContractFeatures, FeasibilityResult, ToolCard, TriState
from toolrank.schemas_v2 import BudgetProfile
from toolrank.solc_range import solidity_constraints_overlap, version_in_range


def _required_inputs(features: ContractFeatures) -> list[str]:
    if features.present_input_kinds:
        return list(dict.fromkeys(features.present_input_kinds))
    if features.source_kind == "sol":
        return ["sol"]
    if features.source_kind == "bytecode":
        return ["bytecode"]
    if features.source_kind == "runtime":
        return ["runtime"]
    return []


def check_feasibility(
    card: ToolCard,
    features: ContractFeatures,
    budget: BudgetProfile,
) -> FeasibilityResult:
    reasons: list[str] = []

    if features.source_kind == "unknown" and features.target_path:
        reasons.append("target has no supported input files")

    required_inputs = _required_inputs(features)
    if features.source_kind == "mixed" and not required_inputs:
        reasons.append("mixed target does not identify its present input kinds")
    adapter_capabilities = adapter_input_capabilities(card.tool_id)
    if adapter_capabilities is None and features.target_path:
        reasons.append("no executable adapter registered")
    for input_type in required_inputs:
        if not getattr(card.d7_input_support, input_type, False):
            reasons.append(f"missing required input support: {input_type}")
        elif adapter_capabilities is not None and input_type not in adapter_capabilities:
            reasons.append(f"adapter does not implement input support: {input_type}")

    if features.solidity_version_constraints:
        if not solidity_constraints_overlap(
            features.solidity_version_constraints,
            card.d2_solidity_versions,
        ):
            reasons.append("target solidity constraints do not overlap tool support")
    elif (
        features.primary_solidity_version
        and not version_in_range(features.primary_solidity_version, card.d2_solidity_versions)
    ):
        reasons.append(f"target solidity version unsupported: {features.primary_solidity_version}")

    if features.is_multifile and card.d3_multifile_support == TriState.no:
        reasons.append("target is multifile but tool lacks multifile support")

    return FeasibilityResult(feasible=not reasons, reasons=reasons)
