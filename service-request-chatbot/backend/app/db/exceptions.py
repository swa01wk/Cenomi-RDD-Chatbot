"""Database layer custom exceptions.

All repository errors inherit from RepositoryError so callers can catch the
base class when they don't care about the specific sub-type.
"""

from __future__ import annotations


class RepositoryError(Exception):
    """Base class for all repository-layer errors."""


class RecordNotFoundError(RepositoryError):
    """Raised when a requested record does not exist in the database."""

    def __init__(self, model: str, record_id: object) -> None:
        super().__init__(f"{model} with id={record_id!r} not found")
        self.model = model
        self.record_id = record_id


class InvalidUpdateFieldError(RepositoryError):
    """Raised when an update dict contains a field that is not updatable."""

    def __init__(self, model: str, field: str) -> None:
        super().__init__(f"Field {field!r} is not updatable on {model}")
        self.model = model
        self.field = field
