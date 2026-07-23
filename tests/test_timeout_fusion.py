from __future__ import annotations

from toolrank.fusion import fuse_reports
from toolrank.schemas import CompositionPlan, Finding, ToolExecutionStatus


def test_timeout_keeps_surviving_owner_and_marks_unavailable_categories() -> None:
    composition = CompositionPlan(
        selected_tool_ids=["a", "b"],
        primary_tool_id="a",
        complementary_tool_ids=["b"],
        estimated_plan_runtime_minutes=8.0,
        category_owners={
            "reentrancy": ["a", "b"],
            "access_control": ["a"],
        },
    )
    report = fuse_reports(
        {"b": [Finding(source_tool="b", category="reentrancy", location="A.sol:4")]},
        composition,
        tool_statuses={
            "a": ToolExecutionStatus(status="TIMEOUT"),
            "b": ToolExecutionStatus(status="SUCCESS"),
        },
    )

    assert [item.category for item in report.findings] == ["reentrancy"]
    assert report.partial_categories == ["reentrancy"]
    assert report.unavailable_categories == ["access_control"]
