"""Shared target-input classification for profiling and execution."""

from __future__ import annotations

from pathlib import Path
from typing import Literal


TargetInputKind = Literal["sol", "bytecode", "runtime"]


def classify_target_input(path: str | Path) -> TargetInputKind | None:
    """Classify one source, creation-bytecode, or runtime-bytecode file."""
    candidate = Path(path)
    suffix = candidate.suffix.lower()
    if suffix == ".sol":
        return "sol"
    if suffix in {".rt", ".runtime"}:
        return "runtime"
    if suffix not in {".bin", ".hex"}:
        return None
    stem = candidate.stem.lower()
    if "runtime" in stem or stem.endswith(".rt"):
        return "runtime"
    return "bytecode"
