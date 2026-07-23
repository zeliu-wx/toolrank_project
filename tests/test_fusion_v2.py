from __future__ import annotations

import pytest

from toolrank.fusion import compact_fused_report_payload, fuse_reports
from toolrank.schemas import CompositionPlan, Finding, FusedReport, ToolExecutionStatus


def plan() -> CompositionPlan:
    return CompositionPlan(
        selected_tool_ids=["a", "b"],
        primary_tool_id="a",
        complementary_tool_ids=["b"],
        estimated_plan_runtime_minutes=8.0,
        category_owners={"reentrancy": ["a", "b"]},
    )


def test_same_category_and_location_merge_with_provenance_and_conflicts() -> None:
    report = fuse_reports(
        {
            "a": [
                Finding(
                    source_tool="a",
                    category="reentrancy",
                    location="A.sol:10",
                    severity="high",
                    explanation="primary explanation",
                    raw={"id": "a1"},
                )
            ],
            "b": [
                Finding(
                    source_tool="b",
                    category="reentrancy",
                    location="A.sol:10",
                    severity="medium",
                    explanation="complement explanation",
                    raw={"id": "b1"},
                )
            ],
        },
        plan(),
    )

    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.source_tools == ["a", "b"]
    assert finding.severity_values == {"a": ["high"], "b": ["medium"]}
    assert set(finding.inconsistent_fields) == {"severity", "explanation"}
    assert [item.raw["id"] for item in finding.raw_findings] == ["a1", "b1"]


def test_locationless_findings_remain_distinct_and_unowned_complement_is_ignored() -> None:
    report = fuse_reports(
        {
            "a": [Finding(source_tool="a", category="reentrancy")],
            "b": [
                Finding(source_tool="b", category="reentrancy"),
                Finding(source_tool="b", category="access_control", location="A.sol:2"),
            ],
        },
        plan(),
    )
    assert len(report.findings) == 2
    assert all(item.category == "reentrancy" for item in report.findings)


def test_category_results_include_empty_required_and_observed_primary_categories() -> None:
    composition = CompositionPlan(
        selected_tool_ids=["a", "b"],
        primary_tool_id="a",
        complementary_tool_ids=["b"],
        estimated_plan_runtime_minutes=8.0,
        category_owners={
            "arithmetic": ["a"],
            "reentrancy": ["a", "b"],
        },
    )
    statuses = {
        "a": ToolExecutionStatus(status="SUCCESS", runtime_minutes=1.0),
        "b": ToolExecutionStatus(status="SUCCESS", runtime_minutes=2.0),
    }
    primary_reentrancy = {"id": "a-r", "nested": {"sentinel": "primary"}}
    complement_reentrancy = {"id": "b-r", "confidence": "Medium"}
    observed_access_control = {
        "id": "a-ac",
        "tool_specific": [1, {"sentinel": True}],
    }
    excluded_non_owner = {"id": "b-ac", "sentinel": "must-not-appear"}

    report = fuse_reports(
        {
            "a": [
                Finding(
                    source_tool="a",
                    category="reentrancy",
                    raw=primary_reentrancy,
                ),
                Finding(
                    source_tool="a",
                    category="access_control",
                    raw=observed_access_control,
                ),
            ],
            "b": [
                Finding(
                    source_tool="b",
                    category="reentrancy",
                    raw=complement_reentrancy,
                ),
                Finding(
                    source_tool="b",
                    category="access_control",
                    raw=excluded_non_owner,
                ),
            ],
        },
        composition,
        tool_statuses=statuses,
        findings_source="execution",
    )

    assert [result.category for result in report.category_results] == [
        "arithmetic",
        "reentrancy",
        "access_control",
    ]
    arithmetic, reentrancy, access_control = report.category_results
    assert arithmetic.owner_tools == ["a"]
    assert list(arithmetic.tools) == ["a"]
    assert arithmetic.tools["a"].findings == []
    assert arithmetic.tools["a"].status == report.tool_statuses["a"]

    assert reentrancy.owner_tools == ["a", "b"]
    assert list(reentrancy.tools) == ["a", "b"]
    assert reentrancy.tools["a"].findings == [primary_reentrancy]
    assert reentrancy.tools["b"].findings == [complement_reentrancy]

    assert access_control.owner_tools == ["a"]
    assert list(access_control.tools) == ["a"]
    assert access_control.tools["a"].findings == [observed_access_control]
    assert excluded_non_owner not in [
        finding
        for result in report.category_results
        for tool_result in result.tools.values()
        for finding in tool_result.findings
    ]

    persisted = compact_fused_report_payload(report)
    assert persisted["category_results"][0]["category"] == "arithmetic"
    assert persisted["category_results"][0]["tools"]["a"]["findings"] == []
    assert persisted["combination_explanation"]["source"] == "DETERMINISTIC_FALLBACK"
    assert persisted["combination_explanation"]["text"]


def test_fused_report_rejects_top_level_and_per_category_status_contradiction() -> None:
    report = fuse_reports(
        {"a": []},
        CompositionPlan(
            selected_tool_ids=["a"],
            primary_tool_id="a",
            complementary_tool_ids=[],
            category_owners={"arithmetic": ["a"]},
        ),
        tool_statuses={"a": ToolExecutionStatus(status="SUCCESS")},
        findings_source="execution",
    )
    payload = report.model_dump(mode="json")
    payload["category_results"][0]["tools"]["a"]["status"]["status"] = "FAIL"

    with pytest.raises(ValueError, match="top-level tool status"):
        FusedReport.model_validate(payload)
