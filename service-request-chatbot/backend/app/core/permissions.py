"""Permission constants and helpers (authorization layer lives alongside domain services)."""

from collections.abc import Iterable

VIEW_SERVICE_REQUEST = "service_request:view"
CREATE_SERVICE_REQUEST = "service_request:create"
UPLOAD_DOCUMENT = "document:upload"
VIEW_OBSERVABILITY = "observability:view"
SUBMIT_FEEDBACK = "observability:feedback"


def has_any(role_names: Iterable[str], required: frozenset[str]) -> bool:
    return bool(required & set(role_names))
