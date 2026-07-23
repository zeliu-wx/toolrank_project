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
