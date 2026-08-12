from __future__ import annotations

import io
import json
from pathlib import Path
import sys

from toolrank import execution, runner
from toolrank.execution import build_execution_plan, execute_plan
from toolrank.openai_compat import (
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
)
from toolrank.schemas import CompositionPlan, ExecutionSchedule


_SENTINEL = "sk-SENTINEL-MUST-NEVER-BE-PERSISTED"


def _clear_gptscan_llm_env(monkeypatch) -> None:
    for name in (
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENAI_API_BASE",
        "OPENAI_BASE_URL",
        "LAKES_GPTSCAN_DEFAULT_API_BASE",
        "TOOLRANK_GPTSCAN_DEFAULT_API_BASE",
        "GPTSCAN_MODEL_GPT4",
        "GPTSCAN_MODEL",
        "LAKES_GPTSCAN_DEFAULT_MODEL_GPT4",
        "TOOLRANK_GPTSCAN_DEFAULT_MODEL_GPT4",
        "LAKES_OPENAI_BASE_URL",
        "TOOLRANK_OPENAI_BASE_URL",
        "LAKES_OPENAI_MODEL",
        "TOOLRANK_OPENAI_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


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


def test_gptscan_llm_resolution_preserves_explicit_and_openai_precedence(
    monkeypatch,
) -> None:
    _clear_gptscan_llm_env(monkeypatch)
    monkeypatch.setattr(runner, "GPTSCAN_DEFAULT_API_BASE", DEFAULT_DEEPSEEK_BASE_URL)
    monkeypatch.setattr(runner, "GPTSCAN_DEFAULT_MODEL_GPT4", DEFAULT_DEEPSEEK_MODEL)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("TOOLRANK_OPENAI_BASE_URL", "https://toolrank.example/v1")
    monkeypatch.setenv("LAKES_OPENAI_BASE_URL", "https://lakes.example/v1")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openai-base.example/v1")
    monkeypatch.setenv("OPENAI_API_BASE", "https://openai-api.example/v1")
    monkeypatch.setenv(
        "LAKES_GPTSCAN_DEFAULT_API_BASE",
        "https://gptscan.example/v1",
    )
    monkeypatch.setenv("TOOLRANK_OPENAI_MODEL", "toolrank-model")
    monkeypatch.setenv("LAKES_OPENAI_MODEL", "lakes-model")
    monkeypatch.setenv("GPTSCAN_MODEL", "gptscan-model")
    monkeypatch.setenv("GPTSCAN_MODEL_GPT4", "gptscan-gpt4-model")
    monkeypatch.setenv("LAKES_GPTSCAN_DEFAULT_MODEL_GPT4", "gptscan-default-model")

    assert runner._resolve_gptscan_api_key("explicit-key") == "explicit-key"
    assert runner._resolve_gptscan_api_base("https://explicit.example/v1") == (
        "https://explicit.example/v1"
    )
    assert runner._resolve_gptscan_api_key("") == "openai-key"
    assert runner._resolve_gptscan_api_base("") == "https://openai-api.example/v1"
    assert runner._resolve_gptscan_model() == "gptscan-gpt4-model"

    monkeypatch.delenv("OPENAI_API_BASE")
    assert runner._resolve_gptscan_api_base("") == "https://openai-base.example/v1"
    monkeypatch.delenv("OPENAI_BASE_URL")
    assert runner._resolve_gptscan_api_base("") == "https://gptscan.example/v1"
    monkeypatch.delenv("LAKES_GPTSCAN_DEFAULT_API_BASE")
    assert runner._resolve_gptscan_api_base("") == "https://lakes.example/v1"
    monkeypatch.delenv("LAKES_OPENAI_BASE_URL")
    assert runner._resolve_gptscan_api_base("") == "https://toolrank.example/v1"

    monkeypatch.delenv("GPTSCAN_MODEL_GPT4")
    assert runner._resolve_gptscan_model() == "gptscan-model"
    monkeypatch.delenv("GPTSCAN_MODEL")
    assert runner._resolve_gptscan_model() == "gptscan-default-model"
    monkeypatch.delenv("LAKES_GPTSCAN_DEFAULT_MODEL_GPT4")
    assert runner._resolve_gptscan_model() == "lakes-model"
    monkeypatch.delenv("LAKES_OPENAI_MODEL")
    assert runner._resolve_gptscan_model() == "toolrank-model"


def test_gptscan_deepseek_key_only_uses_official_defaults(monkeypatch) -> None:
    _clear_gptscan_llm_env(monkeypatch)
    monkeypatch.setattr(runner, "GPTSCAN_DEFAULT_API_BASE", DEFAULT_DEEPSEEK_BASE_URL)
    monkeypatch.setattr(runner, "GPTSCAN_DEFAULT_MODEL_GPT4", DEFAULT_DEEPSEEK_MODEL)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")

    assert runner._resolve_gptscan_api_key() == "deepseek-key"
    assert runner._resolve_gptscan_api_base() == DEFAULT_DEEPSEEK_BASE_URL
    assert runner._resolve_gptscan_model() == DEFAULT_DEEPSEEK_MODEL


def test_gptscan_official_host_prefers_deepseek_key_over_generic_key(
    monkeypatch,
) -> None:
    _clear_gptscan_llm_env(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("OPENAI_API_KEY", "generic-key")

    assert runner._resolve_gptscan_api_key(
        api_base=DEFAULT_DEEPSEEK_BASE_URL,
    ) == "deepseek-key"


def test_gptscan_resolution_accepts_an_isolated_runner_environment(
    monkeypatch,
) -> None:
    _clear_gptscan_llm_env(monkeypatch)
    isolated_env = {
        "DEEPSEEK_API_KEY": "isolated-deepseek-key",
        "LAKES_OPENAI_MODEL": "isolated-model",
    }

    api_base = runner._resolve_gptscan_api_base(env=isolated_env)

    assert api_base == DEFAULT_DEEPSEEK_BASE_URL
    assert runner._resolve_gptscan_api_key(
        api_base=api_base,
        env=isolated_env,
    ) == "isolated-deepseek-key"
    assert runner._resolve_gptscan_model(env=isolated_env) == "isolated-model"


def test_gptscan_provider_key_is_scoped_to_the_resolved_endpoint(monkeypatch) -> None:
    _clear_gptscan_llm_env(monkeypatch)
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")

    assert (
        runner._resolve_gptscan_api_key(api_base="https://custom.example/v1")
        == ""
    )

    monkeypatch.setenv("OPENAI_API_KEY", "generic-key")
    assert (
        runner._resolve_gptscan_api_key(api_base="https://custom.example/v1")
        == "generic-key"
    )

    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "siliconflow-key")
    assert runner._resolve_gptscan_api_key(
        api_base="https://api.siliconflow.cn/v1"
    ) == "siliconflow-key"


def test_generic_adapter_environment_strips_provider_secrets(monkeypatch) -> None:
    secret_names = (
        "DEEPSEEK_API_KEY",
        "SILICONFLOW_API_KEY",
        "QWEN_API_KEY",
        "WHATAI_API_KEY",
        "embeddingAPI",
    )
    for name in secret_names:
        monkeypatch.setenv(name, _SENTINEL)

    env = runner._sanitized_adapter_env()

    assert all(name not in env for name in secret_names)
    assert _SENTINEL not in env.values()


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
    _clear_gptscan_llm_env(monkeypatch)
    monkeypatch.setattr(runner, "GPTSCAN_DEFAULT_API_BASE", DEFAULT_DEEPSEEK_BASE_URL)
    monkeypatch.setattr(runner, "GPTSCAN_DEFAULT_MODEL_GPT4", DEFAULT_DEEPSEEK_MODEL)
    monkeypatch.setenv("DEEPSEEK_API_KEY", _SENTINEL)
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
        "",
        7,
        "",
    )

    rendered = capsys.readouterr()
    inner_argv = json.loads(argv_capture.read_text(encoding="utf-8"))
    assert rc == 0
    assert actual["env"]["OPENAI_API_KEY"] == _SENTINEL
    assert actual["env"]["OPENAI_API_BASE"] == DEFAULT_DEEPSEEK_BASE_URL
    assert actual["env"]["GPTSCAN_MODEL_GPT4"] == DEFAULT_DEEPSEEK_MODEL
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


def test_direct_runner_reads_deepseek_key_and_official_base(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _clear_gptscan_llm_env(monkeypatch)
    monkeypatch.setattr(runner, "GPTSCAN_DEFAULT_API_BASE", DEFAULT_DEEPSEEK_BASE_URL)
    monkeypatch.setattr(runner, "GPTSCAN_DEFAULT_MODEL_GPT4", DEFAULT_DEEPSEEK_MODEL)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    captured: dict = {}

    def fake_run_targets(*args, **kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(runner, "run_targets", fake_run_targets)

    rc = runner.main([str(tmp_path / "Token.sol"), str(tmp_path / "results")])

    assert rc == 0
    assert captured["openai_api_key"] == "deepseek-key"
    assert captured["openai_api_base"] == DEFAULT_DEEPSEEK_BASE_URL


def test_native_fallback_forwards_isolated_deepseek_configuration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _clear_gptscan_llm_env(monkeypatch)
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.8.20; contract Token {}", encoding="utf-8")
    results = tmp_path / "results"
    smartbugs_dir = tmp_path / "smartbugs"
    smartbugs_dir.mkdir()
    captured: dict = {}

    def fake_adapter(tool_id, _contract_path, out_dir, **kwargs):
        captured["tool_id"] = tool_id
        captured.update(kwargs)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "result.json").write_text(
            json.dumps({"findings": []}),
            encoding="utf-8",
        )
        return 0

    monkeypatch.setattr(runner, "_run_adapter_with_deadline", fake_adapter)
    plan = build_execution_plan(
        target,
        results,
        CompositionPlan(
            selected_tool_ids=["gptscan"],
            primary_tool_id="gptscan",
            complementary_tool_ids=[],
            execution_schedule=ExecutionSchedule(tool_timeout_seconds=13.0),
        ),
        runner_script=Path(runner.__file__),
    )

    completed = execution._native_smartbugs_execute(
        plan,
        runner_env={
            "LAKES_SMARTBUGS_DIR": str(smartbugs_dir),
            "DEEPSEEK_API_KEY": _SENTINEL,
            "LAKES_OPENAI_MODEL": "isolated-model",
        },
    )

    assert completed.status == "executed"
    assert captured["tool_id"] == "gptscan"
    assert captured["openai_api_key"] == _SENTINEL
    assert captured["openai_api_base"] == DEFAULT_DEEPSEEK_BASE_URL
    assert captured["gptscan_model"] == "isolated-model"
    assert _SENTINEL not in completed.model_dump_json()


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
