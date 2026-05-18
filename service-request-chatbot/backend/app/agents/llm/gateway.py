"""Minimal async LLM gateway used by supervisor and extraction nodes.

``LLMGateway`` is a thin wrapper around the OpenAI Chat Completions API that:

- Forces ``response_format={"type": "json_object"}`` so all responses are
  valid JSON (supported by gpt-4o and gpt-4o-mini).
- Returns token counts and wall-clock latency alongside the parsed payload so
  callers can feed them into ``TraceManager.capture_llm_call``.
- Exposes a ``from_settings()`` factory for production instantiation and
  accepts explicit constructor args for testing / mocking.

The module also maintains a process-level singleton (``_default_gateway``)
lazily initialised on first use.  Tests should call ``set_default_gateway``
with a mock before exercising code that calls ``get_default_gateway()``.
"""

from __future__ import annotations

import json
import time
from typing import Any

import openai

from app.core.config import settings

# ---------------------------------------------------------------------------
# Module-level singleton (replaced in tests via set_default_gateway)
# ---------------------------------------------------------------------------

_default_gateway: LLMGateway | None = None


class LLMGateway:
    """Async OpenAI JSON-mode chat completion wrapper."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        self._model = model
        self._temperature = temperature
        self._client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or None,
        )

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_settings(cls) -> LLMGateway:
        """Instantiate using application ``Settings``."""
        return cls(
            model=settings.llm_model,
            api_key=settings.openai_api_key or "",
            base_url=settings.llm_base_url,
            temperature=0.0,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def model(self) -> str:
        return self._model

    async def complete_json(
        self,
        system_prompt: str,
        user_message: str,
    ) -> tuple[dict[str, Any], int, int, int]:
        """Call the LLM and return ``(parsed_json, input_tokens, output_tokens, latency_ms)``.

        ``response_format`` is forced to ``json_object`` so ``json.loads``
        should never fail on a well-behaved model.  Callers should still
        handle ``json.JSONDecodeError`` defensively.

        Raises
        ------
        openai.OpenAIError
            Propagated as-is so the caller can decide on retry / fallback.
        json.JSONDecodeError
            If the model produces malformed JSON despite the format constraint.
        """
        start = time.monotonic()

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=self._temperature,
        )

        latency_ms = int((time.monotonic() - start) * 1000)
        raw = response.choices[0].message.content or "{}"
        usage = response.usage

        parsed: dict[str, Any] = json.loads(raw)
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        return parsed, input_tokens, output_tokens, latency_ms


# ---------------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------------


def get_default_gateway() -> LLMGateway:
    """Return the process-level ``LLMGateway`` singleton, creating it on first call."""
    global _default_gateway
    if _default_gateway is None:
        _default_gateway = LLMGateway.from_settings()
    return _default_gateway


def set_default_gateway(gateway: LLMGateway | None) -> None:
    """Override the singleton — used by tests to inject a mock gateway."""
    global _default_gateway
    _default_gateway = gateway
