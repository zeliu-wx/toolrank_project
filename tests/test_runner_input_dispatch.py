from __future__ import annotations

import json
from pathlib import Path

from toolrank import runner
from toolrank.adapter_capabilities import adapter_supports_input


def _write_report(path: Path, filename: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "result.json").write_text(
        json.dumps({"errors": [], "fails": [], "findings": [{"name": "tx-origin", "filename": filename}]}),
        encoding="utf-8",
    )


def test_adapter_capabilities_match_pinned_smartbugs_modes() -> None:
    assert adapter_supports_input("mythril", "bytecode")
    assert adapter_supports_input("maian", "bytecode")
    assert adapter_supports_input("vulhunter", "bytecode")
    assert adapter_supports_input("oyente", "runtime")
    assert adapter_supports_input("vandal", "runtime")
    assert not adapter_supports_input("slither", "bytecode")
    assert not adapter_supports_input("vandal", "bytecode")


def test_directory_dispatches_source_roots_and_all_bytecode_kinds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "Lib.sol").write_text(
        "pragma solidity ^0.8.20; library Lib {}",
        encoding="utf-8",
    )
    (project / "Main.sol").write_text(
        'pragma solidity ^0.8.20; import "./Lib.sol"; contract Main {}',
        encoding="utf-8",
    )
    (project / "deploy.bin").write_text("6000", encoding="utf-8")
    (project / "deployed.runtime.hex").write_text("6001", encoding="utf-8")
    (project / "direct.runtime").write_text("6002", encoding="utf-8")
    calls: list[tuple[str, str]] = []

    def fake_adapter(tool_id, contract_path, out_dir, **kwargs):
        calls.append((Path(contract_path).name, kwargs["input_kind"]))
        _write_report(Path(out_dir), Path(contract_path).name)
        return 0

    monkeypatch.setattr(runner, "_run_adapter_with_deadline", fake_adapter)

    rc = runner.run_targets(
        project,
        tmp_path / "results",
        ["mythril"],
        write_lakes_output=False,
    )

    assert rc == 0
    assert calls == [
        ("Main.sol", "sol"),
        ("deploy.bin", "bytecode"),
        ("deployed.runtime.hex", "runtime"),
        ("direct.runtime", "runtime"),
    ]
    assert all(name != "Lib.sol" for name, _kind in calls)


def test_directory_input_discovery_ignores_file_symlinks(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside_source = tmp_path / "Outside.sol"
    outside_bytecode = tmp_path / "Outside.bin"
    outside_source.write_text("contract Outside {}", encoding="utf-8")
    outside_bytecode.write_text("6000", encoding="utf-8")
    (project / "Outside.sol").symlink_to(outside_source)
    (project / "Outside.bin").symlink_to(outside_bytecode)

    assert runner._discover_target_inputs(project) == []


def test_generic_smartbugs_dispatch_normalizes_bin_and_marks_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    smartbugs = tmp_path / "smartbugs"
    smartbugs.mkdir()
    commands: list[tuple[list[str], dict[str, str] | None]] = []

    def fake_stream(command, cwd=None, env=None, **kwargs):
        commands.append((command, env))
        input_path = Path(command[command.index("-f") + 1])
        assert input_path.suffix == ".hex"
        assert input_path.read_text(encoding="utf-8") in {"6000", "6001"}
        return 0

    monkeypatch.setattr(runner, "_stream_process", fake_stream)
    deployment = tmp_path / "deploy.bin"
    runtime = tmp_path / "deploy.runtime.bin"
    deployment.write_text("0x6000\n", encoding="utf-8")
    runtime.write_text("6001", encoding="utf-8")

    assert runner._run_smartbugs_tool(
        "mythril",
        deployment,
        tmp_path / "out1",
        target_root=tmp_path,
        smartbugs_dir=smartbugs,
        timeout=10,
        gptscan_timeout=10,
        openai_api_key="",
        openai_api_base="",
        input_kind="bytecode",
    ) == 0
    assert runner._run_smartbugs_tool(
        "mythril",
        runtime,
        tmp_path / "out2",
        target_root=tmp_path,
        smartbugs_dir=smartbugs,
        timeout=10,
        gptscan_timeout=10,
        openai_api_key="",
        openai_api_base="",
        input_kind="runtime",
    ) == 0

    assert "--runtime" not in commands[0][0]
    assert "--runtime" in commands[1][0]


def test_slither_08_uses_generic_smartbugs_project_bridge(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.8.20; contract Token {}", encoding="utf-8")
    smartbugs = tmp_path / "smartbugs"
    smartbugs.mkdir()
    package = smartbugs / "sb"
    package.mkdir()
    for name in ("cli.py", "docker.py"):
        (package / name).write_text("# test sentinel\n", encoding="utf-8")
    seen: dict = {}

    def fake_stream(command, cwd=None, env=None, **kwargs):
        seen.update(command=command, cwd=cwd, env=env)
        return 0

    monkeypatch.setattr(runner, "_stream_process", fake_stream)

    rc = runner._run_smartbugs_tool(
        "slither",
        target,
        tmp_path / "out",
        target_root=tmp_path,
        smartbugs_dir=smartbugs,
        timeout=10,
        gptscan_timeout=10,
        openai_api_key="",
        openai_api_base="",
        input_kind="sol",
    )

    assert rc == 0
    assert seen["command"][seen["command"].index("-t") + 1] == "slither"
    assert seen["env"]["LAKES_PROJECT_ROOT"] == str(tmp_path.resolve())
    assert str(Path(runner.__file__).resolve().parents[1]) in seen["env"]["PYTHONPATH"]
    assert "smartbugs_project.py" in " ".join(seen["command"])


def test_project_source_fails_closed_without_smartbugs_python_api(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    target = project / "Token.sol"
    target.write_text("contract Token {}", encoding="utf-8")
    smartbugs = tmp_path / "smartbugs"
    smartbugs.mkdir()
    monkeypatch.setattr(
        runner,
        "_stream_process",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("missing bridge API must fail before analyzer launch")
        ),
    )

    rc = runner._run_smartbugs_tool(
        "slither",
        target,
        tmp_path / "out",
        target_root=project,
        smartbugs_dir=smartbugs,
        timeout=10,
        gptscan_timeout=10,
        openai_api_key="",
        openai_api_base="",
        input_kind="sol",
    )

    assert rc != 0


def test_special_source_only_adapter_fails_closed_for_bytecode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "contract.bin"
    target.write_text("6000", encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "_run_gptscan",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    rc = runner._run_smartbugs_tool(
        "gptscan",
        target,
        tmp_path / "out",
        target_root=tmp_path,
        smartbugs_dir=tmp_path / "smartbugs",
        timeout=10,
        gptscan_timeout=10,
        openai_api_key="",
        openai_api_base="",
        input_kind="bytecode",
    )
    assert rc != 0


def test_generic_unsupported_mode_fails_before_smartbugs_launch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "contract.bin"
    target.write_text("6000", encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "_stream_process",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("unsupported mode must not launch SmartBugs")
        ),
    )

    rc = runner._run_smartbugs_tool(
        "slither",
        target,
        tmp_path / "out",
        target_root=target,
        smartbugs_dir=tmp_path / "smartbugs",
        timeout=10,
        gptscan_timeout=10,
        openai_api_key="",
        openai_api_base="",
        input_kind="bytecode",
    )

    assert rc == runner.UNSUPPORTED_INPUT_RETURN_CODE


def test_gptscan_scans_a_multi_root_project_only_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    for name in ("A.sol", "B.sol"):
        (project / name).write_text(
            f"pragma solidity ^0.8.20; contract {name[0]} {{}}",
            encoding="utf-8",
        )
    calls: list[tuple[str, str]] = []

    def fake_adapter(tool_id, contract_path, out_dir, **kwargs):
        calls.append((tool_id, Path(contract_path).name))
        _write_report(Path(out_dir), Path(contract_path).name)
        return 0

    monkeypatch.setattr(runner, "_run_adapter_with_deadline", fake_adapter)

    rc = runner.run_targets(
        project,
        tmp_path / "results",
        ["gptscan", "slither"],
        primary_tool="gptscan",
        write_lakes_output=False,
    )

    assert rc == 0
    assert [call for call in calls if call[0] == "gptscan"] == [
        ("gptscan", "A.sol")
    ]
    assert [call for call in calls if call[0] == "slither"] == [
        ("slither", "A.sol"),
        ("slither", "B.sol"),
    ]


def test_gptscan_stages_only_safe_solidity_project_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    (project / "contracts").mkdir(parents=True)
    (project / "lib").mkdir()
    main = project / "contracts" / "Main.sol"
    main.write_text(
        'pragma solidity ^0.8.20; import "../lib/Lib.sol"; contract Main {}',
        encoding="utf-8",
    )
    (project / "lib" / "Lib.sol").write_text(
        "pragma solidity ^0.8.20; library Lib {}",
        encoding="utf-8",
    )
    (project / ".env").write_text("SECRET=do-not-stage", encoding="utf-8")
    (project / "notes.txt").write_text("not source", encoding="utf-8")
    monkeypatch.setattr(runner, "_run_solc_select", lambda *args, **kwargs: True)

    def fake_stream(command, *, env, **kwargs):
        staged = Path(env["LAKES_GPTSCAN_SOURCE"])
        assert (staged / "contracts" / "Main.sol").is_file()
        assert (staged / "lib" / "Lib.sol").is_file()
        assert not (staged / ".env").exists()
        assert not (staged / "notes.txt").exists()
        Path(env["LAKES_GPTSCAN_OUTPUT"]).write_text(
            json.dumps({"success": True, "results": []}),
            encoding="utf-8",
        )
        return 0

    monkeypatch.setattr(runner, "_stream_process", fake_stream)

    assert runner._run_gptscan(
        main,
        tmp_path / "out",
        "",
        7,
        "",
        target_root=project,
    ) == 0
