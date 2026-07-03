from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List

from toolrank import _complexity
from toolrank.schemas import ContractFeatures

_PRAGMA_RE = re.compile(r"pragma\s+solidity\s+([^;]+);", re.IGNORECASE)
_VERSION_RE = re.compile(r"0\.[4-8](?:\.\d+|\.x)?")
_CONTRACT_RE = re.compile(r"\b(contract|library|interface)\s+[A-Za-z_][A-Za-z0-9_]*")
_FUNCTION_RE = re.compile(r"\bfunction\s+[A-Za-z_][A-Za-z0-9_]*")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _semver_key(version: str) -> tuple:
    """Parse a version string like '0.8.20' into a tuple of ints for correct comparison."""
    parts = []
    for part in version.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _choose_primary_version(versions: List[str]) -> str | None:
    if not versions:
        return None
    # Prefer the most concrete version; fall back to max within known ranges.
    concrete = [v for v in versions if not v.endswith(".x")]
    if concrete:
        return max(concrete, key=_semver_key)
    return max(versions, key=_semver_key)


def _loc_total(files: Iterable[Path]) -> int:
    total = 0
    for path in files:
        text = _read_text(path)
        total += sum(1 for line in text.splitlines() if line.strip())
    return total


def analyze_target(target_path: str | None) -> ContractFeatures:
    if not target_path:
        return ContractFeatures()

    path = Path(target_path).expanduser().resolve()
    if not path.exists():
        return ContractFeatures(target_path=str(path))

    sol_files: List[Path] = []
    bytecode_files: List[Path] = []
    runtime_files: List[Path] = []

    if path.is_file():
        suffix = path.suffix.lower()
        if suffix == ".sol":
            sol_files = [path]
        elif suffix in {".bin", ".hex"}:
            if "runtime" in path.stem.lower():
                runtime_files = [path]
            else:
                bytecode_files = [path]
    else:
        sol_files = sorted(path.rglob("*.sol"))
        bytecode_files = sorted([p for p in path.rglob("*.bin") if "runtime" not in p.stem.lower()])
        runtime_files = sorted([p for p in path.rglob("*.bin") if "runtime" in p.stem.lower()])

    versions: List[str] = []
    contract_count = 0
    function_count = 0
    sol_sources: dict[str, str] = {}
    source_root = path if path.is_dir() else path.parent
    if sol_files:
        for sol_file in sol_files:
            text = _read_text(sol_file)
            try:
                source_name = sol_file.relative_to(source_root).as_posix()
            except ValueError:
                source_name = sol_file.name
            sol_sources[source_name] = text
            versions.extend(_VERSION_RE.findall(" ".join(_PRAGMA_RE.findall(text))))
            contract_count += len(_CONTRACT_RE.findall(text))
            function_count += len(_FUNCTION_RE.findall(text))

    try:
        complexity = _complexity.profile_sources(sol_sources) if sol_sources else {}
    except _complexity.AstExtractionError:
        complexity = {}

    if sol_files and (bytecode_files or runtime_files):
        source_kind = "mixed"
    elif sol_files:
        source_kind = "sol"
    elif bytecode_files:
        source_kind = "bytecode"
    elif runtime_files:
        source_kind = "runtime"
    else:
        source_kind = "unknown"

    file_count = len(sol_files) if sol_files else len(bytecode_files) + len(runtime_files)
    features = ContractFeatures(
        target_path=str(path),
        source_kind=source_kind,
        solidity_versions=sorted(set(versions)),
        primary_solidity_version=_choose_primary_version(sorted(set(versions))),
        loc_total=_loc_total(sol_files) if sol_files else 0,
        function_count=function_count,
        file_count=file_count,
        contract_count=contract_count,
        is_multifile=len(sol_files) > 1,
        cyclomatic_avg=complexity.get("avg_cyc", 0.0),
        cyclomatic_max=complexity.get("max_cyc", 0),
        cyclomatic_sum=complexity.get("sum_cyc", 0),
        max_nesting=complexity.get("max_nest", 0),
        contract_coupling=complexity.get("coupling", 0),
    )
    return features
