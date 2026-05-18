"""Rule-based prompt-injection detection for user messages.

Design
------
The scanner applies a fixed list of regex patterns to the (lowercased) input
text.  Each pattern is assigned an individual risk score (0.0–1.0) and a
short label.  The final ``InjectionScanResult`` carries:

- ``risk_score``        — maximum score across all matched patterns.
- ``matched_patterns``  — list of labels for every matched pattern.
- ``reason``            — human-readable summary for audit/logging.
- ``is_high_risk``      — ``True`` when ``risk_score >= HIGH_RISK_THRESHOLD``.

Thresholds
----------
``HIGH_RISK_THRESHOLD = 0.7``

At or above this score the orchestration layer should:
  1. Refuse to invoke the LangGraph pipeline.
  2. Write an audit event (``security.injection_attempt``).
  3. Return a safe refusal reply to the user.

Below the threshold (but with ≥1 match) the call is suspicious but allowed
through — the orchestration layer should log a structured warning.

Clean messages (no matches) return ``risk_score = 0.0``, ``is_high_risk = False``.

Note: this is a POC rule-based detector.  False-positive rate is acceptable
for a controlled internal tool; a production deployment can layer an LLM
classifier on top.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Threshold
# ---------------------------------------------------------------------------

HIGH_RISK_THRESHOLD: float = 0.7

# ---------------------------------------------------------------------------
# Pattern registry  (pattern, individual_score, label)
# ---------------------------------------------------------------------------
# Patterns are compiled once at import time; they run on the lowercased text
# so capitalisation variants are covered without `re.IGNORECASE` overhead.

_RAW_PATTERNS: list[tuple[str, float, str]] = [
    # Instruction-hijack vectors
    (r"ignore\s+(?:previous|all)\s+instructions?", 0.9, "instruction-override"),
    (r"override\s+developer\s+instructions?", 0.9, "dev-override"),
    (r"forget\s+(?:your\s+)?(?:previous\s+)?instructions?", 0.85, "instruction-forget"),
    # System-prompt leakage probes
    (r"reveal\s+(?:the\s+|your\s+)?system\s+prompt", 0.9, "system-prompt-leak"),
    (r"show\s+(?:me\s+)?(?:your\s+)?(?:hidden\s+)?(?:system\s+)?instructions?", 0.8, "system-prompt-leak"),
    (r"what\s+(?:are\s+)?your\s+(?:hidden\s+)?instructions?", 0.75, "system-prompt-leak"),
    (r"print\s+(?:your\s+)?(?:system\s+)?prompt", 0.85, "system-prompt-leak"),
    # Policy / validation bypass
    (r"bypass\s+policy", 0.8, "policy-bypass"),
    (r"skip\s+validation", 0.7, "skip-validation"),
    (r"submit\s+anyway", 0.7, "skip-confirmation"),
    (r"force\s+submit", 0.75, "skip-confirmation"),
    # Secrets / credential disclosure
    (r"disclose\s+secrets?", 0.8, "secret-disclosure"),
    (r"(?:reveal|show|print|output|expose)\s+(?:(?:the|your|an?|my)\s+)?(?:api[\s_]?key|token|credential|password|secret)", 0.85, "secret-disclosure"),
    # Unauthorised execution
    (r"execute\s+unauthorized\s+action", 0.8, "unauthorized-exec"),
    (r"run\s+(?:a\s+)?(?:system|shell|exec|command|script)\s+(?:command|call)?", 0.75, "unauthorized-exec"),
    # Direct API call injection
    (r"call\s+(?:the\s+)?api\s+(?:directly|now|immediately)", 0.8, "direct-api-call"),
    (r"(?:post|get|put|delete|patch)\s+(?:to\s+|from\s+)?(?:https?://|/api/)", 0.75, "direct-api-call"),
]

# Compile patterns once
_COMPILED_PATTERNS: list[tuple[re.Pattern[str], float, str]] = [
    (re.compile(pat), score, label) for pat, score, label in _RAW_PATTERNS
]

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InjectionScanResult:
    """Immutable result returned by :func:`scan_message`.

    Attributes
    ----------
    risk_score:
        Maximum individual score across all matched patterns.
        ``0.0`` when no patterns matched.
    matched_patterns:
        Labels of every pattern that fired (may contain duplicates when
        multiple sub-patterns share the same label).
    reason:
        Single human-readable sentence suitable for audit logging.
    is_high_risk:
        ``True`` when ``risk_score >= HIGH_RISK_THRESHOLD``.
    """

    risk_score: float
    matched_patterns: list[str] = field(default_factory=list)
    reason: str = ""
    is_high_risk: bool = False


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


def scan_message(text: str) -> InjectionScanResult:
    """Scan *text* for prompt-injection patterns and return a result.

    The function is **pure** (no side effects, no I/O).  Callers are
    responsible for logging and audit writes based on the returned result.

    Parameters
    ----------
    text:
        The raw user message to evaluate.

    Returns
    -------
    InjectionScanResult
        Always returns a result; never raises.
    """
    if not text or not text.strip():
        return InjectionScanResult(
            risk_score=0.0,
            matched_patterns=[],
            reason="Empty message — no injection risk.",
            is_high_risk=False,
        )

    lowered = text.lower()
    matched_labels: list[str] = []
    max_score: float = 0.0

    for compiled_re, score, label in _COMPILED_PATTERNS:
        if compiled_re.search(lowered):
            matched_labels.append(label)
            if score > max_score:
                max_score = score

    if not matched_labels:
        return InjectionScanResult(
            risk_score=0.0,
            matched_patterns=[],
            reason="No injection patterns detected.",
            is_high_risk=False,
        )

    is_high = max_score >= HIGH_RISK_THRESHOLD
    unique_labels = list(dict.fromkeys(matched_labels))  # deduplicated, insertion-ordered

    reason = (
        f"{'High' if is_high else 'Suspicious'}-risk input detected "
        f"(score={max_score:.2f}): matched [{', '.join(unique_labels)}]."
    )

    return InjectionScanResult(
        risk_score=max_score,
        matched_patterns=unique_labels,
        reason=reason,
        is_high_risk=is_high,
    )
