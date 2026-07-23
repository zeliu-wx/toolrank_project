import json
from pathlib import Path
import threading

import pytest

from toolrank import execution
from toolrank.engine import _normalize_raw_findings
from toolrank.fusion import fuse_reports
from toolrank.process_deadline import DeadlineProcessResult
from toolrank.schemas import CompositionPlan, ExecutionResult, ExecutionSchedule


def _write_report(
    path: Path,
    filename: str,
    finding_name: str = "tx-origin",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "findings": [
                    {
                        "name": finding_name,
                        "line": 7,
                        "filename": filename,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def _configure_smartbugs(tmp_path: Path, monkeypatch) -> Path:
    smartbugs = tmp_path / "smartbugs"
    package = smartbugs / "sb"
    package.mkdir(parents=True)
    for name in ("cli.py", "docker.py"):
        (package / name).write_text("# test sentinel\n", encoding="utf-8")
    monkeypatch.setattr(execution, "DEFAULT_SMARTBUGS_DIR", smartbugs)
    return smartbugs


def test_native_fallback_matches_parallel_tools_and_sequential_files_schedule(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "contracts"
    target.mkdir()
    for name in ("A.sol", "B.sol"):
        (target / name).write_text(
            f"pragma solidity ^0.4.25;\ncontract {name[0]} {{}}\n",
            encoding="utf-8",
        )
    results = tmp_path / "results"
    stale_reports = [
        results / tool / "Old.sol" / "result.json"
        for tool in ("slither", "mythril")
    ]
    for stale_report in stale_reports:
        _write_report(stale_report, "Old.sol")
    unselected_report = results / "osiris" / "Old.sol" / "result.json"
    _write_report(unselected_report, "Old.sol")
    _configure_smartbugs(tmp_path, monkeypatch)

    first_file_barrier = threading.Barrier(2)
    calls: list[tuple[str, str, float]] = []
    calls_lock = threading.Lock()
    elapsed = {
        ("slither", "A.sol"): 30.0,
        ("slither", "B.sol"): 60.0,
        ("mythril", "A.sol"): 90.0,
        ("mythril", "B.sol"): 120.0,
    }

    def fake_run(command, *, timeout_seconds, **kwargs):
        assert all(not report.exists() for report in stale_reports)
        tool = command[command.index("-t") + 1]
        filename = Path(command[command.index("-f") + 1]).name
        assert command[command.index("--timeout") + 1] == "321"
        assert timeout_seconds == 321.0
        with calls_lock:
            calls.append((tool, filename, timeout_seconds))
        if filename == "A.sol":
            first_file_barrier.wait(timeout=2.0)
        out_dir = Path(command[command.index("--results") + 1])
        _write_report(
            out_dir / "result.json",
            filename,
            "Use of tx.origin" if tool == "mythril" else "tx-origin",
        )
        return DeadlineProcessResult(
            returncode=0,
            elapsed_seconds=elapsed[(tool, filename)],
        )

    monkeypatch.setattr(execution, "run_process_with_deadline", fake_run)
    plan = ExecutionResult(
        status="planned",
        target_path=str(target),
        results_root=str(results),
        selected_tool_ids=["slither", "mythril"],
        primary_tool_id="slither",
        category_owners={"access_control": ["slither", "mythril"]},
        execution_schedule=ExecutionSchedule(
            contract_count=2,
            execution_jobs=0,
            tool_timeout_seconds=321.0,
            timeout_source="explicit",
        ),
    )

    completed = execution._native_smartbugs_execute(plan)

    assert completed.status == "executed"
    assert all(not report.exists() for report in stale_reports)
    assert unselected_report.exists()
    assert len(calls) == 4
    for tool in ("slither", "mythril"):
        assert [filename for called_tool, filename, _ in calls if called_tool == tool] == [
            "A.sol",
            "B.sol",
        ]
        assert (results / tool / "A.sol" / "result.json").exists()
        assert (results / tool / "B.sol" / "result.json").exists()
        assert len(completed.per_tool_findings[tool]) == 2
        assert completed.tool_statuses[tool].status == "SUCCESS"
    assert completed.tool_statuses["slither"].runtime_minutes == 1.5
    assert completed.tool_statuses["mythril"].runtime_minutes == 3.5
    assert len(completed.native_commands) == 4
    assert completed.per_tool_findings["slither"][0]["category"] == "access_control"
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
    assert fused.findings[0].category == "access_control"
    assert fused.findings[0].source_tools == ["slither", "mythril"]


def test_native_fallback_rejects_insufficient_explicit_jobs(tmp_path: Path) -> None:
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.4.25;\ncontract Token {}\n", encoding="utf-8")
    plan = ExecutionResult(
        status="planned",
        target_path=str(target),
        results_root=str(tmp_path / "results"),
        selected_tool_ids=["slither", "mythril"],
        primary_tool_id="slither",
        execution_schedule=ExecutionSchedule(
            execution_jobs=1,
            tool_timeout_seconds=321.0,
        ),
    )

    with pytest.raises(ValueError, match="one worker per selected tool"):
        execution._native_smartbugs_execute(plan)


def test_native_fallback_dispatches_creation_and_direct_runtime_inputs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "bytecode"
    target.mkdir()
    (target / "Deploy.bin").write_text("0x6000\n", encoding="utf-8")
    (target / "Live.runtime").write_text("6001", encoding="utf-8")
    results = tmp_path / "results"
    _configure_smartbugs(tmp_path, monkeypatch)
    calls: list[tuple[str, bool]] = []

    def fake_run(command, *, timeout_seconds, **kwargs):
        input_path = Path(command[command.index("-f") + 1])
        calls.append((input_path.name, "--runtime" in command))
        assert input_path.suffix == ".hex"
        assert input_path.read_text(encoding="utf-8") in {"6000", "6001"}
        staged = Path(command[command.index("--results") + 1])
        _write_report(staged / "result.json", input_path.name)
        return DeadlineProcessResult(returncode=0, elapsed_seconds=1.0)

    monkeypatch.setattr(execution, "run_process_with_deadline", fake_run)
    plan = ExecutionResult(
        status="planned",
        target_path=str(target),
        results_root=str(results),
        selected_tool_ids=["mythril"],
        primary_tool_id="mythril",
        execution_schedule=ExecutionSchedule(tool_timeout_seconds=13.0),
    )

    completed = execution._native_smartbugs_execute(plan)

    assert completed.status == "executed"
    assert calls == [("Deploy.hex", False), ("Live.rt.hex", True)]
    assert (results / "mythril" / "Deploy.bin" / "result.json").is_file()
    assert (results / "mythril" / "Live.runtime" / "result.json").is_file()
    statuses = json.loads(
        (results / "tool_run_statuses.json").read_text(encoding="utf-8")
    )
    assert statuses["mythril"]["status"] == "SUCCESS"


def test_native_fallback_resolves_smartbugs_from_runner_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "Deploy.bin"
    target.write_text("6000", encoding="utf-8")
    smartbugs = tmp_path / "smartbugs-from-env"
    smartbugs.mkdir()
    results = tmp_path / "results"
    seen_cwd: list[Path] = []

    def fake_run(command, *, cwd, **kwargs):
        seen_cwd.append(Path(cwd))
        staged = Path(command[command.index("--results") + 1])
        _write_report(staged / "result.json", "Deploy.hex")
        return DeadlineProcessResult(returncode=0, elapsed_seconds=1.0)

    monkeypatch.setattr(execution, "DEFAULT_SMARTBUGS_DIR", None)
    monkeypatch.setattr(execution, "run_process_with_deadline", fake_run)
    plan = ExecutionResult(
        status="planned",
        target_path=str(target),
        results_root=str(results),
        selected_tool_ids=["mythril"],
        primary_tool_id="mythril",
        execution_schedule=ExecutionSchedule(tool_timeout_seconds=13.0),
    )

    completed = execution._native_smartbugs_execute(
        plan,
        runner_env={"LAKES_SMARTBUGS_DIR": str(smartbugs)},
    )

    assert completed.status == "executed"
    assert seen_cwd == [smartbugs.resolve()]
