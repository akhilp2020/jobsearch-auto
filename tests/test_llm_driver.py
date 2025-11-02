from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

# Ensure repository packages are importable when running tests directly.
ROOT = Path(__file__).resolve().parents[1]
LIB_PATH = ROOT / "libs" / "llm_driver" / "src"
if str(LIB_PATH) not in sys.path:
    sys.path.insert(0, str(LIB_PATH))

from llm_driver import (
    AnthropicCompletionDriver,
    OllamaCompletionDriver,
    OpenAICompletionDriver,
    load_driver_from_env,
)


class _StubResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:  # pragma: no cover - behaviour mocked
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


def test_openai_chat_complete_sends_expected_payload() -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, *, headers: dict[str, str] | None = None, json: Any = None, timeout: int | None = None) -> _StubResponse:
        captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _StubResponse({"choices": [{"message": {"content": "Hello"}}]})

    driver = OpenAICompletionDriver(model="gpt-4o", api_key="secret", post=fake_post)
    result = driver.complete("hi")

    assert result == "Hello"
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["headers"] == {"Authorization": "Bearer secret"}
    assert captured["json"] == {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0,
    }
    assert captured["timeout"] == 30


def test_openai_responses_complete_sends_expected_payload() -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, *, headers: dict[str, str] | None = None, json: Any = None, timeout: int | None = None) -> _StubResponse:
        captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _StubResponse(
            {
                "output": [
                    {"id": "rs", "type": "reasoning", "summary": []},
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Hello",
                            }
                        ]
                    }
                ]
            }
        )

    driver = OpenAICompletionDriver(model="gpt-5-mini", api_key="secret", post=fake_post)
    result = driver.complete("hi")

    assert result == "Hello"
    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["headers"] == {"Authorization": "Bearer secret"}
    assert captured["json"] == {"model": "gpt-5-mini", "input": "hi"}
    assert captured["timeout"] == 30


def test_anthropic_complete_sends_expected_payload() -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, *, headers: dict[str, str] | None = None, json: Any = None, timeout: int | None = None) -> _StubResponse:
        captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _StubResponse({"content": [{"type": "text", "text": "Hello"}]})

    driver = AnthropicCompletionDriver(model="claude-3", api_key="anthro", post=fake_post)
    result = driver.complete("hi")

    assert result == "Hello"
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"] == {
        "x-api-key": "anthro",
        "anthropic-version": "2023-06-01",
    }
    assert captured["json"] == {
        "model": "claude-3",
        "max_tokens": 512,
        "messages": [{"role": "user", "content": "hi"}],
    }
    assert captured["timeout"] == 30


def test_ollama_complete_sends_expected_payload() -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, *, headers: dict[str, str] | None = None, json: Any = None, timeout: int | None = None) -> _StubResponse:
        captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _StubResponse({"response": "Hello"})

    driver = OllamaCompletionDriver(model="llama3:latest", base_url="http://ollama.local:11434", post=fake_post)
    result = driver.complete("hi")

    assert result == "Hello"
    assert captured["url"] == "http://ollama.local:11434/api/generate"
    assert captured["headers"] is None
    assert captured["json"] == {
        "model": "llama3:latest",
        "prompt": "hi",
        "stream": False,
    }
    assert captured["timeout"] == 30


@pytest.mark.parametrize(
    "provider, expected_cls",
    [
        ("openai", OpenAICompletionDriver),
        ("anthropic", AnthropicCompletionDriver),
        ("ollama", OllamaCompletionDriver),
        ("local", OllamaCompletionDriver),
    ],
)
def test_load_driver_from_env(monkeypatch: pytest.MonkeyPatch, provider: str, expected_cls: type[object]) -> None:
    monkeypatch.setenv("LLM_PROVIDER", provider)
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_API_KEY", "key")
    monkeypatch.setenv("LLM_ENDPOINT", "http://custom:11434")

    created = load_driver_from_env(post=lambda *args, **kwargs: _StubResponse({}))
    assert isinstance(created, expected_cls)


def test_load_driver_from_env_requires_api_key_for_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL", "foo")
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    with pytest.raises(RuntimeError):
        load_driver_from_env(post=lambda *args, **kwargs: _StubResponse({}))


def test_load_driver_from_env_uses_endpoint_for_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MODEL", "foo")
    monkeypatch.setenv("LLM_ENDPOINT", "http://my-host:1234/api")

    driver = load_driver_from_env(post=lambda *args, **kwargs: _StubResponse({}))
    assert isinstance(driver, OllamaCompletionDriver)
    assert driver._url == "http://my-host:1234/api/generate"


def teardown_module() -> None:  # pragma: no cover - test hygiene
    for key in ("LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY", "LLM_ENDPOINT"):
        os.environ.pop(key, None)
