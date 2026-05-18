"""Repository layer — persistence only; no orchestration or LLM calls.

Public API
──────────
    ChatSessionRepository
    ChatMessageRepository
    ServiceRequestDraftRepository
    AuditLogRepository

Exceptions re-exported for convenience:
    RecordNotFoundError
    InvalidUpdateFieldError
"""

from app.db.exceptions import InvalidUpdateFieldError, RecordNotFoundError
from app.db.repositories.audit_log_repo import AuditLogRepository
from app.db.repositories.chat_message_repo import ChatMessageRepository
from app.db.repositories.chat_session_repo import ChatSessionRepository
from app.db.repositories.service_request_draft_repo import ServiceRequestDraftRepository

__all__ = [
    "AuditLogRepository",
    "ChatMessageRepository",
    "ChatSessionRepository",
    "ServiceRequestDraftRepository",
    "RecordNotFoundError",
    "InvalidUpdateFieldError",
]
