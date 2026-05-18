"""Decorators for automatic tracing of LangGraph nodes and services.

``@trace_node`` is the primary decorator.  It wraps an async LangGraph node
function and:

1. Extracts ``trace_manager`` and ``trace_id`` from the state dict passed as
   the first positional argument.
2. Opens a run span via ``TraceManager.start_run``.
3. Captures a ``BEFORE_NODE`` state snapshot.
4. Executes the wrapped node.
5. Captures an ``AFTER_NODE`` state snapshot and the state diff.
6. Marks the run ``SUCCESS``.
7. On unhandled exception: marks the run ``FAILED`` and re-raises so the
   LangGraph error handling can proceed.

All trace calls are individually guarded so that a tracing failure never
blocks the node from executing.  If the state dict does not contain a
``trace_manager`` the node runs without any tracing side-effects.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any, ParamSpec, TypeVar
from uuid import UUID

_logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def trace_node(
    node_name: str,
    run_type: str,
) -> Callable[[Callable[P, Coroutine[Any, Any, R]]], Callable[P, Coroutine[Any, Any, R]]]:
    """Decorator factory for tracing an async LangGraph node.

    Usage::

        @trace_node("supervisor", "SUPERVISOR")
        async def supervisor_node(state: ServiceRequestGraphState) -> dict:
            ...

    Parameters
    ----------
    node_name:
        Human-readable name logged as the run/span name.
    run_type:
        Must match one of the valid run types recognised by ``RunRepository``
        (e.g. ``"LANGGRAPH_NODE"``, ``"SUPERVISOR"``, ``"AGENT"``).
    """

    def decorator(
        fn: Callable[P, Coroutine[Any, Any, R]],
    ) -> Callable[P, Coroutine[Any, Any, R]]:
        @wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            state: dict[str, Any] | None = args[0] if args else None  # type: ignore[assignment]
            tm = _extract(state, "trace_manager") if state else None
            trace_id: UUID | None = _extract_uuid(state, "trace_id") if state else None

            run_id: UUID | None = None

            if tm is not None and trace_id is not None:
                run_id = await _safe(
                    tm.start_run(
                        trace_id=trace_id,
                        run_name=node_name,
                        run_type=run_type,
                        input=_safe_state(state),
                    ),
                    context="start_run",
                )
                await _safe(
                    tm.capture_state_snapshot(
                        trace_id=trace_id,
                        run_id=run_id,
                        snapshot_type="BEFORE_NODE",
                        state=_safe_state(state),
                    ),
                    context="before_snapshot",
                )

            # Inject the outer node run_id into the state dict so that child
            # runs created inside the node (e.g. LLM call spans) can read it
            # via state.get("_trace_node_run_id") and pass it as parent_run_id.
            # The key is excluded from all snapshots via _RUNTIME_KEYS and is
            # removed after the call so it never leaks into LangGraph state.
            if state is not None and run_id is not None:
                state["_trace_node_run_id"] = run_id  # type: ignore[index]

            try:
                result: R = await fn(*args, **kwargs)
            except Exception as exc:
                if state is not None:
                    state.pop("_trace_node_run_id", None)  # type: ignore[union-attr]
                if tm is not None and run_id is not None:
                    await _safe(
                        tm.finish_run(
                            run_id=run_id,
                            status="FAILED",
                            error_message=str(exc),
                        ),
                        context="finish_run_failed",
                    )
                raise

            # Clean up the injected run_id key before capturing snapshots so it
            # never appears in persisted state or propagates to subsequent nodes.
            if state is not None:
                state.pop("_trace_node_run_id", None)  # type: ignore[union-attr]

            if tm is not None and trace_id is not None and run_id is not None:
                node_output = result if isinstance(result, dict) else {}
                # Build the merged state (accumulated input + node updates) for
                # the AFTER_NODE snapshot.  This prevents the diff from showing
                # every context key as "removed" — only the actual changes appear.
                # The raw node output is still passed to finish_run so the run's
                # ``output`` field reflects exactly what this node returned.
                merged_after_state = {**_safe_state(state), **node_output}
                before_state = _safe_state(state)
                await _safe(
                    tm.capture_state_snapshot(
                        trace_id=trace_id,
                        run_id=run_id,
                        snapshot_type="AFTER_NODE",
                        state=merged_after_state,
                    ),
                    context="after_snapshot",
                )
                await _safe(
                    tm.capture_state_diff(
                        trace_id=trace_id,
                        run_id=run_id,
                        before_state=before_state,
                        after_state=merged_after_state,
                    ),
                    context="state_diff",
                )
                await _safe(
                    tm.finish_run(run_id=run_id, output=node_output, status="SUCCESS"),
                    context="finish_run_success",
                )

            return result

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Backward-compatibility alias
# ---------------------------------------------------------------------------

def traced(
    trace_manager: Any,
    name: str | None = None,
) -> Callable[[Callable[P, Coroutine[Any, Any, R]]], Callable[P, Coroutine[Any, Any, R]]]:
    """Deprecated — use :func:`trace_node` instead.

    Kept so that any existing code referencing ``@traced(trace_manager, ...)``
    continues to compile without modification.  The decorator becomes a
    no-op wrapper that simply awaits the function.
    """

    def decorator(
        fn: Callable[P, Coroutine[Any, Any, R]],
    ) -> Callable[P, Coroutine[Any, Any, R]]:
        span_name = name or fn.__name__
        _logger.warning(
            "@traced is deprecated; migrate to @trace_node('%s', run_type='...')",
            span_name,
        )

        @wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            return await fn(*args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _extract(state: dict[str, Any] | None, key: str) -> Any:
    if not isinstance(state, dict):
        return None
    return state.get(key)


def _extract_uuid(state: dict[str, Any] | None, key: str) -> UUID | None:
    raw = _extract(state, key)
    if raw is None:
        return None
    try:
        return raw if isinstance(raw, UUID) else UUID(str(raw))
    except (ValueError, AttributeError):
        return None


# Keys injected at runtime that contain non-serialisable objects (DB sessions,
# service instances) or internal decorator bookkeeping.  These are excluded from
# every state snapshot / diff so that JSON serialisation never fails when the
# trace layer persists state.
_RUNTIME_KEYS: frozenset[str] = frozenset(
    {"conversation_state_service", "trace_manager", "_trace_node_run_id"}
)


def _safe_state(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    return {k: v for k, v in state.items() if k not in _RUNTIME_KEYS}


async def _safe(coro: Any, *, context: str) -> Any:
    """Await *coro* and absorb any exception, logging it at WARNING level."""
    try:
        return await coro
    except Exception:
        _logger.warning("trace_node.%s.failed", context, exc_info=True)
        return None
