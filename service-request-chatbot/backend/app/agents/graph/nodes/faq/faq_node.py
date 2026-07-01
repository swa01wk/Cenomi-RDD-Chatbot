"""FAQ node — answer platform Q&A questions via hybrid RAG search + embedded prompt.

Responsibilities
----------------
- When the supervisor classifies intent as ``ASK_HELP`` or ``UNKNOWN``, this
  node handles the response by:
    1. Attempting a hybrid Azure AI Search query to retrieve relevant knowledge
       base chunks (``cenomi-help-index``).
    2. Prepending the retrieved context block to the user message before calling
       the LLM with the FAQ system prompt.
    3. Returning the answer plus structured ``faq_sources`` citations for the
       API layer and frontend.
- Falls back gracefully to the static ``FAQ_SYSTEM_PROMPT`` if:
    - No search credentials are configured (``get_search_repository()`` → ``None``)
    - Any exception occurs during embed, search, or formatting
  In all fallback cases ``faq_sources`` is returned as an empty list.

Non-responsibilities
--------------------
- MUST NOT collect, validate, or process form fields.
- MUST NOT submit or approve service requests.
- Does not create a session draft — Q&A turns are stateless.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import structlog

from app.agents.graph.state import ServiceRequestState
from app.agents.llm.gateway import get_default_gateway
from app.agents.prompts.faq_prompt import FAQ_SYSTEM_PROMPT
from app.integrations.factory import get_search_repository
from app.integrations.search.base import SearchResult
from app.observability.decorators import trace_node

log = structlog.get_logger(__name__)

_FALLBACK_MESSAGE = (
    "I'm here to help with questions about the platform and service requests. "
    "Could you rephrase your question?"
)

# Arabic Unicode block — used for language detection
_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _detect_language(text: str) -> str:
    """Return ``"ar"`` if the text contains Arabic characters, else ``"en"``."""
    return "ar" if _ARABIC_RE.search(text) else "en"


def _format_rag_context(results: list[SearchResult]) -> tuple[str, list[dict]]:
    """Format search results into a context block and a citations list.

    Returns
    -------
    rag_block:
        Markdown-formatted string prepended to the user message:
        ``### Relevant Knowledge Base Results\\n\\n...``
    faq_sources:
        List of ``{source_type, title}`` dicts for the API response / state.
    """
    if not results:
        return "", []

    lines: list[str] = ["### Relevant Knowledge Base Results\n"]
    sources: list[dict] = []

    for idx, r in enumerate(results, start=1):
        lines.append(f"**[{idx}] {r.title}** (type: {r.source_type})")
        if r.mall_name:
            lines.append(f"Mall: {r.mall_name}")
        lines.append(r.content.strip())
        lines.append("")
        sources.append({"source_type": r.source_type, "title": r.title})

    return "\n".join(lines), sources


def _build_faq_user_content(state: ServiceRequestState, rag_block: str) -> str:
    """Build the user-facing prompt content for the FAQ node.

    Prepends the RAG context block (if any) before the user question and the
    last 4 conversation turns so the model answers follow-ups accurately.
    """
    message = state.get("user_message") or ""
    parts: list[str] = []

    if rag_block:
        parts.append(rag_block)

    parts.append(f"User question: {message}")

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


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------


@trace_node("faq", "AGENT")
async def faq_node(state: ServiceRequestState) -> dict[str, Any]:
    """LangGraph node: answer a platform FAQ question via RAG + LLM.

    Attempts hybrid Azure AI Search retrieval, falls back to the static
    ``FAQ_SYSTEM_PROMPT`` on any error.  Always returns ``faq_sources`` as a
    list (empty when RAG is unavailable or fails).
    """
    user_message: str = state.get("user_message") or ""
    gateway = get_default_gateway()

    rag_block = ""
    faq_sources: list[dict] = []

    search_repo = get_search_repository()

    if search_repo is not None:
        try:
            lang = _detect_language(user_message)

            t_search = time.monotonic()
            results = await search_repo.search(query=user_message, lang=lang)
            search_total_ms = int((time.monotonic() - t_search) * 1000)

            log.info(
                "faq_node.search_complete",
                latency_ms=search_total_ms,
                hits=len(results),
                lang=lang,
            )

            rag_block, faq_sources = _format_rag_context(results)

        except Exception as exc:
            log.warning(
                "faq_node.rag_fallback",
                reason="search_error",
                error=str(exc),
            )
            rag_block = ""
            faq_sources = []
    else:
        log.debug("faq_node.rag_fallback", reason="no_repo")

    user_content = _build_faq_user_content(state, rag_block)
    answer: str = _FALLBACK_MESSAGE

    try:
        parsed, _in, _out, _ms = await gateway.complete_json(
            system_prompt=FAQ_SYSTEM_PROMPT,
            user_message=user_content,
        )
        if isinstance(parsed, dict) and parsed.get("message"):
            answer = str(parsed["message"]).strip()

            # Embed inline source markers so response_generation_node preserves them.
            if faq_sources:
                source_label = ", ".join(
                    f"[Source: {s['title']}]" for s in faq_sources[:3]
                )
                answer = f"{answer}\n\n{source_label}"
        else:
            log.warning("faq_node.unexpected_llm_shape", parsed=parsed)
    except json.JSONDecodeError as exc:
        log.warning("faq_node.json_parse_error", error=str(exc))
    except Exception as exc:
        log.exception("faq_node.llm_failed", error=str(exc))

    log.info(
        "faq_node.answered",
        answer_length=len(answer),
        rag_used=bool(rag_block),
        sources_count=len(faq_sources),
    )

    return {
        "response_message": answer,
        "status": "WAITING_FOR_USER",
        "faq_sources": faq_sources,
    }
