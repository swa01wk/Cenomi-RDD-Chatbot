"""Serialize and sanitize complex objects for trace storage.

``sanitize_state_for_trace`` is the primary entry-point used by the
TraceManager and decorator layer before any state snapshot is persisted.

Rules applied (in order):
1. Remove ``trace_manager`` key — avoids serializing the TraceManager instance.
2. Remove keys whose values are SQLAlchemy ``AsyncSession`` instances —
   database sessions must never be stored in audit tables.
3. Strip hidden chain-of-thought keys via ``strip_cot``.
4. Redact sensitive credential keys recursively via ``redact_payload``.
5. Drop raw binary / bytes values, replacing them with ``"[BINARY_OMITTED]"``.
6. Serialize the remaining structure to a JSON-safe representation via
   ``to_json_safe``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.observability.redaction import redact_payload, strip_cot

if TYPE_CHECKING:
    pass

_REMOVE_KEYS: frozenset[str] = frozenset({"trace_manager"})


def _is_db_session(value: Any) -> bool:
    """Return True if *value* looks like a SQLAlchemy session.

    Uses a name-based check to avoid importing sqlalchemy at module load time,
    which keeps startup fast and avoids circular dependencies.
    """
    cls = type(value)
    qualname = f"{cls.__module__}.{cls.__qualname__}"
    return "AsyncSession" in cls.__name__ or "sqlalchemy" in qualname


def to_json_safe(value: Any) -> Any:
    """Recursively convert *value* to a JSON-serialisable structure.

    - ``dict`` → recursed with string keys.
    - ``list`` / ``tuple`` → recursed list.
    - ``str``, ``int``, ``float``, ``bool``, ``None`` → returned as-is.
    - ``bytes`` / ``bytearray`` → ``"[BINARY_OMITTED]"``.
    - Anything else → ``repr(value)``.
    """
    if isinstance(value, dict):
        return {str(k): to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_safe(v) for v in value]
    if isinstance(value, (bytes, bytearray)):
        return "[BINARY_OMITTED]"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def sanitize_state_for_trace(state: dict[str, Any]) -> dict[str, Any]:
    """Return a cleaned, JSON-safe copy of *state* suitable for trace storage.

    Steps:
    1. Drop ``trace_manager`` and any database session values.
    2. Strip chain-of-thought keys.
    3. Redact sensitive credential keys (recursive).
    4. Serialize to a JSON-safe structure (binary → placeholder, complex
       objects → repr).
    """
    cleaned: dict[str, Any] = {}
    for k, v in state.items():
        if k in _REMOVE_KEYS:
            continue
        if _is_db_session(v):
            continue
        cleaned[k] = v

    stripped = strip_cot(cleaned)
    redacted = redact_payload(stripped)

    if not isinstance(redacted, dict):
        return {}

    return to_json_safe(redacted)  # type: ignore[return-value]
