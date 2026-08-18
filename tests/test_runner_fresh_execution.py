import json
from pathlib import Path

import pytest

from toolrank import runner


def _write_report(path: Path, finding_name: str, filename: str = "Token.sol") -> None:
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


def test_ancestor_smartbugsout_report_cannot_bypass_analyzer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "project" / "Token.sol"
    target.parent.mkdir()
    target.write_text("pragma solidity ^0.4.25;\ncontract Token {}\n", encoding="utf-8")
    _write_report(tmp_path / "smartbugsout" / "slither" / "Token.json", "reentrancy-eth")

    calls: list[Path] = []

    def fake_run_tool(tool_id, contract_path, out_dir, **kwargs):
        calls.append(out_dir)
        _write_report(out_dir / "result.json", "tx-origin")
        return 0

    monkeypatch.setattr(runner, "_run_adapter_with_deadline", fake_run_tool)

    results = tmp_path / "results"
    rc = runner.run_targets(
        target,
        results,
        ["slither"],
        primary_tool="slither",
        write_lakes_output=False,
    )

    assert rc == 0
    assert calls == [results.resolve() / "slither"]
    report = json.loads((results / "slither" / "result.json").read_text(encoding="utf-8"))
    assert report["findings"][0]["raw_name"] == "tx-origin"


def test_stale_report_in_output_dir_cannot_bypass_analyzer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.4.25;\ncontract Token {}\n", encoding="utf-8")
    results = tmp_path / "results"
    stale_report = results / "slither" / "result.json"
    _write_report(stale_report, "reentrancy-eth")

    calls: list[Path] = []

    def fake_run_tool(tool_id, contract_path, out_dir, **kwargs):
        calls.append(out_dir)
        assert not stale_report.exists()
        _write_report(out_dir / "result.json", "tx-origin")
        return 0

    monkeypatch.setattr(runner, "_run_adapter_with_deadline", fake_run_tool)

    rc = runner.run_targets(
        target,
        results,
        ["slither"],
        primary_tool="slither",
        write_lakes_output=False,
    )

    assert rc == 0
    assert calls == [results.resolve() / "slither"]
    report = json.loads(stale_report.read_text(encoding="utf-8"))
    assert report["findings"][0]["raw_name"] == "tx-origin"


def test_root_legacy_reports_and_status_manifest_are_cleared_before_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.8.20; contract Token {}", encoding="utf-8")
    results = tmp_path / "results"
    results.mkdir()
    (results / "slither.json").write_text(
        '{"findings": [{"name": "stale", "filename": "Old.sol"}]}',
        encoding="utf-8",
    )
    (results / "slither.sarif").write_text('{"runs": []}', encoding="utf-8")
    (results / "tool_run_statuses.json").write_text(
        '{"slither": {"status": "SUCCESS"}}', encoding="utf-8"
    )

    def fail_current_run(tool_id, contract_path, out_dir, **kwargs):
        assert not (results / "slither.json").exists()
        assert not (results / "slither.sarif").exists()
        assert not (results / "tool_run_statuses.json").exists()
        return 2

    monkeypatch.setattr(runner, "_run_adapter_with_deadline", fail_current_run)

    rc = runner.run_targets(
        target,
        results,
        ["slither"],
        primary_tool="slither",
        write_lakes_output=False,
    )

    assert rc == 2
    assert not (results / "slither.json").exists()
    assert not (results / "slither.sarif").exists()
    statuses = json.loads((results / "tool_run_statuses.json").read_text(encoding="utf-8"))
    assert statuses["slither"]["status"] == "FAIL"


def test_fresh_analyzer_report_is_enriched_and_fused(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.4.25;\ncontract Token {}\n", encoding="utf-8")

    def fake_run_tool(tool_id, contract_path, out_dir, **kwargs):
        _write_report(out_dir / "result.json", "tx-origin")
        return 0

    monkeypatch.setattr(runner, "_run_adapter_with_deadline", fake_run_tool)

    results = tmp_path / "results"
    rc = runner.run_targets(target, results, ["slither"], primary_tool="slither")

    assert rc == 0
    run_dir = results / "LAKES_out" / "Token"
    report = json.loads((run_dir / "raw" / "slither" / "result.json").read_text(encoding="utf-8"))
    assert report["findings"][0]["category"] == "access_control"
    assert report["findings"][0]["raw_name"] == "tx-origin"
    fused = json.loads((run_dir / "fused_report.json").read_text(encoding="utf-8"))
    assert fused["findings"][0]["source_tools"] == ["slither"]
    assert fused["findings"][0]["category"] == "access_control"


def test_lakes_named_symlink_root_does_not_create_a_second_lakes_tree(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.4.25; contract Token {}\n", encoding="utf-8")
    physical_root = tmp_path / "physical-output"
    physical_root.mkdir()
    requested_root = tmp_path / "LAKES_out"
    requested_root.symlink_to(physical_root, target_is_directory=True)

    def fake_run_tool(tool_id, contract_path, out_dir, **kwargs):
        _write_report(out_dir / "result.json", "tx-origin")
        return 0

    monkeypatch.setattr(runner, "_run_adapter_with_deadline", fake_run_tool)

    rc = runner.run_targets(
        target,
        requested_root,
        ["slither"],
        primary_tool="slither",
    )

    assert rc == 0
    expected = physical_root / "Token"
    assert (expected / "fused_report.json").is_file()
    assert (expected / "raw" / "slither" / "result.json").is_file()
    assert not (physical_root / "LAKES_out").exists()


def test_directory_target_removes_reports_for_deleted_contracts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "contracts"
    target.mkdir()
    current_contract = target / "New.sol"
    current_contract.write_text(
        "pragma solidity ^0.4.25;\ncontract New {}\n",
        encoding="utf-8",
    )
    results = tmp_path / "results"
    raw_root = results / "LAKES_out" / "contracts" / "raw"
    stale_report = raw_root / "slither" / "Old.sol" / "result.json"
    _write_report(stale_report, "reentrancy-eth", "Old.sol")
    unselected_report = raw_root / "osiris" / "Old.sol" / "result.json"
    _write_report(unselected_report, "overflow bugs", "Old.sol")

    calls: list[Path] = []

    def fake_run_tool(tool_id, contract_path, out_dir, **kwargs):
        calls.append(out_dir)
        assert not stale_report.exists()
        _write_report(out_dir / "result.json", "tx-origin", "New.sol")
        return 0

    monkeypatch.setattr(runner, "_run_adapter_with_deadline", fake_run_tool)

    rc = runner.run_targets(target, results, ["slither"], primary_tool="slither")

    assert rc == 0
    assert calls == [raw_root.resolve() / "slither" / "New.sol"]
    assert not stale_report.exists()
    assert unselected_report.exists()
    fused = json.loads(
        (results / "LAKES_out" / "contracts" / "fused_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert [finding["location"] for finding in fused["findings"]] == ["New.sol:7"]


def test_runner_records_and_aggregates_measured_runtime_across_solidity_files(
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

    def fake_run_tool(tool_id, contract_path, out_dir, **kwargs):
        _write_report(out_dir / "result.json", "tx-origin", contract_path.name)
        return 0

    timestamps = iter([0.0, 60.0, 100.0, 220.0])
    monkeypatch.setattr(runner, "_run_adapter_with_deadline", fake_run_tool)
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(timestamps))

    results = tmp_path / "results"
    rc = runner.run_targets(
        target,
        results,
        ["slither"],
        primary_tool="slither",
        write_lakes_output=False,
    )

    assert rc == 0
    statuses = json.loads(
        (results / "tool_run_statuses.json").read_text(encoding="utf-8")
    )
    assert statuses["slither"]["runtime_minutes"] == 3.0


def test_runner_rejects_jobs_cap_smaller_than_selected_tool_count(
    tmp_path: Path,
) -> None:
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.4.25;\ncontract Token {}\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        runner.run_targets(
            target,
            tmp_path / "results",
            ["slither", "mythril"],
            jobs=1,
            write_lakes_output=False,
        )

    assert exc_info.value.code == 2
