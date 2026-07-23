from __future__ import annotations

from toolrank.categories import normalize_category
from toolrank.fusion import fuse_reports
from toolrank.report_parser import _normalize_json_finding
from toolrank.runner import _parse_tool_category_filters
from toolrank.runner_adapter import _enrich_report_with_categories
from toolrank.schemas import CompositionPlan, Finding, ToolPerformanceObservation


def test_legacy_category_aliases_normalize_to_internal_long_form() -> None:
    assert normalize_category("denial_service") == "denial_of_service"
    assert normalize_category("DENIAL OF SERVICE") == "denial_of_service"
    assert normalize_category("unchecked_low_calls") == "unchecked_low_level_calls"
    assert normalize_category("unchecked_ll_calls") == "unchecked_low_level_calls"
    assert normalize_category("other") == "unknown_unknowns"


def test_runner_input_and_enrichment_emit_long_form_categories() -> None:
    filters = _parse_tool_category_filters(
        "mythril:DENIAL_SERVICE|UNCHECKED_LOW_CALLS|OTHER"
    )
    assert filters == {
        "mythril": [
            "denial_of_service",
            "unchecked_low_level_calls",
            "unknown_unknowns",
        ]
    }

    enriched = _enrich_report_with_categories(
        {"findings": [{"name": "legacy"}]},
        "mythril",
        {("mythril", "legacy"): "DENIAL_SERVICE"},
    )
    assert enriched["findings"][0]["category"] == "denial_of_service"


def test_parser_and_fusion_keep_legacy_named_complement_findings() -> None:
    parsed = _normalize_json_finding(
        {
            "category": "unchecked_low_calls",
            "filename": "Token.sol",
            "line": 7,
        },
        "mythril",
    )
    assert parsed["category"] == "unchecked_low_level_calls"

    plan = CompositionPlan(
        selected_tool_ids=["slither", "mythril"],
        primary_tool_id="slither",
        complementary_tool_ids=["mythril"],
        category_owners={"unchecked_low_level_calls": ["slither", "mythril"]},
    )
    report = fuse_reports(
        {
            "mythril": [
                Finding(
                    source_tool="mythril",
                    category="unchecked_low_calls",
                    location="Token.sol:7",
                )
            ]
        },
        plan,
    )

    assert len(report.findings) == 1
    assert report.findings[0].category == "unchecked_low_level_calls"
    assert report.findings[0].source_tools == ["mythril"]


def test_performance_counts_normalize_without_matching_score_keys() -> None:
    observation = ToolPerformanceObservation.model_validate(
        {
            "tool_name": "mythril",
            "metrics": {},
            "vulnerability_scores": {"reentrancy": 0.5},
            "vulnerability_score_counts": {
                "denial_service": {"detected": 3, "total": 4},
                "unchecked_low_calls": {"detected": 2, "total": 5},
            },
        }
    )

    assert observation.vulnerability_scores == {"reentrancy": 0.5}
    assert set(observation.vulnerability_score_counts or {}) == {
        "denial_of_service",
        "unchecked_low_level_calls",
    }


def test_performance_counts_only_payload_normalizes_legacy_aliases() -> None:
    observation = ToolPerformanceObservation.model_validate(
        {
            "tool_name": "slither",
            "metrics": {},
            "vulnerability_score_counts": {
                "other": {"detected": 1, "total": 9},
            },
        }
    )

    assert observation.vulnerability_scores is None
    assert set(observation.vulnerability_score_counts or {}) == {
        "unknown_unknowns"
    }
