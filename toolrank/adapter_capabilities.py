"""Executable input modes implemented by the bundled analyzer adapters.

This is deliberately narrower than some historical ToolCards.  The values
describe what the pinned SmartBugs configuration (plus LAKES' special
wrappers) can actually launch, so unsupported inputs fail before SmartBugs can
silently create zero tasks.
"""

from __future__ import annotations

from typing import Literal, Mapping

from toolrank.target_inputs import TargetInputKind


_SOL = frozenset({"sol"})
_SOL_RUNTIME = frozenset({"sol", "runtime"})
_SOL_BYTECODE_RUNTIME = frozenset({"sol", "bytecode", "runtime"})
SPECIAL_ADAPTER_TOOL_IDS = frozenset(
    {"gptscan", "sailfish", "securify2", "smartian"}
)

SharedArtifactComponent = Literal[
    "abi",
    "creation_bytecode",
    "runtime_bytecode",
]

# Only routes that replace a LAKES-owned source compilation belong here.
# Source-native analyzers remain source-only even when they compile internally.
SHARED_ARTIFACT_CONSUMERS: Mapping[
    str, frozenset[SharedArtifactComponent]
] = {
    "smartian": frozenset({"abi", "creation_bytecode"}),
    "vandal": frozenset({"runtime_bytecode"}),
}


ADAPTER_INPUT_CAPABILITIES: Mapping[str, frozenset[TargetInputKind]] = {
    # Pinned SmartBugs 89c16bb configurations.
    "ccc": _SOL,
    "confuzzius": _SOL,
    "conkas": _SOL_RUNTIME,
    "ethainter": frozenset({"runtime"}),
    "ethor": frozenset({"runtime"}),
    "honeybadger": _SOL_RUNTIME,
    "madmax": frozenset({"runtime"}),
    "maian": _SOL_BYTECODE_RUNTIME,
    "mando": _SOL,
    "mando-hgt": _SOL,
    "manticore": _SOL,
    "mythril": _SOL_BYTECODE_RUNTIME,
    "osiris": _SOL_RUNTIME,
    "oyente": _SOL_RUNTIME,
    "oyente+": _SOL_RUNTIME,
    "pakala": frozenset({"runtime"}),
    "securify": _SOL_RUNTIME,
    "semgrep": _SOL,
    "sfuzz": _SOL,
    "slither": _SOL,
    "smartcheck": _SOL,
    "solhint": _SOL,
    "teether": frozenset({"runtime"}),
    "vulhunter": frozenset({"sol", "bytecode"}),
    # Vandal is runtime-only in SmartBugs; LAKES also accepts source by
    # compiling it to runtime bytecode before dispatch.
    "vandal": frozenset({"sol", "runtime"}),
    # Source-only special wrappers bundled by LAKES.
    "gptscan": _SOL,
    "sailfish": _SOL,
    "securify2": _SOL,
    "smartian": _SOL,
}


def adapter_input_capabilities(
    tool_id: str,
) -> frozenset[TargetInputKind] | None:
    """Return bundled adapter capabilities, or ``None`` for an extension tool."""

    return ADAPTER_INPUT_CAPABILITIES.get(tool_id.strip().lower())


def adapter_supports_input(tool_id: str, input_kind: str) -> bool:
    """Return whether the current executable adapter implements this mode."""

    return input_kind in (adapter_input_capabilities(tool_id) or ())


def shared_artifact_components(
    tool_id: str,
    input_kind: str,
) -> frozenset[SharedArtifactComponent]:
    """Return components genuinely consumed by one registered source route."""

    if input_kind != "sol":
        return frozenset()
    return SHARED_ARTIFACT_CONSUMERS.get(tool_id.strip().lower(), frozenset())
