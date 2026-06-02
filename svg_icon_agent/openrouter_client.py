"""OpenRouter chat-completions client."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

import requests

# DEFAULT_OPENROUTER_MODEL = "openai/gpt-oss-120b:free"
DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-v4-flash"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 2


class OpenRouterError(RuntimeError):
    """Raised when OpenRouter cannot return a usable response."""

    def __init__(self, message: str, debug_payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.debug_payload = debug_payload or {}


@dataclass(frozen=True)
class OpenRouterConfig:
    api_key: str
    model: str = DEFAULT_OPENROUTER_MODEL
    endpoint: str = OPENROUTER_CHAT_URL
    timeout: float = DEFAULT_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES
    app_title: str = "SVG Icon Agent"
    http_referer: str | None = None

    @classmethod
    def from_env(
        cls,
        model: str | None = None,
        *,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> "OpenRouterConfig":
        api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            raise OpenRouterError("OPENROUTER_API_KEY is not set.")
        return cls(
            api_key=api_key,
            model=model or os.environ.get("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL),
            timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
            max_retries=max_retries if max_retries is not None else DEFAULT_MAX_RETRIES,
            http_referer=os.environ.get("OPENROUTER_HTTP_REFERER") or None,
        )


@dataclass(frozen=True)
class OpenRouterResponse:
    content: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def trace(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "usage": self.usage,
        }


class OpenRouterClient:
    """Small wrapper around OpenRouter's OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        config: OpenRouterConfig,
        session: requests.Session | None = None,
    ) -> None:
        self.config = config
        self.session = session or requests.Session()

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        response_format: dict[str, Any] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1400,
    ) -> OpenRouterResponse:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self.session.post(
                    self.config.endpoint,
                    json=payload,
                    headers=self._headers(),
                    timeout=self.config.timeout,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise OpenRouterError(
                    f"OpenRouter request failed: {exc}",
                    debug_payload={"error_type": type(exc).__name__, "message": str(exc)},
                ) from exc

            if response.status_code in {408, 409, 425, 429} or response.status_code >= 500:
                if attempt < self.config.max_retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue
            if response.status_code >= 400:
                raise OpenRouterError(
                    f"OpenRouter returned HTTP {response.status_code}: {_safe_response_text(response)}",
                    debug_payload={
                        "status_code": response.status_code,
                        "body": _safe_response_text(response),
                    },
                )

            data = _response_json(response)
            try:
                choice = data["choices"][0]
                message = choice["message"]
                content = message["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise OpenRouterError(
                    "OpenRouter response did not contain choices[0].message.content.",
                    debug_payload=_sanitize_payload(data),
                ) from exc
            if not isinstance(content, str) or not content.strip():
                raise OpenRouterError(
                    "OpenRouter returned an empty message.",
                    debug_payload=_sanitize_payload(data),
                )

            return OpenRouterResponse(
                content=content.strip(),
                model=str(data.get("model") or self.config.model),
                usage=data.get("usage") if isinstance(data.get("usage"), dict) else {},
                raw=_sanitize_payload(data),
            )

        raise OpenRouterError(
            f"OpenRouter request failed after retries: {last_error}",
            debug_payload={"error": str(last_error) if last_error else "unknown"},
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "X-OpenRouter-Title": self.config.app_title,
        }
        if self.config.http_referer:
            headers["HTTP-Referer"] = self.config.http_referer
        return headers


def has_openrouter_key() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY", "").strip())


def _response_json(response: requests.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise OpenRouterError(
            "OpenRouter response was not valid JSON.",
            debug_payload={"status_code": response.status_code, "body": _safe_response_text(response)},
        ) from exc
    if not isinstance(data, dict):
        raise OpenRouterError("OpenRouter response JSON must be an object.")
    return data


def _safe_response_text(response: requests.Response) -> str:
    text = response.text.strip().replace(os.environ.get("OPENROUTER_API_KEY", ""), "")
    return text[:500] if text else "<empty response>"


def _sanitize_payload(value: Any) -> Any:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if isinstance(value, dict):
        return {str(key): _sanitize_payload(item) for key, item in value.items() if str(key).lower() != "authorization"}
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    if isinstance(value, str):
        return value.replace(api_key, "[REDACTED]") if api_key else value
    return value
