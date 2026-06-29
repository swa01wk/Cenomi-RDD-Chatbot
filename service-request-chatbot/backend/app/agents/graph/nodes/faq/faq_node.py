"""FAQ node — answer platform Q&A questions via an embedded FAQ prompt.

Responsibilities
----------------
- When the supervisor classifies intent as ``ASK_HELP``, this node handles the
  response by calling the LLM with a well-crafted FAQ system prompt.
- No external search, no Azure AI Search, no vector embeddings.
- The FAQ_SYSTEM_PROMPT in ``faq_prompt.py`` is the single place to add or edit
  knowledge — changes take effect on the next server restart.

Non-responsibilities
--------------------
- MUST NOT collect, validate, or process form fields.
- MUST NOT submit or approve service requests.
- Does not create a session draft — Q&A turns are stateless.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import structlog

from app.agents.graph.state import ServiceRequestState
from app.agents.llm.gateway import get_default_gateway
from app.agents.prompts.faq_prompt import FAQ_SYSTEM_PROMPT
from app.observability.decorators import trace_node

log = structlog.get_logger(__name__)
logger = logging.getLogger(__name__)

_FALLBACK_MESSAGE = (
    "I'm here to help with questions about the platform and service requests. "
    "Could you rephrase your question?"
)


def _build_faq_user_content(state: ServiceRequestState) -> str:
    """Build the user-facing prompt content for the FAQ node.

    Includes up to 4 recent conversation turns for context so the model can
    answer follow-up questions accurately.
    """
    message = state.get("user_message") or ""
    parts = [f"User question: {message}"]

    history: list[dict] = state.get("conversation_history") or []  # type: ignore[assignment]
    recent = history[-4:]
    if recent:
        parts.append("Recent conversation (oldest first):")
        for turn in recent:
            role = (turn.get("role") or "unknown").capitalize()
            content = (turn.get("content") or "").strip()
            if content:
                parts.append(f"  {role}: {content}")

    return "\n".join(parts)


@trace_node("faq", "AGENT")
async def faq_node(state: ServiceRequestState) -> dict[str, Any]:
    """LangGraph node: answer a platform FAQ question via LLM.

    Calls ``LLMGateway.complete_json`` with the embedded FAQ system prompt.
    Expects the LLM to return ``{"message": "<answer>"}``.
    Falls back gracefully on any failure.
    """
    gateway = get_default_gateway()
    user_content = _build_faq_user_content(state)

    answer: str = _FALLBACK_MESSAGE

    try:
        parsed, _in, _out, _ms = await gateway.complete_json(
            system_prompt=FAQ_SYSTEM_PROMPT,
            user_message=user_content,
        )
        if isinstance(parsed, dict) and parsed.get("message"):
            answer = str(parsed["message"]).strip()
        else:
            logger.warning("faq_node: unexpected LLM response shape: %s", parsed)
    except json.JSONDecodeError as exc:
        logger.warning("faq_node: JSON parse error: %s", exc)
    except Exception as exc:
        logger.exception("faq_node: LLM call failed: %s", exc)

    log.info("faq_node.answered", answer_length=len(answer))
    return {
        "response_message": answer,
        "status": "WAITING_FOR_USER",
    }
