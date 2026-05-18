"""Append audit entries for sensitive actions."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.audit_log_repo import AuditLogRepository


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = AuditLogRepository(session)

    async def record(
        self,
        *,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str | None,
        details: dict[str, Any],
    ) -> None:
        await self._repo.append(
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )
