from __future__ import annotations

import json
from pathlib import Path

import pytest

from toolrank import engine, execution, report_validity, runner
from toolrank.report_validity import OUTPUT_CLEANUP_FAILURE_RETURN_CODE
from toolrank.schemas import (
    CompositionPlan,
    ExecutionResult,
    ExecutionSchedule,
    ToolExecutionStatus,
)


def _write_report(path: Path, name: str = "stale") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "findings": [
                    {"name": name, "filename": "Token.sol", "line": 7}
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


def _plan(target: Path, results: Path) -> ExecutionResult:
    return ExecutionResult(
        status="planned",
        target_path=str(target),
        results_root=str(results),
        selected_tool_ids=["slither"],
        primary_tool_id="slither",
        runner_command=["python", "runner.py"],
        execution_schedule=ExecutionSchedule(tool_timeout_seconds=13.0),
    )


def test_cleanup_renames_stale_tree_outside_tool_scan_when_rmtree_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    results = tmp_path / "results"
    tool_dir = results / "slither"
    stale = tool_dir / "Old.sol" / "result.json"
    _write_report(stale)
    quarantine_root = results / ".lakes_quarantine_test"
    original_rmtree = report_validity.shutil.rmtree

    def fail_target_and_quarantine(path, *args, **kwargs):
        candidate = Path(path)
        if candidate == tool_dir or quarantine_root in candidate.parents:
            raise OSError("injected deletion failure")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(
        report_validity.shutil,
        "rmtree",
        fail_target_and_quarantine,
    )

    assert report_validity.remove_or_quarantine_tree(
        tool_dir,
        quarantine_root,
    )
    assert not tool_dir.exists()
    quarantined_reports = list(quarantine_root.rglob("result.json"))
    assert len(quarantined_reports) == 1
    assert all(tool_dir not in path.parents for path in quarantined_reports)


def test_cleanup_returns_false_when_delete_and_quarantine_move_both_fail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    results = tmp_path / "results"
    tool_dir = results / "slither"
    stale = tool_dir / "result.json"
    _write_report(stale)
    quarantine_root = results / ".lakes_quarantine_test"

    monkeypatch.setattr(
        report_validity.shutil,
        "rmtree",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("delete failed")),
    )
    monkeypatch.setattr(
        report_validity.os,
        "replace",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("rename failed")),
    )

    assert not report_validity.remove_or_quarantine_tree(
        tool_dir,
        quarantine_root,
    )
    assert stale.exists()


def test_atomic_final_write_failure_preserves_previous_complete_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "fused_report.json"
    artifact.write_text('{"generation":"previous"}\n', encoding="utf-8")
    monkeypatch.setattr(
        report_validity.os,
        "replace",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("replace failed")),
    )

    with pytest.raises(OSError, match="replace failed"):
        report_validity.atomic_write_text(
            artifact,
            '{"generation":"current"}\n',
        )

    assert artifact.read_text(encoding="utf-8") == '{"generation":"previous"}\n'
    assert list(tmp_path.glob(".fused_report.json.*.tmp")) == []


def test_normal_adapter_cleanup_failure_is_controlled_and_skips_analyzer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.4.25; contract Token {}", encoding="utf-8")
    results = tmp_path / "results"
    out_dir = results / "slither"
    _write_report(out_dir / "result.json")
    quarantine_root = results / ".lakes_quarantine_test"
    invoked = False

    def fake_process(*args, **kwargs):
        nonlocal invoked
        invoked = True
        raise AssertionError("analyzer must not run")

    monkeypatch.setattr(runner, "run_process_with_deadline", fake_process)
    monkeypatch.setattr(
        report_validity.shutil,
        "rmtree",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("delete failed")),
    )
    monkeypatch.setattr(
        report_validity.os,
        "replace",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("rename failed")),
    )

    rc = runner._run_adapter_with_deadline(
        "slither",
        target,
        out_dir,
        target_root=target,
        smartbugs_dir=tmp_path / "smartbugs",
        timeout=13,
        gptscan_timeout=7,
        openai_api_key="",
        openai_api_base="",
        mapping={},
        quarantine_root=quarantine_root,
    )

    assert rc == OUTPUT_CLEANUP_FAILURE_RETURN_CODE
    assert not invoked
    assert (out_dir / "result.json").exists()


def test_batch_cleanup_failure_is_controlled_and_skips_every_analyzer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.4.25; contract Token {}", encoding="utf-8")
    results = tmp_path / "results"
    stale = results / "slither" / "result.json"
    _write_report(stale)
    calls = 0

    def fake_adapter(*args, **kwargs):
        nonlocal calls
        calls += 1
        return 0

    monkeypatch.setattr(runner, "_run_adapter_with_deadline", fake_adapter)
    monkeypatch.setattr(
        report_validity.shutil,
        "rmtree",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("delete failed")),
    )
    monkeypatch.setattr(
        report_validity.os,
        "replace",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("rename failed")),
    )

    rc = runner.run_targets(
        target,
        results,
        ["slither"],
        primary_tool="slither",
        write_lakes_output=False,
    )

    assert rc == OUTPUT_CLEANUP_FAILURE_RETURN_CODE
    assert calls == 0
    assert stale.exists()


def test_native_selected_tool_cleanup_failure_skips_analyzer_and_harvest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.4.25; contract Token {}", encoding="utf-8")
    results = tmp_path / "results"
    stale = results / "slither" / "Old.sol" / "result.json"
    _write_report(stale)
    invoked = False
    _configure_smartbugs(tmp_path, monkeypatch)

    def fake_process(*args, **kwargs):
        nonlocal invoked
        invoked = True
        raise AssertionError("analyzer must not run")

    monkeypatch.setattr(execution, "run_process_with_deadline", fake_process)
    monkeypatch.setattr(
        report_validity.shutil,
        "rmtree",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("delete failed")),
    )
    monkeypatch.setattr(
        report_validity.os,
        "replace",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("rename failed")),
    )

    completed = execution._native_smartbugs_execute(_plan(target, results))

    assert completed.status == "failed"
    assert completed.return_code == OUTPUT_CLEANUP_FAILURE_RETURN_CODE
    assert completed.per_tool_findings == {}
    assert completed.tool_statuses["slither"].status == "FAIL"
    assert not invoked
    assert stale.exists()


def test_native_per_invocation_cleanup_failure_is_controlled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.4.25; contract Token {}", encoding="utf-8")
    results = tmp_path / "results"
    tool_dir = results / "slither"
    out_dir = tool_dir / "Token.sol"
    invoked = False
    _configure_smartbugs(tmp_path, monkeypatch)

    def fake_cleanup(path, quarantine_root):
        candidate = Path(path)
        if candidate == tool_dir:
            return True
        if candidate == out_dir:
            _write_report(out_dir / "result.json")
            return False
        raise AssertionError(f"unexpected cleanup path: {candidate}")

    def fake_process(*args, **kwargs):
        nonlocal invoked
        invoked = True
        raise AssertionError("analyzer must not run")

    monkeypatch.setattr(execution, "remove_or_quarantine_tree", fake_cleanup)
    monkeypatch.setattr(execution, "run_process_with_deadline", fake_process)

    completed = execution._native_smartbugs_execute(_plan(target, results))

    assert completed.status == "failed"
    assert completed.return_code == OUTPUT_CLEANUP_FAILURE_RETURN_CODE
    assert completed.per_tool_findings == {}
    assert not invoked


def test_promotion_quarantines_old_final_before_candidate_replace_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    results = tmp_path / "results"
    tool_dir = results / "slither"
    final = tool_dir / "Token.sol"
    staged = tmp_path / "staged"
    _write_report(final / "result.json", "stale")
    _write_report(staged / "result.json", "fresh")
    quarantine_root = results / ".lakes_quarantine_test"
    original_replace = report_validity.os.replace
    original_rmtree = report_validity.shutil.rmtree

    def fail_selected_and_quarantine_deletion(path, *args, **kwargs):
        candidate = Path(path)
        if candidate == final or quarantine_root in candidate.parents:
            raise OSError("injected deletion failure")
        return original_rmtree(path, *args, **kwargs)

    def quarantine_then_fail_candidate(source, destination):
        if Path(source) == final:
            return original_replace(source, destination)
        raise OSError("injected candidate replace failure")

    monkeypatch.setattr(
        report_validity.shutil,
        "rmtree",
        fail_selected_and_quarantine_deletion,
    )
    monkeypatch.setattr(report_validity.os, "replace", quarantine_then_fail_candidate)

    assert not report_validity.promote_valid_report_tree(
        staged,
        final,
        quarantine_root=quarantine_root,
    )
    assert not final.exists()
    quarantined_reports = list(quarantine_root.rglob("result.json"))
    assert quarantined_reports
    assert all(tool_dir not in path.parents for path in quarantined_reports)


def test_cleanup_failure_return_code_prevents_outer_harvest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.4.25; contract Token {}", encoding="utf-8")
    results = tmp_path / "results"
    _write_report(results / "slither" / "result.json")
    plan = _plan(target, results)

    monkeypatch.setattr(
        execution,
        "_stream_runner_output",
        lambda *args, **kwargs: (
            OUTPUT_CLEANUP_FAILURE_RETURN_CODE,
            None,
            "output cleanup failed",
        ),
    )

    completed = execution.execute_plan(plan)

    assert completed.status == "failed"
    assert completed.return_code == OUTPUT_CLEANUP_FAILURE_RETURN_CODE
    assert completed.per_tool_findings == {}
    assert completed.tool_statuses["slither"].status == "FAIL"


def test_cleanup_failure_prevents_engine_fallback_fusion_of_stale_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.4.25; contract Token {}", encoding="utf-8")
    composition = CompositionPlan(
        selected_tool_ids=["slither"],
        primary_tool_id="slither",
        complementary_tool_ids=[],
    )
    outputs = tmp_path / "outputs"
    raw_root = outputs / "LAKES_out" / "Token" / "raw"
    selected_stale = raw_root / "slither" / "result.json"
    unselected_report = raw_root / "osiris" / "result.json"
    _write_report(selected_stale)
    _write_report(unselected_report, "unselected")

    def fake_execute(plan, **kwargs):
        assert Path(plan.results_root) == raw_root
        assert selected_stale.exists()
        assert unselected_report.exists()
        return plan.model_copy(
            update={
                "status": "failed",
                "return_code": OUTPUT_CLEANUP_FAILURE_RETURN_CODE,
                "per_tool_findings": {},
                "tool_statuses": {
                    "slither": ToolExecutionStatus(
                        status="FAIL",
                        return_code=OUTPUT_CLEANUP_FAILURE_RETURN_CODE,
                        detail="output cleanup failed",
                    )
                },
            }
        )

    monkeypatch.setattr(engine, "execute_plan", fake_execute)

    completed, fused, _output_dir = engine._run_execution_pipeline(
        target_path=target,
        composition=composition,
        results_root=outputs,
        runner_script=Path(runner.__file__),
        runner_cwd=None,
        gptscan_timeout_sec=7,
        openai_api_key=None,
        openai_api_base=None,
    )

    assert completed.status == "failed"
    assert completed.return_code == OUTPUT_CLEANUP_FAILURE_RETURN_CODE
    assert completed.per_tool_findings == {}
    assert fused.findings == []
    assert selected_stale.exists()
    assert unselected_report.exists()


def test_engine_invalidates_previous_canonical_result_before_runner_start(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.4.25; contract Token {}", encoding="utf-8")
    outputs = tmp_path / "outputs"
    output_dir = report_validity.canonical_contract_output_dir(outputs, target)
    output_dir.mkdir(parents=True)
    for filename in report_validity.CANONICAL_FINAL_ARTIFACTS:
        (output_dir / filename).write_text("stale generation", encoding="utf-8")

    monkeypatch.setattr(
        engine,
        "execute_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("runner startup failed")
        ),
    )

    with pytest.raises(RuntimeError, match="runner startup failed"):
        engine._run_execution_pipeline(
            target_path=target,
            composition=CompositionPlan(
                selected_tool_ids=["slither"],
                primary_tool_id="slither",
                complementary_tool_ids=[],
            ),
            results_root=outputs,
            runner_script=Path(runner.__file__),
            runner_cwd=None,
            gptscan_timeout_sec=7,
            openai_api_key=None,
            openai_api_base=None,
        )

    assert output_dir == outputs / "LAKES_out" / "Token"
    assert all(
        not (output_dir / filename).exists()
        for filename in report_validity.CANONICAL_FINAL_ARTIFACTS
    )


def test_runner_canonical_cleanup_failure_stops_before_analyzer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.4.25; contract Token {}", encoding="utf-8")
    calls = 0

    def fake_adapter(*args, **kwargs):
        nonlocal calls
        calls += 1
        return 0

    monkeypatch.setattr(runner, "_run_adapter_with_deadline", fake_adapter)
    monkeypatch.setattr(runner, "clear_canonical_final_artifacts", lambda _path: False)

    rc = runner.run_targets(
        target,
        tmp_path / "outputs",
        ["slither"],
        primary_tool="slither",
    )

    assert rc == OUTPUT_CLEANUP_FAILURE_RETURN_CODE
    assert calls == 0
