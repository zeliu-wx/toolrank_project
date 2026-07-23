from __future__ import annotations

import json

from toolrank.engine import _normalize_raw_findings
from toolrank.report_parser import (
    load_per_tool_findings,
    load_per_tool_findings_from_run_dir,
)


def test_generic_json_finding_round_trips_exactly_into_finding_raw(tmp_path) -> None:
    original = {
        "category": "access_control",
        "filename": "Vault.sol",
        "line": 17,
        "confidence": "Medium",
        "description": "Tool-owned description",
        "tool_specific": {
            "sentinel": ["keep", {"nested": True, "value": None}],
        },
    }
    tool_dir = tmp_path / "slither"
    tool_dir.mkdir()
    (tool_dir / "result.json").write_text(
        json.dumps({"findings": [original]}, ensure_ascii=False),
        encoding="utf-8",
    )

    parsed = load_per_tool_findings_from_run_dir(tmp_path, {"slither"})
    finding = _normalize_raw_findings("slither", parsed["slither"])[0]

    assert finding.category == "access_control"
    assert finding.location == "Vault.sol:17"
    assert finding.confidence is None
    assert finding.raw == original
    assert finding.raw is not parsed["slither"][0]["raw"]
    assert "source_tool" not in finding.raw
    assert "location" not in finding.raw


def test_sarif_result_round_trips_exactly_into_finding_raw(tmp_path) -> None:
    original = {
        "ruleId": "controlled-delegatecall",
        "level": "warning",
        "message": {"text": "Delegatecall target is controlled"},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": "Vault.sol"},
                    "region": {"startLine": 23, "sentinel": "keep-region"},
                }
            }
        ],
        "properties": {
            "confidence": "Medium",
            "sentinel": {"nested": [1, 2, 3]},
        },
    }
    sarif = {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "rules": [
                            {
                                "id": "controlled-delegatecall",
                                "properties": {"tags": ["access_control"]},
                            }
                        ]
                    }
                },
                "results": [original],
            }
        ],
    }
    (tmp_path / "slither.sarif").write_text(
        json.dumps(sarif, ensure_ascii=False),
        encoding="utf-8",
    )

    parsed = load_per_tool_findings(tmp_path, {"slither"})
    finding = _normalize_raw_findings("slither", parsed["slither"])[0]

    assert finding.category == "access_control"
    assert finding.location == "Vault.sol:23"
    assert finding.raw == original
    assert finding.raw is not parsed["slither"][0]["raw"]


def test_ignored_json_findings_remain_excluded(tmp_path) -> None:
    accepted = {"category": "arithmetic", "sentinel": "accepted"}
    tool_dir = tmp_path / "slither"
    tool_dir.mkdir()
    (tool_dir / "result.json").write_text(
        json.dumps(
            {
                "findings": [
                    accepted,
                    {"category": "IGNORE", "sentinel": "ignored-category"},
                    {
                        "category": "access_control",
                        "ignored": True,
                        "sentinel": "ignored-flag",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    parsed = load_per_tool_findings_from_run_dir(tmp_path, {"slither"})
    findings = _normalize_raw_findings("slither", parsed["slither"])

    assert [finding.raw for finding in findings] == [accepted]


def test_analyzer_owned_raw_field_does_not_turn_finding_into_parser_projection() -> None:
    original = {
        "source_tool": "analyzer-owned-value",
        "category": "access_control",
        "location": "Vault.sol:31",
        "explanation": "Outer finding must remain authoritative",
        "raw": {"nested": "analyzer-owned", "sentinel": [1, 2, 3]},
        "outer_sentinel": "must-not-be-dropped",
    }

    finding = _normalize_raw_findings("slither", [original])[0]

    assert finding.raw == original
    assert finding.raw is not original
    assert finding.raw["outer_sentinel"] == "must-not-be-dropped"
