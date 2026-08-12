from __future__ import annotations

import json
from pathlib import Path

from toolrank import execution
from toolrank.engine import _normalize_raw_findings
from toolrank.fusion import fuse_reports
from toolrank.process_deadline import DeadlineProcessResult
from toolrank.schemas import (
    CompositionPlan,
    ExecutionResult,
    ExecutionSchedule,
    ToolExecutionStatus,
)


def _write_report(path: Path, *, finding: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "findings": [
                    {
                        "name": finding,
                        "category": "access_control",
                        "filename": "Deploy.bin",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_manual_runner_mixed_success_and_timeout_is_usable_partial(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "Deploy.bin"
    target.write_text("6000", encoding="utf-8")
    results = tmp_path / "results"

    def fake_runner(_command, **_kwargs):
        _write_report(
            results / "slither" / "Deploy.bin" / "result.json",
            finding="tx-origin",
        )
        (results / "tool_run_statuses.json").write_text(
            json.dumps(
                {
                    "slither": ToolExecutionStatus(
                        status="SUCCESS", return_code=0
                    ).model_dump(mode="json"),
                    "mythril": ToolExecutionStatus(
                        status="TIMEOUT", return_code=124
                    ).model_dump(mode="json"),
                }
            ),
            encoding="utf-8",
        )
        return 124, "", "mythril timed out"

    monkeypatch.setattr(execution, "_stream_runner_output", fake_runner)
    plan = ExecutionResult(
        status="planned",
        target_path=str(target),
        results_root=str(results),
        runner_command=["fake-runner"],
        selected_tool_ids=["slither", "mythril"],
        primary_tool_id="slither",
        category_owners={"access_control": ["slither", "mythril"]},
        execution_schedule=ExecutionSchedule(tool_timeout_seconds=30.0),
    )

    completed = execution.execute_plan(plan)

    assert completed.status == "partial"
    assert completed.return_code == 124
    assert completed.tool_statuses["slither"].status == "SUCCESS"
    assert completed.tool_statuses["mythril"].status == "TIMEOUT"
    assert len(completed.per_tool_findings["slither"]) == 1


def test_manual_runner_without_any_usable_tool_is_execution_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "Deploy.bin"
    target.write_text("6000", encoding="utf-8")
    results = tmp_path / "results"

    def fake_runner(_command, **_kwargs):
        (results / "tool_run_statuses.json").write_text(
            json.dumps(
                {
                    "slither": ToolExecutionStatus(
                        status="FAIL", return_code=1
                    ).model_dump(mode="json"),
                    "mythril": ToolExecutionStatus(
                        status="TIMEOUT", return_code=124
                    ).model_dump(mode="json"),
                }
            ),
            encoding="utf-8",
        )
        return 1, "", "all tools unavailable"

    monkeypatch.setattr(execution, "_stream_runner_output", fake_runner)
    plan = ExecutionResult(
        status="planned",
        target_path=str(target),
        results_root=str(results),
        runner_command=["fake-runner"],
        selected_tool_ids=["slither", "mythril"],
        primary_tool_id="slither",
        execution_schedule=ExecutionSchedule(tool_timeout_seconds=30.0),
    )

    completed = execution.execute_plan(plan)

    assert completed.status == "failed"
    assert completed.per_tool_findings == {}


def test_native_mixed_success_and_timeout_retains_a_partial_fused_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "Deploy.sol"
    target.write_text(
        "pragma solidity ^0.4.25;\ncontract Deploy {}\n",
        encoding="utf-8",
    )
    results = tmp_path / "results"
    smartbugs = tmp_path / "smartbugs"
    package = smartbugs / "sb"
    package.mkdir(parents=True)
    for name in ("cli.py", "docker.py"):
        (package / name).write_text("# test sentinel\n", encoding="utf-8")
    monkeypatch.setattr(execution, "DEFAULT_SMARTBUGS_DIR", smartbugs)

    def fake_run(command, **_kwargs):
        tool = command[command.index("-t") + 1]
        if tool == "slither":
            staged = Path(command[command.index("--results") + 1])
            _write_report(staged / "result.json", finding="tx-origin")
            return DeadlineProcessResult(returncode=0, elapsed_seconds=0.1)
        return DeadlineProcessResult(
            returncode=124,
            timed_out=True,
            elapsed_seconds=30.0,
        )

    monkeypatch.setattr(execution, "run_process_with_deadline", fake_run)
    plan = ExecutionResult(
        status="planned",
        target_path=str(target),
        results_root=str(results),
        selected_tool_ids=["slither", "mythril"],
        primary_tool_id="slither",
        category_owners={"access_control": ["slither", "mythril"]},
        execution_schedule=ExecutionSchedule(tool_timeout_seconds=30.0),
    )

    completed = execution._native_smartbugs_execute(plan)
    composition = CompositionPlan(
        selected_tool_ids=["slither", "mythril"],
        primary_tool_id="slither",
        complementary_tool_ids=["mythril"],
        category_owners={"access_control": ["slither", "mythril"]},
    )
    fused = fuse_reports(
        {
            tool: _normalize_raw_findings(tool, findings)
            for tool, findings in completed.per_tool_findings.items()
        },
        composition,
        tool_statuses=completed.tool_statuses,
        findings_source="execution",
    )

    assert completed.status == "partial"
    assert completed.tool_statuses["slither"].status == "SUCCESS"
    assert completed.tool_statuses["mythril"].status == "TIMEOUT"
    assert len(completed.per_tool_findings["slither"]) == 1
    assert len(fused.findings) == 1
    assert fused.findings[0].source_tools == ["slither"]
    assert fused.partial_categories == ["access_control"]
