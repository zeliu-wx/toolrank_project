from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
GPTSCAN_SOURCE = ROOT / "docker" / "vendor" / "gptscan" / "src"


def _load_chat_module(monkeypatch):
    calls: list[dict] = []

    error_module = ModuleType("openai.error")
    for name in (
        "RateLimitError",
        "APIConnectionError",
        "Timeout",
        "APIError",
    ):
        setattr(error_module, name, type(name, (Exception,), {}))

    openai_module = ModuleType("openai")
    openai_module.__path__ = []
    openai_module.error = error_module
    openai_module.InvalidRequestError = type(
        "InvalidRequestError",
        (Exception,),
        {},
    )
    openai_module.api_key = None
    openai_module.api_base = None

    class FakeChatCompletion:
        @staticmethod
        def create(**kwargs):
            calls.append(kwargs)
            return {"choices": [{"message": {"content": "{}"}}]}

    openai_module.ChatCompletion = FakeChatCompletion

    class FakeEncoder:
        @staticmethod
        def encode(value: str) -> list[int]:
            return list(range(len(value)))

    tiktoken_module = ModuleType("tiktoken")
    tiktoken_module.get_encoding = lambda _name: FakeEncoder()
    tiktoken_module.encoding_for_model = lambda _name: FakeEncoder()

    config_module = ModuleType("config")
    config_module.OPENAI_APIS = []
    config_module.GPT4_API = ""

    console = SimpleNamespace(print=lambda *_args, **_kwargs: None)
    rich_module = ModuleType("rich")
    rich_module.get_console = lambda: console
    rich_utils_module = ModuleType("rich_utils")
    rich_utils_module.make_response_panel = lambda *_args, **_kwargs: None

    monkeypatch.setitem(sys.modules, "openai", openai_module)
    monkeypatch.setitem(sys.modules, "openai.error", error_module)
    monkeypatch.setitem(sys.modules, "tiktoken", tiktoken_module)
    monkeypatch.setitem(sys.modules, "config", config_module)
    monkeypatch.setitem(sys.modules, "rich", rich_module)
    monkeypatch.setitem(sys.modules, "rich_utils", rich_utils_module)

    module_name = "_lakes_test_gptscan_chatgpt_api"
    spec = importlib.util.spec_from_file_location(
        module_name,
        GPTSCAN_SOURCE / "chatgpt_api.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module, calls


def test_official_deepseek_gptscan_json_call_is_non_thinking_json_mode(
    monkeypatch,
) -> None:
    module, calls = _load_chat_module(monkeypatch)
    monkeypatch.setenv("OPENAI_API_BASE", "https://api.deepseek.com")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("GPTSCAN_MODEL_GPT4", "deepseek-v4-flash")

    assert module.Chat().sendMessages("Return JSON.", GPT4=True, json_mode=True) == "{}"

    assert len(calls) == 1
    assert calls[0]["model"] == "deepseek-v4-flash"
    assert calls[0]["temperature"] == 0
    assert calls[0]["thinking"] == {"type": "disabled"}
    assert calls[0]["response_format"] == {"type": "json_object"}


def test_official_deepseek_gptscan_text_call_disables_thinking_without_json_mode(
    monkeypatch,
) -> None:
    module, calls = _load_chat_module(monkeypatch)
    monkeypatch.setenv("OPENAI_API_BASE", "https://api.deepseek.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    module.Chat().sendMessages("Answer Yes or No.", GPT4=True)

    assert calls[0]["thinking"] == {"type": "disabled"}
    assert "response_format" not in calls[0]


def test_custom_gptscan_host_receives_no_deepseek_only_request_fields(
    monkeypatch,
) -> None:
    module, calls = _load_chat_module(monkeypatch)
    monkeypatch.setenv("OPENAI_API_BASE", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    module.Chat().sendMessages("Return JSON.", GPT4=True, json_mode=True)

    assert "thinking" not in calls[0]
    assert "response_format" not in calls[0]


def test_gptscan_structured_callers_enable_json_mode() -> None:
    source = (GPTSCAN_SOURCE / "analyze_pipeline.py").read_text(encoding="utf-8")

    assert "args=(prompt, gpt4, json_mode)" in source
    assert source.count("ask_with_timeout(prompt, json_mode=True)") == 2
    assert source.count(
        'ask_with_timeout(prompts+"\\n"+source, json_mode=True)'
    ) == 2
