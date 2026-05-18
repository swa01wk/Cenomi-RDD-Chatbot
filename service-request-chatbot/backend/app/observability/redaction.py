"""Payload sanitisation utilities for the agent observability layer.

Rules enforced before any JSONB payload is persisted:

1. ``redact_payload`` — recursively replaces the *value* of any key whose
   name exactly matches a sensitive key name with ``"[REDACTED]"``.
   Walks nested dicts and lists.  Primitives are returned as-is.

2. ``_strip_cot`` — removes top-level keys that contain hidden
   chain-of-thought content (chain_of_thought, reasoning, thinking).
   These must never appear in auditable storage.

``sanitise`` applies both in one call and is the single entry-point used by
all repository modules.
"""

from __future__ import annotations

from typing import Any

_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "authorization",
        "access_token",
        "refresh_token",
        "cookie",
        "password",
        "secret",
        "api_key",
        "signed_url",
        "token",
        "credential",
        "credentials",
        "connection_string",
        # Prevent OpenAI key from leaking via config/settings dumps in traces
        "openai_api_key",
        # Prevent accidental system-prompt content from being stored in traces
        "internal_prompt",
    }
)

_COT_KEYS: frozenset[str] = frozenset(
    {"chain_of_thought", "reasoning", "thinking"}
)


def _is_sensitive_key(key: str) -> bool:
    """Return ``True`` if *key* (case-insensitive) is or contains a sensitive term.

    Matches both exact keys (``"api_key"``) and composite keys that embed a
    sensitive word (``"secret_key"``, ``"access_token_expiry"``).
    """
    lowered = key.lower()
    return any(sensitive in lowered for sensitive in _SENSITIVE_KEYS)


def redact_payload(payload: Any) -> Any:
    """Recursively redact sensitive keys in *payload*.

    - ``dict``: keys whose lowercased name equals or contains any entry in
      ``_SENSITIVE_KEYS`` have their values replaced with ``"[REDACTED]"``.
      Other values are recursed into.
    - ``list``: each element is recursed into.
    - Primitives (str, int, float, bool, None): returned unchanged.

    The original structure is never mutated.
    """
    if isinstance(payload, dict):
        return {
            k: "[REDACTED]" if _is_sensitive_key(k) else redact_payload(v)
            for k, v in payload.items()
        }
    if isinstance(payload, list):
        return [redact_payload(item) for item in payload]
    return payload


def redact(payload: dict[str, Any]) -> dict[str, Any]:
    """Shallow-compatible wrapper — delegates to :func:`redact_payload`.

    Kept for backward compatibility with callers that expect a
    ``dict → dict`` signature.
    """
    result = redact_payload(payload)
    return result if isinstance(result, dict) else {}


def strip_cot(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *payload* with hidden chain-of-thought keys removed.

    Only top-level keys are inspected.  The original dict is not mutated.
    """
    return {k: v for k, v in payload.items() if k not in _COT_KEYS}


def sanitise(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply both :func:`redact` and :func:`strip_cot` in one call.

    Use this as the single entry-point when preparing any JSONB payload
    for storage in the observability tables.
    """
    return redact(strip_cot(payload))
