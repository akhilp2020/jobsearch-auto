"""Concrete LLM driver implementations."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any, Callable, Mapping

import httpx


PostFn = Callable[..., httpx.Response]


class LLMDriver(ABC):
    """Interface for large-language-model providers."""

    def __init__(self, model: str) -> None:
        self.model = model

    @abstractmethod
    def complete(self, prompt: str) -> str:
        """Synchronously obtain a completion for *prompt*."""

    def embed(self, text: str) -> list[float]:  # pragma: no cover - optional
        """Return an embedding vector if the provider supports it."""

        raise NotImplementedError("Embeddings not implemented for this driver")


class OpenAICompletionDriver(LLMDriver):
    """Driver that talks to OpenAI endpoints."""

    _CHAT_API_URL = "https://api.openai.com/v1/chat/completions"
    _RESPONSES_API_URL = "https://api.openai.com/v1/responses"

    def __init__(self, model: str, api_key: str, *, post: PostFn | None = None) -> None:
        super().__init__(model)
        self._api_key = api_key
        self._post = post or httpx.post

    def _use_responses_api(self) -> bool:
        return self.model.lower().startswith("gpt-5")

    def complete(self, prompt: str) -> str:
        headers = {"Authorization": f"Bearer {self._api_key}"}

        if self._use_responses_api():
            payload = {"model": self.model, "input": prompt}
            response = self._post(
                self._RESPONSES_API_URL, headers=headers, json=payload, timeout=30
            )
            response.raise_for_status()
            data = response.json()
            return self._parse_responses_payload(data)

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        response = self._post(
            self._CHAT_API_URL, headers=headers, json=payload, timeout=30
        )
        response.raise_for_status()
        data = response.json()
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError) as exc:  # pragma: no cover - defensive
            raise RuntimeError("Unexpected OpenAI response format") from exc

    @staticmethod
    def _parse_responses_payload(data: Mapping[str, Any]) -> str:
        # Expected shape matches OpenAI's responses API: output -> content -> text
        outputs = data.get("output") or data.get("outputs") or []
        if not outputs:
            return ""

        for entry in outputs:
            if not isinstance(entry, Mapping):
                continue
            content = entry.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, Mapping):
                        text = block.get("text") or block.get("value")
                        if text:
                            return str(text).strip()
                    elif isinstance(block, str) and block:
                        return block.strip()
            if "text" in entry and entry["text"]:
                return str(entry["text"]).strip()

        first = outputs[0]
        return str(first).strip()


class AnthropicCompletionDriver(LLMDriver):
    """Driver that talks to Anthropic's messages API."""

    _API_URL = "https://api.anthropic.com/v1/messages"
    _API_VERSION = "2023-06-01"

    def __init__(self, model: str, api_key: str, *, post: PostFn | None = None) -> None:
        super().__init__(model)
        self._api_key = api_key
        self._post = post or httpx.post

    def complete(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "max_tokens": 512,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": self._API_VERSION,
        }
        response = self._post(self._API_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        try:
            message_blocks = data["content"]
            if not message_blocks:
                return ""
            first_block = message_blocks[0]
            if isinstance(first_block, Mapping):
                return str(first_block.get("text", "")).strip()
            return str(first_block).strip()
        except KeyError as exc:  # pragma: no cover - defensive
            raise RuntimeError("Unexpected Anthropic response format") from exc


class OllamaCompletionDriver(LLMDriver):
    """Driver for a local Ollama-compatible HTTP endpoint."""

    def __init__(
        self,
        model: str,
        *,
        base_url: str = "http://localhost:11434",
        post: PostFn | None = None,
    ) -> None:
        super().__init__(model)
        normalized = base_url.rstrip("/")
        if normalized.endswith("/api"):
            self._url = normalized + "/generate"
        else:
            self._url = normalized + "/api/generate"
        self._post = post or httpx.post

    def complete(self, prompt: str) -> str:
        payload = {"model": self.model, "prompt": prompt, "stream": False}
        response = self._post(self._url, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        return str(data.get("response", "")).strip()


def load_driver_from_env(*, post: PostFn | None = None) -> LLMDriver:
    """Load an :class:`LLMDriver` based on common environment variables."""

    provider = os.getenv("LLM_PROVIDER")
    model = os.getenv("LLM_MODEL")
    api_key = os.getenv("LLM_API_KEY")
    endpoint = os.getenv("LLM_ENDPOINT")

    if not provider:
        raise RuntimeError("LLM_PROVIDER is required")
    if not model:
        raise RuntimeError("LLM_MODEL is required")

    provider_key = provider.strip().lower()
    if provider_key == "openai":
        if not api_key:
            raise RuntimeError("LLM_API_KEY is required for OpenAI provider")
        return OpenAICompletionDriver(model=model, api_key=api_key, post=post)

    if provider_key == "anthropic":
        if not api_key:
            raise RuntimeError("LLM_API_KEY is required for Anthropic provider")
        return AnthropicCompletionDriver(model=model, api_key=api_key, post=post)

    if provider_key in {"ollama", "local"}:
        base_url = endpoint or "http://localhost:11434"
        return OllamaCompletionDriver(model=model, base_url=base_url, post=post)

    raise RuntimeError(f"Unsupported LLM provider: {provider}")
