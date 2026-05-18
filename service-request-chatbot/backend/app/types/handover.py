"""Types for model → system structured handover payloads."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class HandoverFieldCandidate:
    """A single LLM-proposed field; validation happens in code, not in the model."""

    field_key: str
    value: Any
    confidence: float | None = None
