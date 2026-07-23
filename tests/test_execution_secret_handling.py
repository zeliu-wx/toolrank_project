from __future__ import annotations

import io
import json
from pathlib import Path
import sys

from toolrank import execution, runner
from toolrank.execution import build_execution_plan, execute_plan
from toolrank.schemas import CompositionPlan, ExecutionSchedule


_SENTINEL = "sk-SENTINEL-MUST-NEVER-BE-PERSISTED"


def _composition() -> CompositionPlan:
    return CompositionPlan(
        selected_tool_ids=["slither"],
        primary_tool_id="slither",
        complementary_tool_ids=[],
    )


def test_secret_is_ephemeral_environment_not_serialized_plan_or_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.4.25; contract Token {}", encoding="utf-8")
    plan = build_execution_plan(
        target,
        tmp_path / "results",
        _composition(),
        runner_script=tmp_path / "runner.py",
    )
    captured: dict = {}

    def fake_stream(command, *, cwd, env):
        captured["command"] = command
        captured["env"] = env
        return 1, None, "runner failed without secret"

    monkeypatch.setattr(execution, "_stream_runner_output", fake_stream)
    result = execute_plan(
        plan,
        runner_env={
            "OPENAI_API_KEY": _SENTINEL,
            "OPENAI_API_BASE": "https://example.invalid",
        },
    )
    persisted = tmp_path / "execution.json"
    persisted.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    assert captured["env"]["OPENAI_API_KEY"] == _SENTINEL
    assert _SENTINEL not in " ".join(captured["command"])
    assert _SENTINEL not in plan.model_dump_json()
    assert _SENTINEL not in json.dumps(plan.model_dump())
    assert _SENTINEL not in result.model_dump_json()
    assert _SENTINEL not in persisted.read_text(encoding="utf-8")


def test_runner_subprocess_argv_and_log_tails_redact_secret(
    monkeypatch,
    capsys,
) -> None:
    captured: dict = {}

    class FakeProcess:
        def __init__(self):
            self.stdout = io.StringIO(f"stdout {_SENTINEL}\n")
            self.stderr = io.StringIO(f"stderr {_SENTINEL}\n")

        def wait(self):
            return 1

    def fake_popen(command, **kwargs):
        captured["argv"] = command
        captured["env"] = kwargs["env"]
        return FakeProcess()

    monkeypatch.setattr(execution.subprocess, "Popen", fake_popen)
    rc, stdout_tail, stderr_tail = execution._stream_runner_output(
        ["python", "runner.py"],
        cwd=None,
        env={"OPENAI_API_KEY": _SENTINEL},
    )

    rendered = capsys.readouterr()
    assert rc == 1
    assert captured["env"]["OPENAI_API_KEY"] == _SENTINEL
    assert _SENTINEL not in " ".join(captured["argv"])
    assert _SENTINEL not in (stdout_tail or "")
    assert _SENTINEL not in (stderr_tail or "")
    assert _SENTINEL not in rendered.out
    assert _SENTINEL not in rendered.err


def test_gptscan_os_argv_is_secret_free_but_wrapper_receives_key_in_memory(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    fake_main = tmp_path / "gptscan" / "src" / "main.py"
    fake_main.parent.mkdir(parents=True)
    argv_capture = tmp_path / "inner_argv.json"
    fake_main.write_text(
        "import json, os, sys\n"
        "open(os.environ['GPTSCAN_ARGV_CAPTURE'], 'w').write(json.dumps(sys.argv))\n"
        "print(os.environ['OPENAI_API_KEY'])\n"
        "out = sys.argv[sys.argv.index('-o') + 1]\n"
        "open(out, 'w').write(json.dumps({'success': True, 'results': []}))\n",
        encoding="utf-8",
    )
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.8.20; contract Token {}", encoding="utf-8")
    out_dir = tmp_path / "out"
    monkeypatch.setattr(runner, "GPTSCAN_MAIN", fake_main)
    monkeypatch.setattr(runner, "GPTSCAN_PY", Path(sys.executable))
    monkeypatch.setattr(runner, "_run_solc_select", lambda *args, **kwargs: True)
    monkeypatch.setenv("GPTSCAN_ARGV_CAPTURE", str(argv_capture))
    actual: dict = {}
    original_stream = runner._stream_process

    def spy_stream(command, **kwargs):
        actual["argv"] = list(command)
        actual["env"] = kwargs["env"]
        return original_stream(command, **kwargs)

    monkeypatch.setattr(runner, "_stream_process", spy_stream)

    rc = runner._run_gptscan(
        target,
        out_dir,
        _SENTINEL,
        7,
        "https://example.invalid",
    )

    rendered = capsys.readouterr()
    inner_argv = json.loads(argv_capture.read_text(encoding="utf-8"))
    assert rc == 0
    assert actual["env"]["OPENAI_API_KEY"] == _SENTINEL
    assert _SENTINEL not in " ".join(actual["argv"])
    assert _SENTINEL in inner_argv
    assert _SENTINEL not in rendered.out
    assert _SENTINEL not in rendered.err
    assert json.loads((out_dir / "result.json").read_text(encoding="utf-8"))[
        "findings"
    ] == []


def test_direct_runner_help_has_no_secret_forwarding_flags() -> None:
    help_text = runner.build_parser().format_help()

    assert "openai_api_key" not in help_text
    assert "openai_api_base" not in help_text


def test_real_generic_analyzer_process_cannot_inherit_openai_secrets(
    tmp_path: Path,
) -> None:
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.4.25; contract Token {}", encoding="utf-8")
    smartbugs_dir = tmp_path / "smartbugs"
    smartbugs_dir.mkdir()
    analyzer = smartbugs_dir / "smartbugs"
    analyzer.write_text(
        "#!/bin/sh\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  if [ \"$1\" = \"--results\" ]; then shift; OUT=$1; fi\n"
        "  shift\n"
        "done\n"
        "SEEN=\"${OPENAI_API_KEY-}|${OPENAI_API_TOKEN-}|${OPENAI_API_BASE-}|${OPENAI_BASE_URL-}\"\n"
        "printf 'probe=%s\\n' \"$SEEN\"\n"
        "mkdir -p \"$OUT\"\n"
        "printf '{\"findings\":[{\"name\":\"env-probe\",\"message\":\"%s\"}]}' \"$SEEN\" > \"$OUT/result.json\"\n",
        encoding="utf-8",
    )
    analyzer.chmod(0o755)
    results = tmp_path / "results"
    composition = CompositionPlan(
        selected_tool_ids=["mythril"],
        primary_tool_id="mythril",
        complementary_tool_ids=[],
        execution_schedule=ExecutionSchedule(tool_timeout_seconds=10.0),
    )
    plan = build_execution_plan(
        target,
        results,
        composition,
        runner_script=Path(runner.__file__),
    )

    completed = execute_plan(
        plan,
        runner_env={
            "OPENAI_API_KEY": _SENTINEL,
            "OPENAI_API_TOKEN": _SENTINEL,
            "OPENAI_API_BASE": f"https://{_SENTINEL}@example.invalid",
            "OPENAI_BASE_URL": f"https://{_SENTINEL}@example.invalid",
            "LAKES_SMARTBUGS_DIR": str(smartbugs_dir),
        },
    )
    run_dir = results / "LAKES_out" / "Token"
    execution_json = run_dir / "execution.json"
    execution_json.write_text(completed.model_dump_json(indent=2), encoding="utf-8")
    persisted = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(results.rglob("*"))
        if path.is_file()
    )

    assert completed.status == "executed"
    assert _SENTINEL not in (completed.stdout_tail or "")
    assert _SENTINEL not in (completed.stderr_tail or "")
    assert _SENTINEL not in persisted
    raw = json.loads(
        (run_dir / "raw" / "mythril" / "result.json").read_text(encoding="utf-8")
    )
    assert raw["findings"][0]["message"] == "|||"
    fused = json.loads((run_dir / "fused_report.json").read_text(encoding="utf-8"))
    assert _SENTINEL not in json.dumps(fused)
