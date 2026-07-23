"""Stage 3 additive finding fusion."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from toolrank.categories import DASP10_CATEGORIES, normalize_category
from toolrank.report_explanation import deterministic_combination_explanation

from toolrank.schemas import (
    CategoryResult,
    CategoryToolResult,
    CombinationExplanation,
    CompositionPlan,
    Finding,
    FusedFinding,
    FusedReport,
    ToolExecutionStatus,
)


_USABLE_RUN_STATUSES = {"SUCCESS", "PARTIAL"}


def _unique_values(items: Sequence[Finding], field: str) -> list:
    values: list = []
    for item in items:
        value = getattr(item, field)
        if value in {None, ""} or value in values:
            continue
        values.append(value)
    return values


def _values_by_tool(items: Sequence[Finding], field: str) -> dict[str, list]:
    values: dict[str, list] = {}
    for item in items:
        value = getattr(item, field)
        if value in {None, ""}:
            continue
        bucket = values.setdefault(item.source_tool, [])
        if value not in bucket:
            bucket.append(value)
    return values


def _fused_finding(items: list[Finding], selected_order: list[str]) -> FusedFinding:
    source_set = {item.source_tool for item in items}
    sources = [tool for tool in selected_order if tool in source_set]
    sources.extend(sorted(source_set - set(sources)))
    inconsistent: list[str] = []
    for output_name, field in (
        ("severity", "severity"),
        ("confidence", "confidence"),
        ("explanation", "explanation"),
    ):
        if len(_unique_values(items, field)) > 1:
            inconsistent.append(output_name)
    return FusedFinding(
        category=normalize_category(items[0].category),
        location=items[0].location.strip(),
        source_tools=sources,
        severity_values=_values_by_tool(items, "severity"),
        confidence_values=_values_by_tool(items, "confidence"),
        explanation_variants=_values_by_tool(items, "explanation"),
        inconsistent_fields=inconsistent,
        raw_findings=items,
    )


def _resolved_statuses(
    composition: CompositionPlan,
    supplied: Mapping[str, ToolExecutionStatus] | None,
) -> dict[str, ToolExecutionStatus]:
    if supplied is None:
        return {
            tool: ToolExecutionStatus(status="SUCCESS")
            for tool in composition.selected_tool_ids
        }
    return {
        tool: supplied.get(tool, ToolExecutionStatus())
        for tool in composition.selected_tool_ids
    }


def _category_availability(
    composition: CompositionPlan,
    statuses: Mapping[str, ToolExecutionStatus],
) -> tuple[list[str], list[str]]:
    unavailable: list[str] = []
    partial: list[str] = []
    for category, owners in composition.category_owners.items():
        owner_statuses = [statuses.get(tool, ToolExecutionStatus()) for tool in owners]
        usable = [status for status in owner_statuses if status.status in _USABLE_RUN_STATUSES]
        if not usable:
            unavailable.append(category)
        elif len(usable) < len(owners) or any(status.status == "PARTIAL" for status in usable):
            partial.append(category)
    return unavailable, partial


def _category_results(
    composition: CompositionPlan,
    statuses: Mapping[str, ToolExecutionStatus],
    accepted: Sequence[Finding],
) -> list[CategoryResult]:
    owner_lists: OrderedDict[str, list[str]] = OrderedDict(
        (
            normalize_category(category),
            list(owners),
        )
        for category, owners in composition.category_owners.items()
    )
    for finding in accepted:
        category = normalize_category(finding.category)
        if category in DASP10_CATEGORIES:
            owner_lists.setdefault(category, [composition.primary_tool_id])

    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for finding in accepted:
        category = normalize_category(finding.category)
        grouped.setdefault(category, {}).setdefault(finding.source_tool, []).append(
            deepcopy(finding.raw)
        )

    return [
        CategoryResult(
            category=category,
            owner_tools=owners,
            tools={
                tool: CategoryToolResult(
                    status=statuses[tool],
                    findings=grouped.get(category, {}).get(tool, []),
                )
                for tool in owners
            },
        )
        for category, owners in owner_lists.items()
    ]


def fuse_reports(
    findings_by_tool: Mapping[str, Sequence[Finding]],
    composition: CompositionPlan,
    *,
    tool_statuses: Mapping[str, ToolExecutionStatus] | None = None,
    findings_source: str = "synthesized",
    combination_explanation: CombinationExplanation | None = None,
) -> FusedReport:
    """Fuse owner-authorized findings by non-empty ``(category, location)``.

    The primary contributes every category.  A complement contributes only the
    categories whose additive owner set names it.  Locationless findings stay
    distinct because there is no reliable cross-tool identity key for them.
    """
    statuses = _resolved_statuses(composition, tool_statuses)
    groups: OrderedDict[tuple[str, str, int | None], list[Finding]] = OrderedDict()
    accepted: list[Finding] = []
    accepted_count = 0
    serial = 0
    owner_sets = {
        normalize_category(category): set(owners)
        for category, owners in composition.category_owners.items()
    }

    for tool in composition.selected_tool_ids:
        if statuses[tool].status not in _USABLE_RUN_STATUSES:
            continue
        for finding in findings_by_tool.get(tool, []):
            category = normalize_category(finding.category)
            if tool != composition.primary_tool_id and tool not in owner_sets.get(category, set()):
                continue
            location = finding.location.strip()
            if location:
                key = (category, location, None)
            else:
                serial += 1
                key = (category, "", serial)
            groups.setdefault(key, []).append(finding)
            accepted.append(finding)
            accepted_count += 1

    fused = [
        _fused_finding(items, composition.selected_tool_ids)
        for items in groups.values()
    ]
    unavailable, partial = _category_availability(composition, statuses)
    summary = "; ".join(
        (
            f"primary={composition.primary_tool_id}",
            f"selected_tools={composition.selected_tool_ids}",
            f"fused_findings={len(fused)}",
            f"deduplicated={accepted_count - len(fused)}",
            f"unavailable_categories={unavailable}",
            f"partial_categories={partial}",
            f"source={findings_source}",
        )
    )
    return FusedReport(
        primary_tool_id=composition.primary_tool_id,
        category_owners=composition.category_owners,
        tool_statuses=statuses,
        combination_explanation=(
            combination_explanation
            if combination_explanation is not None
            else deterministic_combination_explanation(composition)
        ),
        category_results=_category_results(composition, statuses, accepted),
        findings=fused,
        deduplicated_count=accepted_count - len(fused),
        unavailable_categories=unavailable,
        partial_categories=partial,
        findings_source=findings_source,
        summary=summary,
    )


def compact_fused_report_payload(fused_report: FusedReport) -> dict[str, Any]:
    """Return the persisted report without dropping provenance or conflicts."""
    return {
        "primary_tool": fused_report.primary_tool_id,
        "category_owners": fused_report.category_owners,
        "combination_explanation": fused_report.combination_explanation.model_dump(
            mode="json"
        ),
        "category_results": [
            result.model_dump(mode="json") for result in fused_report.category_results
        ],
        "tool_statuses": {
            tool: status.model_dump(mode="json")
            for tool, status in fused_report.tool_statuses.items()
        },
        "unavailable_categories": fused_report.unavailable_categories,
        "partial_categories": fused_report.partial_categories,
        "findings": [finding.model_dump(mode="json") for finding in fused_report.findings],
    }
