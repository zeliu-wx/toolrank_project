"""Canonical Solidity AST metrics for contract profiles ``phi=(solc, loc, c)``.

The five complexity dimensions are derived from the compact JSON AST emitted
by a pragma-compatible ``solc`` compiler.  LOC remains a source-level metric.
The same implementation is shared by the offline benchmark-profile builder and
runtime target analysis.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

import solcx
from semantic_version import SimpleSpec, Version as SemanticVersion


NUM_DIMS = ["loc", "avg_cyc", "max_cyc", "sum_cyc", "max_nest", "coupling"]

_PRAGMA_RE = re.compile(r"pragma\s+solidity\s+([^;]+);", re.IGNORECASE)
_VER_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")
_COMPARATOR_RE = re.compile(r"(?:>=|<=|>|<|=|\^|~)?\d+\.\d+\.\d+")
_CONTROL_NODES = {"IfStatement", "ForStatement", "WhileStatement", "DoWhileStatement"}
_LOGICAL_OPERATORS = {"&&", "||"}


class AstExtractionError(RuntimeError):
    """Raised when no installed Solidity compiler can produce a usable AST."""


def strip_noncode(src: str) -> str:
    """Drop comments and string/char literal contents, preserving newlines."""
    out = []
    i, n, state = 0, len(src), "code"
    while i < n:
        ch = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if state == "code":
            if ch == "/" and nxt == "/":
                state, i = "line", i + 2
            elif ch == "/" and nxt == "*":
                state, i = "block", i + 2
            elif ch == '"':
                state, i = "dq", i + 1
            elif ch == "'":
                state, i = "sq", i + 1
            else:
                out.append(ch)
                i += 1
        elif state == "line":
            if ch == "\n":
                state = "code"
                out.append("\n")
            i += 1
        elif state == "block":
            if ch == "*" and nxt == "/":
                state, i = "code", i + 2
            else:
                if ch == "\n":
                    out.append("\n")
                i += 1
        elif state == "dq":
            i += 2 if ch == "\\" else 1
            if ch == '"':
                state = "code"
        elif state == "sq":
            i += 2 if ch == "\\" else 1
            if ch == "'":
                state = "code"
    return "".join(out)


def solc_floors(text: str) -> list[tuple[int, int]]:
    """Return major/minor lower bounds while ignoring upper-bound clauses."""
    floors = []
    for match in _PRAGMA_RE.finditer(text):
        spec = re.sub(r"<=?\s*\d+\.\d+(?:\.\d+)?", " ", match.group(1))
        for version_match in _VER_RE.finditer(spec):
            floors.append((int(version_match.group(1)), int(version_match.group(2))))
    return floors


def solc_bucket(floors: list[tuple[int, int]]) -> str:
    if not floors:
        return "unknown"
    major, minor = max(floors)
    return f"{major}.{minor}.x"


def eff_loc(stripped: str) -> int:
    return sum(1 for line in stripped.splitlines() if line.strip())


def _child_nodes(node: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    for value in node.values():
        if isinstance(value, dict):
            if "nodeType" in value:
                yield value
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and "nodeType" in item:
                    yield item


def _walk(node: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    yield dict(node)
    for child in _child_nodes(node):
        yield from _walk(child)


def _function_complexity(function: Mapping[str, Any]) -> tuple[int, int]:
    body = function.get("body")
    if not isinstance(body, dict):
        return 0, 0

    complexity = 1
    max_nesting = 0

    def visit(node: Mapping[str, Any], nesting: int) -> None:
        nonlocal complexity, max_nesting
        node_type = node.get("nodeType")
        child_nesting = nesting
        if node_type in _CONTROL_NODES:
            complexity += 1
            child_nesting += 1
            max_nesting = max(max_nesting, child_nesting)
        elif node_type == "BinaryOperation" and node.get("operator") in _LOGICAL_OPERATORS:
            complexity += 1
        elif node_type == "Conditional":
            complexity += 1

        for child in _child_nodes(node):
            visit(child, child_nesting)

    visit(body, 0)
    return complexity, max_nesting


def _collect_contract_references(
    node: Mapping[str, Any],
    contract_ids: set[int],
    references: set[int],
    current_contract: int | None = None,
) -> None:
    node_type = node.get("nodeType")
    if node_type == "ContractDefinition" and isinstance(node.get("id"), int):
        current_contract = node["id"]
    elif node_type in {"UserDefinedTypeName", "IdentifierPath"}:
        referenced = node.get("referencedDeclaration")
        if isinstance(referenced, int) and referenced in contract_ids and referenced != current_contract:
            references.add(referenced)

    for child in _child_nodes(node):
        _collect_contract_references(child, contract_ids, references, current_contract)


def _metrics_from_asts(asts: Iterable[Mapping[str, Any]]) -> dict[str, float | int]:
    ast_list = list(asts)
    contract_ids = {
        node["id"]
        for ast in ast_list
        for node in _walk(ast)
        if node.get("nodeType") == "ContractDefinition" and isinstance(node.get("id"), int)
    }

    cyclomatics: list[int] = []
    max_nesting = 0
    references: set[int] = set()
    for ast in ast_list:
        for node in _walk(ast):
            if node.get("nodeType") != "FunctionDefinition":
                continue
            complexity, nesting = _function_complexity(node)
            if complexity > 0:
                cyclomatics.append(complexity)
                max_nesting = max(max_nesting, nesting)
        _collect_contract_references(ast, contract_ids, references)

    return {
        "avg_cyc": round(sum(cyclomatics) / len(cyclomatics), 3) if cyclomatics else 0.0,
        "max_cyc": max(cyclomatics) if cyclomatics else 0,
        "sum_cyc": sum(cyclomatics),
        "max_nest": max_nesting,
        "coupling": len(references),
        "n_func": len(cyclomatics),
    }


def _semantic_version(version) -> SemanticVersion:
    if isinstance(version, SemanticVersion):
        return version
    return SemanticVersion(str(version))


def _matches_pragma(version, pragma_spec: str) -> bool:
    candidate = _semantic_version(version)
    for comparator_set in pragma_spec.replace(" ", "").split("||"):
        comparators = _COMPARATOR_RE.findall(comparator_set)
        if comparators and SimpleSpec(",".join(comparators)).match(candidate):
            return True
    return False


def _ast_compiler_versions(sources: Mapping[str, str]) -> list:
    """Choose one modern compiler per compatible Solidity version bucket.

    Some exact legacy compiler binaries do not run on current macOS releases.
    Complexity extraction only needs a structurally compatible AST, so each
    candidate bucket is represented by its newest installed patch release.
    The original pragma remains authoritative everywhere outside this isolated
    AST compilation step.
    """
    installed = sorted(solcx.get_installed_solc_versions())
    if not installed:
        raise AstExtractionError("No solc versions are installed for AST extraction")

    pragma_specs = [
        match.group(1)
        for source in sources.values()
        for match in _PRAGMA_RE.finditer(source)
    ]
    if not pragma_specs:
        return [installed[-1]]

    compatible = [
        version
        for version in installed
        if all(_matches_pragma(version, spec) for spec in pragma_specs)
    ]
    if not compatible:
        joined = "; ".join(pragma_specs)
        raise AstExtractionError(f"No installed Solidity version bucket satisfies: {joined}")

    compatible_buckets = {(version.major, version.minor) for version in compatible}
    newest_by_bucket = {
        bucket: max(
            version
            for version in installed
            if (version.major, version.minor) == bucket
        )
        for bucket in compatible_buckets
    }
    return [newest_by_bucket[bucket] for bucket in sorted(newest_by_bucket)]


def _sources_for_ast(sources: Mapping[str, str], version) -> dict[str, str]:
    pragma = f"pragma solidity {version};"
    return {
        name: _PRAGMA_RE.sub(pragma, text)
        for name, text in sources.items()
    }


def _compile_asts(sources: Mapping[str, str]) -> list[dict[str, Any]]:
    failures: list[str] = []
    for version in _ast_compiler_versions(sources):
        ast_sources = _sources_for_ast(sources, version)
        input_data = {
            "language": "Solidity",
            "sources": {name: {"content": text} for name, text in ast_sources.items()},
            "settings": {"outputSelection": {"*": {"": ["ast"]}}},
        }
        try:
            output = solcx.compile_standard(input_data, solc_version=version)
        except Exception as exc:  # solcx exception types vary across releases
            failures.append(f"solc {version}: {str(exc).splitlines()[0]}")
            continue
        asts = [
            source_output["ast"]
            for name, source_output in output.get("sources", {}).items()
            if name in sources and isinstance(source_output.get("ast"), dict)
        ]
        if len(asts) == len(sources):
            return asts
        failures.append(f"solc {version}: AST output missing for one or more sources")

    detail = failures[-1] if failures else "unknown compiler failure"
    raise AstExtractionError(f"Unable to build Solidity AST ({detail})")


def profile_sources(sources: Mapping[str, str]) -> dict[str, float | int | str]:
    """Build one profile from named Solidity sources using compiler-generated ASTs."""
    if not sources:
        raise AstExtractionError("At least one Solidity source is required")
    stripped_sources = [strip_noncode(source) for source in sources.values()]
    floors = [floor for source in stripped_sources for floor in solc_floors(source)]
    metrics = _metrics_from_asts(_compile_asts(sources))
    return {
        "solc": solc_bucket(floors),
        "loc": sum(eff_loc(source) for source in stripped_sources),
        **metrics,
    }


def profile_text(text: str) -> dict[str, float | int | str]:
    """Compatibility wrapper for a single, self-contained Solidity file."""
    return profile_sources({"Contract.sol": text})


def profile_target(texts: list[str]) -> dict[str, float | int | str]:
    """Compatibility wrapper for a target represented by multiple source texts."""
    return profile_sources({f"source_{index}.sol": text for index, text in enumerate(texts)})
