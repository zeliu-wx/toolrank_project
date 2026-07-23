"""Canonical Solidity AST metrics for contract profiles ``phi=(solc, loc, c)``.

The five complexity dimensions are derived from the compact JSON AST emitted
by the first successful canonical ``solc`` patch in a deterministic,
constraint-bounded bucket order. LOC remains a source-level metric. The same
implementation is shared by the offline benchmark-profile builder and runtime
target analysis.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

try:
    import solcx
except ImportError:  # Feature extraction degrades to source-level metrics.
    solcx = None

from toolrank.solc_range import (
    representative_solidity_version,
    version_satisfies_solidity_constraint,
)
from toolrank.source_project import mask_solidity_noncode_for_pragmas


NUM_DIMS = ["loc", "avg_cyc", "max_cyc", "sum_cyc", "max_nest", "coupling"]

PROFILE_ARTIFACT_SCHEMA = "contract_profiles_v2"
PROFILE_MANIFEST_SCHEMA = "contract_profile_manifest_v1"
CANONICAL_PROFILE_ENGINE = "solc_compact_ast_v3"
PROFILE_SAMPLE_UNIT = "solidity_file_with_safe_import_closure"
PROFILE_NORMALIZATIONS = ["blockscan_export_wrapper_v1"]
PROFILE_FAILURE_CLASSES = [
    "compilation_error",
    "pragma_constraint",
    "source_encoding",
    "source_io",
    "unsafe_import_closure",
    "unresolved_import",
]
CANONICAL_PROFILING_COMPILERS = {
    "0.4.x": "0.4.26",
    "0.5.x": "0.5.17",
    "0.6.x": "0.6.12",
    "0.7.x": "0.7.6",
    "0.8.x": "0.8.30",
}
CANONICAL_PROFILING_BUCKET_ORDER = tuple(CANONICAL_PROFILING_COMPILERS)
DEFAULT_PROFILING_COMPILER = CANONICAL_PROFILING_COMPILERS["0.8.x"]
NO_PRAGMA_PROFILING_BUCKET_ORDER = tuple(
    reversed(CANONICAL_PROFILING_BUCKET_ORDER)
)

_PRAGMA_RE = re.compile(r"pragma\s+solidity\s+([^;]+);", re.IGNORECASE)
_VER_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")
_CONTROL_NODES = {"IfStatement", "ForStatement", "WhileStatement", "DoWhileStatement"}
_LOGICAL_OPERATORS = {"&&", "||"}
_BLOCKSCAN_EXPORT_PREFIX = "Contract Source Code (Solidity)"
_BLOCKSCAN_EXPORT_SUFFIX = " Contract Security Audit No Contract Security Audit"


class AstExtractionError(RuntimeError):
    """Raised when no installed Solidity compiler can produce a usable AST."""


@dataclass(frozen=True)
class AstCompilation:
    """ASTs plus the canonical compiler identity that actually emitted them."""

    asts: tuple[dict[str, Any], ...]
    solc_bucket: str
    profiling_compiler: str


def strip_noncode(src: str) -> str:
    """Drop comments and string/char literal contents, preserving newlines."""
    return mask_solidity_noncode_for_pragmas(src)


def normalize_profile_source(src: str) -> str:
    """Mask a known Blockscan UI export banner while preserving positions.

    Some BNB corpus files prepend the copied explorer outline to otherwise
    valid source.  The exact banner is not Solidity and must not contribute to
    effective LOC or reach the profiling compiler.
    """
    if not src.startswith(_BLOCKSCAN_EXPORT_PREFIX):
        return src
    starts = [
        index
        for marker in ("/**", "// SPDX", "pragma solidity")
        if (index := src.find(marker, len(_BLOCKSCAN_EXPORT_PREFIX))) >= 0
    ]
    if not starts:
        return src
    start = min(starts)
    masked_prefix = "".join("\n" if char == "\n" else " " for char in src[:start])
    normalized = masked_prefix + src[start:]
    suffix_start = normalized.find(_BLOCKSCAN_EXPORT_SUFFIX, start)
    if suffix_start < 0:
        return normalized
    masked_suffix = "".join(
        "\n" if char == "\n" else " " for char in normalized[suffix_start:]
    )
    return normalized[:suffix_start] + masked_suffix


def _solc_bucket(version: str | None) -> str:
    if version is None:
        return "unknown"
    match = _VER_RE.fullmatch(version)
    if match is None:
        return "unknown"
    return f"{match.group(1)}.{match.group(2)}.x"


def eff_loc(stripped: str) -> int:
    return sum(1 for line in stripped.splitlines() if line.strip())


def _pragma_constraints(sources: Mapping[str, str]) -> list[str]:
    return [
        match.group(1).strip()
        for source in sources.values()
        for match in _PRAGMA_RE.finditer(strip_noncode(normalize_profile_source(source)))
    ]


def source_profile_facts(
    sources: Mapping[str, str],
) -> dict[str, int | str]:
    """Build compiler-bucket and effective-LOC facts without compiling ASTs."""
    if not sources:
        raise AstExtractionError("At least one Solidity source is required")

    stripped_sources = [
        strip_noncode(normalize_profile_source(source)) for source in sources.values()
    ]
    constraints = _pragma_constraints(sources)
    representative = representative_solidity_version(constraints)
    if constraints and representative is None:
        raise AstExtractionError(
            "Solidity pragma constraints have no supported intersection"
        )

    return {
        "solc": _solc_bucket(representative),
        "loc": sum(eff_loc(source) for source in stripped_sources),
    }


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


def profiling_compiler_for_bucket(bucket: str) -> str:
    """Return the fixed profiling compiler for a Gower compiler bucket."""
    if bucket == "unknown":
        return DEFAULT_PROFILING_COMPILER
    try:
        return CANONICAL_PROFILING_COMPILERS[bucket]
    except KeyError as exc:
        raise AstExtractionError(f"Unsupported Solidity profiling bucket: {bucket}") from exc


@lru_cache(maxsize=256)
def _candidate_buckets_for_constraints(
    constraints: tuple[str, ...],
) -> tuple[str, ...]:
    """Return deterministic canonical buckets intersecting every source pragma.

    Constrained sources try eligible buckets from oldest to newest, preserving
    the representative-version policy while allowing a broad pragma to use
    newer syntax it explicitly permits. Sources without a pragma try the
    documented modern default first and then older canonical buckets.
    """
    if not constraints:
        return NO_PRAGMA_PROFILING_BUCKET_ORDER

    candidates: list[str] = []
    for bucket in CANONICAL_PROFILING_BUCKET_ORDER:
        minor = int(bucket.split(".")[1])
        if any(
            all(
                version_satisfies_solidity_constraint(
                    f"0.{minor}.{patch}", constraint
                )
                for constraint in constraints
            )
            for patch in range(100)
        ):
            candidates.append(bucket)
    return tuple(candidates)


def _ast_compiler_versions(sources: Mapping[str, str]) -> list:
    """Return installed canonical candidates in deterministic profiling order.

    Original constraints only bound which major/minor buckets may be tried.
    Each attempt rewrites a private profiling copy to that bucket's fixed patch;
    feasibility and execution continue to use the untouched source constraints.
    """
    if solcx is None:
        raise AstExtractionError("py-solc-x is unavailable for AST extraction")
    installed = sorted(solcx.get_installed_solc_versions())
    if not installed:
        raise AstExtractionError("No solc versions are installed for AST extraction")

    # Validate the complete intersection before choosing candidate buckets.
    source_profile_facts(sources)
    constraints = tuple(_pragma_constraints(sources))
    buckets = _candidate_buckets_for_constraints(constraints)
    if not buckets:
        raise AstExtractionError(
            "Solidity pragma constraints have no supported profiling bucket"
        )

    installed_by_text = {str(version): version for version in installed}
    required = [CANONICAL_PROFILING_COMPILERS[bucket] for bucket in buckets]
    missing = [version for version in required if version not in installed_by_text]
    if missing:
        raise AstExtractionError(
            "Canonical profiling compiler(s) "
            + ", ".join(missing)
            + " are not installed"
        )
    return [installed_by_text[version] for version in required]


def _sources_for_ast(sources: Mapping[str, str], version) -> dict[str, str]:
    pragma = f"pragma solidity {version};"
    rewritten: dict[str, str] = {}
    for name, original_text in sources.items():
        text = normalize_profile_source(original_text)
        masked = strip_noncode(text)
        spans = [match.span() for match in _PRAGMA_RE.finditer(masked)]
        profiling_copy = text
        for start, end in reversed(spans):
            profiling_copy = profiling_copy[:start] + pragma + profiling_copy[end:]
        rewritten[name] = profiling_copy
    return rewritten


def _compile_asts(sources: Mapping[str, str]) -> AstCompilation:
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
            compiler = str(version)
            return AstCompilation(
                asts=tuple(asts),
                solc_bucket=_solc_bucket(compiler),
                profiling_compiler=compiler,
            )
        failures.append(f"solc {version}: AST output missing for one or more sources")

    detail = failures[-1] if failures else "unknown compiler failure"
    raise AstExtractionError(f"Unable to build Solidity AST ({detail})")


def profile_sources(sources: Mapping[str, str]) -> dict[str, float | int | str]:
    """Build one profile from named Solidity sources using compiler-generated ASTs."""
    source_facts = source_profile_facts(sources)
    compilation = _compile_asts(sources)
    metrics = _metrics_from_asts(compilation.asts)
    return {
        **source_facts,
        "solc": compilation.solc_bucket,
        **metrics,
        "profiling_compiler": compilation.profiling_compiler,
    }


def profile_text(text: str) -> dict[str, float | int | str]:
    """Compatibility wrapper for a single, self-contained Solidity file."""
    return profile_sources({"Contract.sol": text})


def profile_target(texts: list[str]) -> dict[str, float | int | str]:
    """Compatibility wrapper for a target represented by multiple source texts."""
    return profile_sources({f"source_{index}.sol": text for index, text in enumerate(texts)})
