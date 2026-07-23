from __future__ import annotations

import json
from pathlib import Path

import pytest

from toolrank import execution, report_validity, runner
from toolrank.process_deadline import DeadlineProcessResult
from toolrank.report_validity import find_valid_report
from toolrank.schemas import ExecutionResult, ExecutionSchedule


_CASES = [
    ("nonzero", 2, False, '{"findings": [{"name": "must-not-harvest"}]}', False),
    ("timeout", 124, True, '{"findings": [{"name": "must-not-harvest"}]}', False),
    ("missing", 0, False, None, False),
    ("empty_object", 0, False, "{}", False),
    ("malformed", 0, False, "{not-json", False),
    ("valid_empty", 0, False, '{"findings": []}', True),
    (
        "valid_findings",
        0,
        False,
        '{"findings": [{"name": "tx-origin", "filename": "Token.sol", "line": 7}]}',
        True,
    ),
]


def _write_staged_report(root: Path, content: str | None) -> None:
    if content is None:
        return
    root.mkdir(parents=True, exist_ok=True)
    (root / "result.json").write_text(content, encoding="utf-8")


def _configure_smartbugs(tmp_path: Path, monkeypatch) -> Path:
    smartbugs = tmp_path / "smartbugs"
    package = smartbugs / "sb"
    package.mkdir(parents=True)
    for name in ("cli.py", "docker.py"):
        (package / name).write_text("# test sentinel\n", encoding="utf-8")
    monkeypatch.setattr(execution, "DEFAULT_SMARTBUGS_DIR", smartbugs)
    return smartbugs


@pytest.mark.parametrize(
    ("case", "process_rc", "timed_out", "content", "valid"),
    _CASES,
)
def test_normal_invocation_promotes_only_valid_current_run_reports(
    case: str,
    process_rc: int,
    timed_out: bool,
    content: str | None,
    valid: bool,
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fake_process(command, **kwargs):
        request = json.loads(kwargs["input_text"])
        _write_staged_report(Path(request["out_dir"]), content)
        return DeadlineProcessResult(
            returncode=process_rc,
            timed_out=timed_out,
            elapsed_seconds=0.1,
        )

    monkeypatch.setattr(runner, "run_process_with_deadline", fake_process)
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.4.25; contract Token {}", encoding="utf-8")
    final_dir = tmp_path / "final" / case

    rc = runner._run_adapter_with_deadline(
        "slither",
        target,
        final_dir,
        target_root=target,
        smartbugs_dir=tmp_path / "smartbugs",
        timeout=13,
        gptscan_timeout=7,
        openai_api_key="",
        openai_api_base="",
        mapping={},
        quarantine_root=tmp_path / ".quarantine",
    )

    assert rc == (0 if valid else (124 if timed_out else process_rc or 1))
    assert final_dir.exists() is valid
    assert (find_valid_report(final_dir) is not None) is valid


def test_normal_enrichment_failure_leaves_no_final_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fake_process(command, **kwargs):
        request = json.loads(kwargs["input_text"])
        _write_staged_report(Path(request["out_dir"]), '{"findings": []}')
        return DeadlineProcessResult(returncode=0, elapsed_seconds=0.1)

    monkeypatch.setattr(runner, "run_process_with_deadline", fake_process)
    monkeypatch.setattr(runner, "_write_enriched_report", lambda *args: False)
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.4.25; contract Token {}", encoding="utf-8")
    final_dir = tmp_path / "final"

    rc = runner._run_adapter_with_deadline(
        "slither",
        target,
        final_dir,
        target_root=target,
        smartbugs_dir=tmp_path / "smartbugs",
        timeout=13,
        gptscan_timeout=7,
        openai_api_key="",
        openai_api_base="",
        mapping={},
        quarantine_root=tmp_path / ".quarantine",
    )

    assert rc == 1
    assert not final_dir.exists()


@pytest.mark.parametrize(
    ("case", "process_rc", "timed_out", "content", "valid"),
    _CASES,
)
def test_native_invocation_promotes_only_valid_current_run_reports(
    case: str,
    process_rc: int,
    timed_out: bool,
    content: str | None,
    valid: bool,
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.4.25; contract Token {}", encoding="utf-8")
    results = tmp_path / "results"
    _configure_smartbugs(tmp_path, monkeypatch)

    def fake_process(command, **kwargs):
        staged = Path(command[command.index("--results") + 1])
        _write_staged_report(staged, content)
        return DeadlineProcessResult(
            returncode=process_rc,
            timed_out=timed_out,
            elapsed_seconds=6.0,
        )

    monkeypatch.setattr(execution, "run_process_with_deadline", fake_process)
    plan = ExecutionResult(
        status="planned",
        target_path=str(target),
        results_root=str(results),
        selected_tool_ids=["slither"],
        primary_tool_id="slither",
        execution_schedule=ExecutionSchedule(tool_timeout_seconds=13.0),
    )

    completed = execution._native_smartbugs_execute(plan)
    final_dir = results / "slither" / "Token.sol"

    assert completed.status == ("executed" if valid else "failed")
    assert completed.tool_statuses["slither"].status == (
        "SUCCESS" if valid else "TIMEOUT" if timed_out else "FAIL"
    )
    assert final_dir.exists() is valid
    assert (find_valid_report(final_dir) is not None) is valid
    if not valid:
        assert completed.per_tool_findings.get("slither", []) == []
    elif case == "valid_findings":
        assert len(completed.per_tool_findings["slither"]) == 1


@pytest.mark.parametrize("fault", ["copytree", "replace"])
def test_promotion_filesystem_fault_returns_false_and_cleans_candidate(
    fault: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    staged = tmp_path / "staged"
    _write_staged_report(staged, '{"findings": []}')
    final = tmp_path / "final"

    def fail(*args, **kwargs):
        raise OSError(f"injected {fault} failure")

    if fault == "copytree":
        monkeypatch.setattr(report_validity.shutil, "copytree", fail)
    else:
        monkeypatch.setattr(report_validity.os, "replace", fail)

    assert report_validity.promote_valid_report_tree(
        staged,
        final,
        quarantine_root=tmp_path / ".quarantine",
    ) is False
    assert not final.exists()
    assert list(tmp_path.glob(".lakes_report_promotion_*")) == []


def test_promotion_cleanup_oserror_is_retried_without_losing_success(
    tmp_path: Path,
    monkeypatch,
) -> None:
    staged = tmp_path / "staged"
    _write_staged_report(staged, '{"findings": []}')
    final = tmp_path / "final"
    original_rmtree = report_validity.shutil.rmtree
    failures = 0

    def fail_once(path, *args, **kwargs):
        nonlocal failures
        if Path(path).name.startswith(".lakes_report_promotion_") and failures == 0:
            failures += 1
            raise OSError("injected cleanup failure")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(report_validity.shutil, "rmtree", fail_once)

    assert report_validity.promote_valid_report_tree(
        staged,
        final,
        quarantine_root=tmp_path / ".quarantine",
    ) is True
    assert find_valid_report(final) is not None
    assert list(tmp_path.glob(".lakes_report_promotion_*")) == []


def test_normal_copy_fault_marks_failure_without_final_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fake_process(command, **kwargs):
        request = json.loads(kwargs["input_text"])
        _write_staged_report(Path(request["out_dir"]), '{"findings": []}')
        return DeadlineProcessResult(returncode=0, elapsed_seconds=0.1)

    monkeypatch.setattr(runner, "run_process_with_deadline", fake_process)
    monkeypatch.setattr(
        report_validity.shutil,
        "copytree",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("copy fault")),
    )
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.4.25; contract Token {}", encoding="utf-8")
    final = tmp_path / "final"

    rc = runner._run_adapter_with_deadline(
        "slither",
        target,
        final,
        target_root=target,
        smartbugs_dir=tmp_path / "smartbugs",
        timeout=13,
        gptscan_timeout=7,
        openai_api_key="",
        openai_api_base="",
        mapping={},
        quarantine_root=tmp_path / ".quarantine",
    )

    assert rc == 1
    assert not final.exists()


def test_native_replace_fault_marks_failure_without_final_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.4.25; contract Token {}", encoding="utf-8")
    results = tmp_path / "results"
    _configure_smartbugs(tmp_path, monkeypatch)

    def fake_process(command, **kwargs):
        staged = Path(command[command.index("--results") + 1])
        _write_staged_report(staged, '{"findings": []}')
        return DeadlineProcessResult(returncode=0, elapsed_seconds=0.1)

    monkeypatch.setattr(execution, "run_process_with_deadline", fake_process)
    monkeypatch.setattr(
        report_validity.os,
        "replace",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("replace fault")),
    )
    plan = ExecutionResult(
        status="planned",
        target_path=str(target),
        results_root=str(results),
        selected_tool_ids=["slither"],
        primary_tool_id="slither",
        execution_schedule=ExecutionSchedule(tool_timeout_seconds=13.0),
    )

    completed = execution._native_smartbugs_execute(plan)

    assert completed.status == "failed"
    assert completed.tool_statuses["slither"].status == "FAIL"
    assert not (results / "slither" / "Token.sol").exists()
