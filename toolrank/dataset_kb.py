from __future__ import annotations

import json
import math
from pathlib import Path
from typing import List, Optional, Tuple

from pydantic import ValidationError

from toolrank.schemas import PerformanceEntry, PerformanceKnowledgeBase


def load_performance_db(path: str | Path) -> PerformanceKnowledgeBase:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    kb = PerformanceKnowledgeBase.model_validate(payload)
    _validate_dynamic_identities(kb)
    return kb


def _validate_dynamic_identities(kb: PerformanceKnowledgeBase) -> None:
    """Validate additive dynamic fields without constraining legacy entries."""
    dataset_ids: set[str] = set()
    observation_ids: set[str] = set()
    for entry in kb.entries:
        if entry.canonical_dataset_id is not None:
            if entry.canonical_dataset_id in dataset_ids:
                raise ValueError(
                    f"duplicate canonical dataset identity: {entry.canonical_dataset_id}"
                )
            dataset_ids.add(entry.canonical_dataset_id)
        for observation in entry.performance_observations:
            if observation.observation_id in observation_ids:
                raise ValueError(
                    f"duplicate performance observation ID: {observation.observation_id}"
                )
            observation_ids.add(observation.observation_id)
            if (
                entry.canonical_dataset_id is not None
                and observation.canonical_dataset_id != entry.canonical_dataset_id
            ):
                raise ValueError(
                    "performance observation canonical dataset does not match its entry"
                )
            if observation.dataset_name != entry.dataset_profile.dataset_name:
                raise ValueError(
                    "performance observation dataset name does not match its entry"
                )
            if observation.source_id != entry.source_id:
                raise ValueError(
                    "performance observation source does not match its dataset entry"
                )


# ---------------------------------------------------------------------------
# Paper §III.D Map&Check Gate(2): numeric-range gate on the dataset-knowledge
# commit path. "An entry that fails any gate is rejected and written to a log."
# Ranges mirror the canonical D1Metric constraints (schemas.py):
#   rate-like fields in [0, 1]; time-like fields > 0 (strictly positive,
#   mirroring D1Metric gt=0.0 — primarily enforced by schema validation;
#   this gate is a defensive backstop for the named D1Metric time fields).
# vulnerability_scores are normalized to fractions (detected/total) before
# they reach this point (ToolPerformanceObservation._normalize_tp_over_gt_scores)
# and are consumed as rates, so they are bounded to [0, 1] as well.
# ---------------------------------------------------------------------------

_RATE_FIELDS = ("precision", "recall", "f1", "accuracy", "failure_rate")
_TIME_FIELDS = ("execution_time_avg", "time_sec", "execution_time_avg_average_s")


def _gate_numeric_ranges(entry: PerformanceEntry) -> Optional[str]:
    """Return a reason string if *entry* has any out-of-range numeric, else None."""
    for obs in entry.tool_performance_data:
        metrics = obs.metrics
        for field in _RATE_FIELDS:
            value = getattr(metrics, field, None)
            if value is not None and not (0.0 <= value <= 1.0):
                return f"{obs.tool_name}.metrics.{field}={value} not in [0.0, 1.0]"
        for field in _TIME_FIELDS:
            value = getattr(metrics, field, None)
            if value is not None and (value <= 0.0 or not math.isfinite(value)):
                return (
                    f"{obs.tool_name}.metrics.{field}={value} "
                    "not positive and finite"
                )
        for category, score in (obs.vulnerability_scores or {}).items():
            if not (0.0 <= score <= 1.0):
                return (
                    f"{obs.tool_name}.vulnerability_scores.{category}="
                    f"{score} not in [0.0, 1.0]"
                )
    return None


def _validate_entry(raw_entry: dict) -> Tuple[Optional[PerformanceEntry], Optional[str]]:
    """Validate a single raw entry through the schema and the numeric-range gate.

    Returns ``(entry, None)`` if it passes, or ``(None, reason)`` if it fails.
    """
    try:
        entry = PerformanceEntry.model_validate(raw_entry)
    except ValidationError as exc:
        return None, f"schema validation failed: {exc.errors()[0].get('loc')} -> {exc.errors()[0].get('msg')}"
    reason = _gate_numeric_ranges(entry)
    if reason is not None:
        return None, reason
    return entry, None


# ---------------------------------------------------------------------------
# Issue 4: Dataset / Benchmark KB refresh path
# Paper (§3.3): "The benchmark base is refreshed when new curated benchmark
# artifacts are incorporated."
# ---------------------------------------------------------------------------


def refresh_performance_db(
    existing_path: str | Path,
    new_artifact_paths: List[str | Path],
    output_path: Optional[str | Path] = None,
) -> PerformanceKnowledgeBase:
    """Ingest new benchmark performance artifacts and merge into existing DB.

    Each *new_artifact_path* must be a JSON file with the same schema as
    ``performance_db.json`` (i.e., ``PerformanceKnowledgeBase``).
    New entries are appended; if an entry with the same ``source_id`` already
    exists, the new entry *replaces* it (fresher evidence wins).

    Paper §III.D Map&Check Gate(2): each incoming entry is validated through a
    numeric-range gate (rate-like fields in [0, 1]; time-like fields > 0). An
    entry that fails any gate is *not* merged; instead it is appended to a
    reject log written next to the output (``*_reject_log.json``) with the
    offending field and reason.
    """
    existing_path = Path(existing_path)
    if existing_path.exists():
        base = load_performance_db(existing_path)
    else:
        base = PerformanceKnowledgeBase(knowledge_base_type="performance", entries=[])

    existing_ids = {entry.source_id for entry in base.entries}
    rejects: List[dict] = []

    for artifact_path in new_artifact_paths:
        payload = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
        for raw_entry in payload.get("entries", []):
            entry, reason = _validate_entry(raw_entry)
            if entry is None:
                rejects.append(
                    {
                        "source_id": raw_entry.get("source_id"),
                        "reason": reason,
                        "artifact": str(artifact_path),
                    }
                )
                continue
            if entry.source_id in existing_ids:
                # Replace existing entry with fresher evidence
                base.entries = [e for e in base.entries if e.source_id != entry.source_id]
            base.entries.append(entry)
            existing_ids.add(entry.source_id)

    out = Path(output_path) if output_path else existing_path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(base.model_dump(by_alias=True), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    if rejects:
        reject_log = out.with_name(f"{out.stem}_reject_log.json")
        reject_log.parent.mkdir(parents=True, exist_ok=True)
        reject_log.write_text(
            json.dumps(rejects, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return base
