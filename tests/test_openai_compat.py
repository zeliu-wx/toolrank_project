from __future__ import annotations

import json
from urllib.error import URLError

import pytest

import toolrank.openai_compat as openai_compat
from toolrank.openai_compat import OpenAICompatClient, create_json_chat_completion


def _stream(payload: dict) -> str:
    chunk = {
        "choices": [
            {
                "index": 0,
                "delta": {"content": json.dumps(payload)},
            }
        ]
    }
    return f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n"


def _clear_chat_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "SILICONFLOW_API_KEY",
        "WHATAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_official_deepseek_is_the_tracked_chat_default() -> None:
    assert openai_compat.DEFAULT_DEEPSEEK_BASE_URL == "https://api.deepseek.com"
    assert openai_compat.DEFAULT_DEEPSEEK_MODEL == "deepseek-v4-flash"
    request = openai_compat._build_request(
        client=OpenAICompatClient(
            base_url=openai_compat.DEFAULT_DEEPSEEK_BASE_URL,
            api_key="test-key",
            timeout_sec=1.0,
        ),
        payload={},
    )
    assert request.full_url == "https://api.deepseek.com/chat/completions"
    assert request.get_header("Authorization") == "Bearer test-key"


def test_deepseek_api_key_is_preferred_for_the_official_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_chat_api_keys(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "legacy-test-key")
    monkeypatch.setattr(
        openai_compat,
        "DEFAULT_OPENAI_BASE_URL",
        openai_compat.DEFAULT_DEEPSEEK_BASE_URL,
    )

    client = openai_compat.load_openai_client()

    assert client == OpenAICompatClient(
        base_url="https://api.deepseek.com",
        api_key="deepseek-test-key",
        timeout_sec=openai_compat.DEFAULT_REQUEST_TIMEOUT_SEC,
    )


def test_generic_openai_api_key_remains_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_chat_api_keys(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "generic-test-key")
    monkeypatch.setattr(
        openai_compat,
        "DEFAULT_OPENAI_BASE_URL",
        openai_compat.DEFAULT_DEEPSEEK_BASE_URL,
    )

    client = openai_compat.load_openai_client()

    assert client is not None
    assert client.api_key == "generic-test-key"


def test_siliconflow_key_requires_an_explicit_siliconflow_chat_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_chat_api_keys(monkeypatch)
    monkeypatch.setenv("SILICONFLOW_API_KEY", "siliconflow-test-key")
    monkeypatch.setattr(
        openai_compat,
        "DEFAULT_OPENAI_BASE_URL",
        openai_compat.DEFAULT_DEEPSEEK_BASE_URL,
    )

    assert openai_compat.load_openai_client() is None

    monkeypatch.setattr(
        openai_compat,
        "DEFAULT_OPENAI_BASE_URL",
        "https://api.siliconflow.cn/v1",
    )
    client = openai_compat.load_openai_client()

    assert client is not None
    assert client.api_key == "siliconflow-test-key"


@pytest.mark.parametrize(
    ("base_url", "provider_key"),
    [
        ("https://api.deepseek.com", "SILICONFLOW_API_KEY"),
        ("https://api.deepseek.com", "WHATAI_API_KEY"),
        ("https://api.siliconflow.cn/v1", "DEEPSEEK_API_KEY"),
        ("https://example.test/v1", "DEEPSEEK_API_KEY"),
        ("https://example.test/v1", "SILICONFLOW_API_KEY"),
        ("https://example.test/v1", "WHATAI_API_KEY"),
    ],
)
def test_provider_specific_keys_do_not_cross_chat_endpoint_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
    provider_key: str,
) -> None:
    _clear_chat_api_keys(monkeypatch)
    monkeypatch.setenv(provider_key, "wrong-provider-test-key")
    monkeypatch.setattr(openai_compat, "DEFAULT_OPENAI_BASE_URL", base_url)

    assert openai_compat.load_openai_client() is None


def test_explicit_temperature_is_serialized_without_multi_choice_n(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bodies: list[dict] = []

    def fake_open(request, _timeout):
        bodies.append(json.loads(request.data.decode("utf-8")))
        return _stream({"complements": []})

    monkeypatch.setattr(openai_compat, "_open_request", fake_open)
    result = create_json_chat_completion(
        client=OpenAICompatClient("https://example.test/v1", "key", 1.0),
        model="test-model",
        system_prompt="system",
        user_prompt="user",
        schema={"type": "object"},
        temperature=0.0,
        raise_on_error=True,
    )

    assert result == {"complements": []}
    assert len(bodies) == 1
    assert bodies[0]["temperature"] == 0.0
    assert bodies[0]["stream"] is True
    assert "n" not in bodies[0]
    assert "thinking" not in bodies[0]
    assert "response_format" not in bodies[0]


def test_deepseek_strict_json_request_disables_default_thinking_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bodies: list[dict] = []

    def fake_open(request, _timeout):
        bodies.append(json.loads(request.data.decode("utf-8")))
        return _stream({"complements": []})

    monkeypatch.setattr(openai_compat, "_open_request", fake_open)
    result = create_json_chat_completion(
        client=OpenAICompatClient(
            openai_compat.DEFAULT_DEEPSEEK_BASE_URL,
            "test-key",
            1.0,
        ),
        model=openai_compat.DEFAULT_DEEPSEEK_MODEL,
        system_prompt="Return JSON only.",
        user_prompt="user",
        schema={"type": "object"},
        temperature=0.0,
        raise_on_error=True,
    )

    assert result == {"complements": []}
    assert bodies == [
        {
            "model": openai_compat.DEFAULT_DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": "Return JSON only."},
                {
                    "role": "user",
                    "content": (
                        "user\n\nReturn JSON only. It must satisfy the following "
                        'schema exactly:\n{"type": "object"}'
                    ),
                },
            ],
            "temperature": 0.0,
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "stream": True,
        }
    ]


def test_transport_retries_still_return_one_logical_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def flaky_open(_request, _timeout):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise URLError("temporary failure")
        return _stream({"complements": []})

    monkeypatch.setattr(openai_compat, "_open_request", flaky_open)
    monkeypatch.setattr(openai_compat.time, "sleep", lambda _delay: None)
    result = create_json_chat_completion(
        client=OpenAICompatClient("https://example.test/v1", "key", 1.0),
        model="test-model",
        system_prompt="system",
        user_prompt="user",
        temperature=0.0,
        raise_on_error=True,
    )

    assert attempts == 3
    assert result == {"complements": []}
