#!/usr/bin/env python3
"""Session trace evaluator for the Handover Service Request chatbot.

Fetches the full replay for a given session_id from the live backend and
scores every turn against a set of quality criteria.

Usage
-----
From the backend/ directory:

    python -m tests.eval.eval_session --session-id f2776b79-d1c2-4b90-a8f6-d25aa2adc3a0

    # Pretty-print only (no JSON file)
    python -m tests.eval.eval_session --session-id <uuid> --no-json

    # Point at a different backend
    python -m tests.eval.eval_session --session-id <uuid> --base-url http://staging:8000

Criteria evaluated per turn
----------------------------
1. STATUS          — trace status must be SUCCESS
2. LATENCY         — warn when total_latency_ms > 5 000 ms
3. INTENT          — flag UNKNOWN intent after Turn 1 on an active agent
4. STAGE           — workflow_stage must not regress (only forward or stay same)
5. EXTRACTION      — flag when no fields were extracted on a field-collection turn
6. CONFIRMATION    — warn when all fields are present but confirmation_card not issued
7. SUBMISSION      — verify SR_CREATED stage reached on the final successful turn
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "http://localhost:8000"
HIGH_LATENCY_MS = 5_000

STAGE_ORDER = {"CREATE_SR": 0, "FM_REVIEW": 1, "RDD_REVIEW": 2, "SR_CREATED": 3}

# Fields the user must supply (not backend-derived).  Used to detect turns
# where the bot should have extracted at least one field.
USER_SUPPLIED_FIELDS = frozenset(
    {
        "title",
        "description",
        "startDate",
        "endDate",
        "inspection_done_by",
        "comments",
        "notes",
    }
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class Severity(str, Enum):
    PASS = "PASS"
    INFO = "INFO"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class CheckResult:
    name: str
    severity: Severity
    message: str


@dataclass
class TurnEval:
    turn_number: int
    trace_id: str
    input_message: str
    output_message: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def worst_severity(self) -> Severity:
        order = [Severity.FAIL, Severity.WARN, Severity.INFO, Severity.PASS]
        for sev in order:
            if any(c.severity == sev for c in self.checks):
                return sev
        return Severity.PASS

    def add(self, name: str, severity: Severity, message: str) -> None:
        self.checks.append(CheckResult(name, severity, message))


@dataclass
class SessionEval:
    session_id: str
    trace_count: int
    turns: list[TurnEval] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {s.value: 0 for s in Severity}
        for t in self.turns:
            counts[t.worst_severity.value] += 1
        return counts


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


def fetch_session_replay(session_id: str, base_url: str) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/observability/sessions/{session_id}/replay"
    with httpx.Client(timeout=30) as client:
        resp = client.get(url)
    if resp.status_code == 404:
        print(f"[ERROR] Session {session_id} not found at {url}", file=sys.stderr)
        sys.exit(1)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Per-turn evaluation logic
# ---------------------------------------------------------------------------


def _has_field_collection_turns(turn_data: dict[str, Any]) -> bool:
    """True if this turn ran field_extraction (captured via runs)."""
    return any(r["run_name"] == "field_extraction" for r in turn_data.get("runs", []))


def _extracted_user_fields(turn_data: dict[str, Any]) -> list[str]:
    """Return names of user-supplied fields extracted on this turn (from LLM call output)."""
    result: list[str] = []
    for llm in turn_data.get("llm_calls", []):
        out = llm.get("structured_output") or {}
        for fname in (out.get("fields") or {}).keys():
            if fname in USER_SUPPLIED_FIELDS:
                result.append(fname)
    return result


def _confirmation_card_issued(turn_data: dict[str, Any]) -> bool:
    """True when any run or tool call output contains a confirmation_card hint.

    The session replay does not store the full HTTP response body; this
    heuristic checks run outputs for any key mentioning 'confirmation'.
    """
    for run in turn_data.get("runs", []):
        out = json.dumps(run.get("output") or {})
        if "confirmation" in out.lower():
            return True
    return False


def _all_user_fields_present(trace: dict[str, Any], turn_data: dict[str, Any]) -> bool:
    """Check state snapshots for presence of all required user fields.

    Looks for AFTER_NODE snapshots containing collected_data.
    """
    for snap in turn_data.get("state_snapshots", []):
        if snap.get("snapshot_type") != "AFTER_NODE":
            continue
        state = snap.get("state") or {}
        cd = state.get("collected_data") or {}
        if all(cd.get(f) for f in ("description", "startDate", "endDate", "inspection_done_by")):
            return True
    return False


def evaluate_turn(
    turn_number: int,
    turn_data: dict[str, Any],
    prev_stage: str | None,
) -> TurnEval:
    trace = turn_data["trace"]
    te = TurnEval(
        turn_number=turn_number,
        trace_id=trace["id"],
        input_message=trace.get("input_message") or "",
        output_message=trace.get("output_message") or "",
    )

    # ── 1. STATUS ────────────────────────────────────────────────────────────
    status = trace.get("status", "UNKNOWN")
    if status == "SUCCESS":
        te.add("STATUS", Severity.PASS, "Trace completed successfully")
    else:
        te.add("STATUS", Severity.FAIL, f"Trace status: {status} — {trace.get('error_message', '')}")

    # ── 2. LATENCY ───────────────────────────────────────────────────────────
    latency = trace.get("total_latency_ms")
    if latency is None:
        te.add("LATENCY", Severity.INFO, "Latency not recorded")
    elif latency > HIGH_LATENCY_MS:
        te.add("LATENCY", Severity.WARN, f"High latency: {latency} ms (threshold {HIGH_LATENCY_MS} ms)")
    else:
        te.add("LATENCY", Severity.PASS, f"Latency OK: {latency} ms")

    # ── 3. INTENT ────────────────────────────────────────────────────────────
    intent = trace.get("intent")
    active_agent = trace.get("active_agent")
    if turn_number == 1:
        te.add("INTENT", Severity.INFO, f"Turn 1 intent: {intent} (classification warm-up expected)")
    elif intent == "UNKNOWN" and not active_agent:
        te.add("INTENT", Severity.WARN, f"Intent UNKNOWN and no active agent on turn {turn_number}")
    elif intent:
        te.add("INTENT", Severity.PASS, f"Intent: {intent}")
    else:
        te.add("INTENT", Severity.INFO, "No intent recorded (agent already active)")

    # ── 4. STAGE PROGRESSION ─────────────────────────────────────────────────
    stage_after = trace.get("workflow_stage_after")
    stage_before = trace.get("workflow_stage_before")
    if stage_after and prev_stage and stage_after != prev_stage:
        prev_order = STAGE_ORDER.get(prev_stage, -1)
        after_order = STAGE_ORDER.get(stage_after, -1)
        if after_order < prev_order:
            te.add("STAGE", Severity.WARN, f"Stage regression: {prev_stage} → {stage_after}")
        else:
            te.add("STAGE", Severity.PASS, f"Stage advanced: {prev_stage} → {stage_after}")
    elif stage_after:
        te.add("STAGE", Severity.PASS, f"Stage: {stage_after}")
    else:
        te.add("STAGE", Severity.INFO, f"Stage unchanged: {stage_before}")

    # ── 5. FIELD EXTRACTION ──────────────────────────────────────────────────
    ran_extraction = _has_field_collection_turns(turn_data)
    if ran_extraction:
        extracted = _extracted_user_fields(turn_data)
        if extracted:
            te.add("EXTRACTION", Severity.PASS, f"Extracted fields: {', '.join(extracted)}")
        else:
            # The LLM may legitimately extract nothing (e.g. a declination)
            te.add("EXTRACTION", Severity.INFO, "Field extraction ran but no user-supplied fields extracted")
    else:
        te.add("EXTRACTION", Severity.INFO, "Field extraction node not traced on this turn")

    # ── 6. CONFIRMATION CARD ─────────────────────────────────────────────────
    fields_complete = _all_user_fields_present(trace, turn_data)
    card_issued = _confirmation_card_issued(turn_data)
    if fields_complete and not card_issued:
        te.add(
            "CONFIRMATION",
            Severity.WARN,
            "All required fields appear present but no confirmation card signal detected in run outputs",
        )
    elif card_issued:
        te.add("CONFIRMATION", Severity.PASS, "Confirmation card issued")
    else:
        te.add("CONFIRMATION", Severity.INFO, "Fields not yet complete — no card expected")

    # ── 7. SUBMISSION ────────────────────────────────────────────────────────
    tool_names = [tc["tool_name"] for tc in (turn_data.get("tool_calls") or [])]
    if "service_request_api.create_service_request" in tool_names:
        # Check the tool call succeeded
        for tc in turn_data["tool_calls"]:
            if tc["tool_name"] == "service_request_api.create_service_request":
                if tc.get("success"):
                    ref_id = (tc.get("response_payload") or {}).get("id", "unknown")
                    te.add("SUBMISSION", Severity.PASS, f"SR submitted successfully — reference: {ref_id}")
                else:
                    te.add("SUBMISSION", Severity.FAIL, f"SR submission failed: {tc.get('error_message')}")

    return te


# ---------------------------------------------------------------------------
# Session-level evaluation
# ---------------------------------------------------------------------------


def evaluate_session(replay: dict[str, Any]) -> SessionEval:
    session_id = replay["session_id"]
    traces = replay["traces"]
    se = SessionEval(session_id=session_id, trace_count=len(traces))

    prev_stage: str | None = None
    for i, turn_data in enumerate(traces, start=1):
        te = evaluate_turn(i, turn_data, prev_stage)
        se.turns.append(te)
        # Advance tracked stage
        new_stage = turn_data["trace"].get("workflow_stage_after")
        if new_stage:
            prev_stage = new_stage

    return se


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_SEV_COLOUR = {
    Severity.PASS: "\033[32m",  # green
    Severity.INFO: "\033[36m",  # cyan
    Severity.WARN: "\033[33m",  # yellow
    Severity.FAIL: "\033[31m",  # red
}
_RESET = "\033[0m"


def _colour(sev: Severity, text: str, use_colour: bool) -> str:
    if not use_colour:
        return text
    return f"{_SEV_COLOUR[sev]}{text}{_RESET}"


def print_report(se: SessionEval, use_colour: bool = True) -> None:
    print()
    print("=" * 72)
    print(f"  SESSION EVALUATION REPORT")
    print(f"  Session : {se.session_id}")
    print(f"  Turns   : {se.trace_count}")
    print("=" * 72)

    for te in se.turns:
        worst = te.worst_severity
        header = _colour(worst, f"[{worst.value:4s}]", use_colour)
        print(f"\n{header}  Turn {te.turn_number:>2}  ←  \"{te.input_message[:60]}\"")
        print(f"         ↳  \"{te.output_message[:80]}\"")
        for chk in te.checks:
            tag = _colour(chk.severity, f"  {chk.severity.value:4s}", use_colour)
            print(f"{tag}  [{chk.name:12s}]  {chk.message}")

    summary = se.summary
    print()
    print("─" * 72)
    print("  SUMMARY")
    for sev in Severity:
        count = summary.get(sev.value, 0)
        if count:
            label = _colour(sev, f"{sev.value}: {count}", use_colour)
            print(f"    {label}")
    total_pass = summary.get("PASS", 0)
    total = se.trace_count
    print(f"    Turns passing all checks: {total_pass}/{total}")
    print("─" * 72)
    print()


def to_json_report(se: SessionEval) -> dict[str, Any]:
    return {
        "session_id": se.session_id,
        "trace_count": se.trace_count,
        "summary": se.summary,
        "turns": [
            {
                "turn": te.turn_number,
                "trace_id": te.trace_id,
                "input": te.input_message,
                "output": te.output_message,
                "worst_severity": te.worst_severity.value,
                "checks": [
                    {"name": c.name, "severity": c.severity.value, "message": c.message}
                    for c in te.checks
                ],
            }
            for te in se.turns
        ],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate agent traces for a chatbot session."
    )
    parser.add_argument(
        "--session-id",
        required=True,
        help="UUID of the chat session to evaluate",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Backend base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--output-json",
        metavar="FILE",
        help="Write JSON report to FILE",
    )
    parser.add_argument(
        "--no-colour",
        action="store_true",
        help="Disable ANSI colour output",
    )
    args = parser.parse_args()

    print(f"Fetching session replay for {args.session_id} …")
    replay = fetch_session_replay(args.session_id, args.base_url)

    se = evaluate_session(replay)
    print_report(se, use_colour=not args.no_colour)

    if args.output_json:
        report = to_json_report(se)
        with open(args.output_json, "w") as fh:
            json.dump(report, fh, indent=2)
        print(f"JSON report written to: {args.output_json}")


if __name__ == "__main__":
    main()
