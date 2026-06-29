#!/usr/bin/env python3
"""
report_writer.py — Compile all evaluation results into a detailed markdown report.

Reads:
  results/manual_block_results.json   — manual block runner output
  results/trace_eval_block_*.json     — per-session eval_session.py outputs
  results/run_eval_output.txt         — automated scenario suite output

Outputs:
  results/manual-test-eval-report-YYYY-MM-DD.md

Usage (from backend/ directory):

    python -m tests.eval.report_writer

    # Or with custom results directory
    python -m tests.eval.report_writer --results-dir /path/to/results
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional


# ── Helpers ───────────────────────────────────────────────────────────────────


def _pct(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "N/A"
    return f"{100 * numerator // denominator}%"


def _badge(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


def _sev_emoji(sev: str) -> str:
    return {"PASS": "✅", "INFO": "ℹ️", "WARN": "⚠️", "FAIL": "❌"}.get(sev, "❓")


def _ms_to_s(ms: Optional[int]) -> str:
    if ms is None:
        return "—"
    return f"{ms / 1000:.2f}s"


# ── Load data ─────────────────────────────────────────────────────────────────


def _load_manual_results(results_dir: Path) -> Optional[dict[str, Any]]:
    path = results_dir / "manual_block_results.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def _load_trace_evals(results_dir: Path) -> dict[str, dict]:
    """Load all trace_eval_block_*.json files into {filename_stem: data}."""
    out: dict[str, dict] = {}
    for p in sorted(results_dir.glob("trace_eval_block_*.json")):
        try:
            with open(p) as f:
                out[p.stem] = json.load(f)
        except Exception:
            pass
    return out


def _load_run_eval(results_dir: Path) -> Optional[str]:
    path = results_dir / "run_eval_output.txt"
    if not path.exists():
        return None
    return path.read_text()


def _parse_run_eval_summary(text: str) -> dict[str, Any]:
    """Extract pass/fail counts and scenario status from run_eval_output.txt."""
    summary: dict[str, Any] = {
        "scenarios": [],
        "scenarios_passed": 0,
        "scenarios_total": 0,
        "turns_passed": 0,
        "turns_total": 0,
        "slow_turns": [],
        "raw": text,
    }

    # Parse scenario lines like: "  Scenario 1  Happy Path (Lease Code Known)  [PASSED]"
    for m in re.finditer(r"Scenario\s+(\d+)\s+(.+?)\s+\[(PASSED|FAILED)\]", text):
        summary["scenarios"].append({
            "id": int(m.group(1)),
            "name": m.group(2).strip(),
            "passed": m.group(3) == "PASSED",
        })

    # Summary line: "3/9 scenarios passed"
    m_summary = re.search(r"(\d+)/(\d+) scenarios passed.*?(\d+)/(\d+) turns", text)
    if m_summary:
        summary["scenarios_passed"] = int(m_summary.group(1))
        summary["scenarios_total"] = int(m_summary.group(2))
        summary["turns_passed"] = int(m_summary.group(3))
        summary["turns_total"] = int(m_summary.group(4))

    # Slow turns
    for m in re.finditer(r"S(\d+) Turn (\d+) — (.+?): (\d+)ms", text):
        summary["slow_turns"].append({
            "scenario": int(m.group(1)),
            "turn": int(m.group(2)),
            "note": m.group(3),
            "latency_ms": int(m.group(4)),
        })

    return summary


# ── Report sections ───────────────────────────────────────────────────────────


def _section_executive_summary(
    manual: dict,
    trace_evals: dict[str, dict],
    run_eval_summary: Optional[dict],
    report_date: str,
) -> str:
    lines = [
        "# Manual Test Evaluation Report",
        f"**Generated:** {report_date}  ",
        f"**Backend:** FastAPI + LangGraph on `http://localhost:8000`  ",
        f"**Frontend:** Next.js on `http://localhost:3000`  ",
        f"**Authenticated as:** `aisha@cenomi.com` (role: MALL_MANAGER)  ",
        f"**Lease used:** `t0105712` — Brand Under Armour, Jawharat Jeddah, Unit FF050  ",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
    ]

    # Manual blocks
    blocks_passed = manual.get("blocks_passed", 0)
    blocks_total = manual.get("blocks_total", 0)
    elapsed = manual.get("elapsed_s", 0)
    run_date = manual.get("run_date", report_date)

    all_sessions = [s for b in manual.get("blocks", []) for s in b.get("sessions", [])]
    sessions_passed = sum(1 for s in all_sessions if s.get("passed"))
    sessions_total = len(all_sessions)

    test_turns = [
        t for b in manual.get("blocks", [])
        for s in b.get("sessions", [])
        for t in s.get("turns", [])
        if not t.get("is_setup")
    ]
    turns_passed = sum(1 for t in test_turns if t.get("passed"))
    turns_total = len(test_turns)

    latencies = [t["latency_ms"] for t in test_turns if t.get("latency_ms") and not t.get("http_error")]
    avg_latency = int(sum(latencies) / len(latencies)) if latencies else 0
    max_latency = max(latencies) if latencies else 0

    lines += [
        "### Manual Testing Blocks (12 blocks from `manual-testing-script.md`)",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Blocks passed | **{blocks_passed}/{blocks_total}** ({_pct(blocks_passed, blocks_total)}) |",
        f"| Sessions passed | {sessions_passed}/{sessions_total} ({_pct(sessions_passed, sessions_total)}) |",
        f"| Test turns passed | {turns_passed}/{turns_total} ({_pct(turns_passed, turns_total)}) |",
        f"| Avg latency (test turns) | {_ms_to_s(avg_latency)} |",
        f"| Max latency | {_ms_to_s(max_latency)} |",
        f"| Total runtime | {elapsed}s |",
        f"| Run date | {run_date} |",
        "",
    ]

    # Automated eval
    if run_eval_summary:
        sp = run_eval_summary["scenarios_passed"]
        st = run_eval_summary["scenarios_total"]
        tp = run_eval_summary["turns_passed"]
        tt = run_eval_summary["turns_total"]
        slow = len(run_eval_summary["slow_turns"])
        lines += [
            "### Automated Scenario Suite (`run_eval.py` — 9 scenarios)",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Scenarios passed | **{sp}/{st}** ({_pct(sp, st)}) |",
            f"| Turns passed | {tp}/{tt} ({_pct(tp, tt)}) |",
            f"| Slow turns (>12s) | {slow} |",
            "",
        ]

    # Trace observability
    if trace_evals:
        all_trace_turns = [
            t for data in trace_evals.values()
            for t in data.get("turns", [])
        ]
        trace_fail = sum(1 for t in all_trace_turns if t.get("worst_severity") == "FAIL")
        trace_warn = sum(1 for t in all_trace_turns if t.get("worst_severity") == "WARN")
        trace_pass = sum(1 for t in all_trace_turns if t.get("worst_severity") == "PASS")

        lines += [
            "### Observability Trace Analysis",
            "",
            f"| Severity | Count |",
            f"|----------|-------|",
            f"| ✅ PASS | {trace_pass} turns |",
            f"| ⚠️ WARN | {trace_warn} turns |",
            f"| ❌ FAIL | {trace_fail} turns |",
            f"| Sessions scored | {len(trace_evals)} |",
            "",
        ]

    # Critical failures callout
    critical = [
        f"Block {b['block_id']} ({b['name']})"
        for b in manual.get("blocks", [])
        if not b.get("passed")
    ]
    if critical:
        lines += [
            "> **Critical Failures:** " + ", ".join(critical),
            "",
        ]
    else:
        lines += [
            "> ✅ All manual test blocks passed.",
            "",
        ]

    return "\n".join(lines)


def _section_block_results(manual: dict) -> str:
    lines = [
        "---",
        "",
        "## Block-by-Block Results",
        "",
        "| Block | Name | Sessions | Turns (pass/total) | Result | Session ID(s) |",
        "|-------|------|----------|--------------------|--------|---------------|",
    ]

    for b in manual.get("blocks", []):
        sessions = b.get("sessions", [])
        all_session_ids = b.get("session_ids", [])
        sess_pass = sum(1 for s in sessions if s.get("passed"))
        sess_total = len(sessions)
        turns_pass = sum(s.get("turns_passed", 0) for s in sessions)
        turns_total = sum(s.get("turns_total", 0) for s in sessions)
        result = "✅ PASS" if b.get("passed") else "❌ FAIL"
        session_ids_short = "<br>".join(
            f"`{sid[:8]}…`" for sid in all_session_ids
        ) if all_session_ids else "—"

        lines.append(
            f"| {b['block_id']} | {b['name']} | {sess_pass}/{sess_total} | "
            f"{turns_pass}/{turns_total} | {result} | {session_ids_short} |"
        )

    lines += [""]
    return "\n".join(lines)


def _section_block_details(manual: dict) -> str:
    lines = ["---", "", "## Block Detail — Turn-by-Turn Analysis", ""]

    for b in manual.get("blocks", []):
        blk_status = "✅" if b.get("passed") else "❌"
        lines += [
            f"### {blk_status} Block {b['block_id']}: {b['name']}",
            "",
            f"> {b.get('description', '')}",
            "",
        ]

        for s in b.get("sessions", []):
            sess_status = "✅" if s.get("passed") else "❌"
            lines += [
                f"**{sess_status} Session: {s['name']}**  ",
                f"Session ID: `{s.get('session_id', 'N/A')}`  ",
                f"Turns: {s.get('turns_passed', 0)}/{s.get('turns_total', 0)} passed  ",
                "",
                "| Turn | Input | Note | Latency | UI Type | Stage | Result | Details |",
                "|------|-------|------|---------|---------|-------|--------|---------|",
            ]

            for t in s.get("turns", []):
                if t.get("is_setup"):
                    continue
                result_icon = "✅" if t.get("passed") else "❌"
                latency = _ms_to_s(t.get("latency_ms"))
                msg = t.get("message", "")[:60].replace("|", "\\|").replace("\n", " ")
                if not msg and t.get("action"):
                    msg = f"[action={t['action']}]"
                if not msg and t.get("corrected_fields"):
                    msg = f"[corrected_fields]"
                note = t.get("note", "")[:60].replace("|", "\\|")
                ui_type = t.get("ui_type") or "—"
                stage = t.get("workflow_stage") or "—"
                http_err = t.get("http_error")

                details_parts = []
                if http_err:
                    details_parts.append(f"❌ {http_err[:80]}")
                for f_msg in (t.get("failures") or []):
                    details_parts.append(f"FAIL: {f_msg[:80]}")
                for w_msg in (t.get("warnings") or []):
                    details_parts.append(f"WARN: {w_msg[:80]}")
                details = "<br>".join(details_parts) if details_parts else "—"

                lines.append(
                    f"| {t['turn_idx']} | `{msg}` | {note} | {latency} | "
                    f"`{ui_type}` | `{stage}` | {result_icon} | {details} |"
                )

            # Show bot responses for failed turns
            failed_turns = [t for t in s.get("turns", []) if not t.get("passed") and not t.get("is_setup")]
            if failed_turns:
                lines += ["", "**Failed turn responses:**", ""]
                for t in failed_turns[:3]:  # cap at 3 for brevity
                    resp = (t.get("response_message") or "")[:300]
                    lines += [
                        f"> **Turn {t['turn_idx']}** — `{(t.get('message') or '')[:60]}`",
                        f"> Bot: {resp}",
                        "",
                    ]

            lines += [""]

    return "\n".join(lines)


def _section_observability_traces(trace_evals: dict[str, dict], manual: dict) -> str:
    if not trace_evals:
        return (
            "---\n\n"
            "## Observability Trace Analysis\n\n"
            "> No trace eval files found. Run `eval_session.py` for each session "
            "to generate trace analysis.\n"
        )

    lines = [
        "---",
        "",
        "## Observability Trace Analysis",
        "",
        "Traces were scored via `eval_session.py` using the following criteria:",
        "",
        "| # | Criterion | Description |",
        "|---|-----------|-------------|",
        "| 1 | STATUS | Trace completed with SUCCESS status |",
        "| 2 | LATENCY | Turn latency ≤ 5000ms |",
        "| 3 | INTENT | No UNKNOWN intent on active agent turns |",
        "| 4 | STAGE | Workflow stage does not regress |",
        "| 5 | EXTRACTION | Fields extracted when field_extraction node ran |",
        "| 6 | CONFIRMATION | Confirmation card issued when all required fields present |",
        "| 7 | SUBMISSION | SR submitted with valid reference UUID |",
        "",
    ]

    # Build a lookup: session_id → block name
    session_to_block: dict[str, str] = {}
    for b in manual.get("blocks", []):
        for sid in b.get("session_ids", []):
            session_to_block[sid] = f"Block {b['block_id']}: {b['name']}"

    for stem, data in sorted(trace_evals.items()):
        session_id = data.get("session_id", "unknown")
        block_label = session_to_block.get(session_id, "Unknown block")
        trace_count = data.get("trace_count", 0)
        summary = data.get("summary", {})

        lines += [
            f"### Session: `{session_id[:8]}…`",
            f"**Block:** {block_label}  ",
            f"**Turns recorded:** {trace_count}  ",
            f"**Summary:** "
            f"✅ {summary.get('PASS', 0)} PASS | "
            f"ℹ️ {summary.get('INFO', 0)} INFO | "
            f"⚠️ {summary.get('WARN', 0)} WARN | "
            f"❌ {summary.get('FAIL', 0)} FAIL",
            "",
            "| Turn | Input | Worst | STATUS | LATENCY | INTENT | STAGE | EXTRACTION | CONFIRMATION |",
            "|------|-------|-------|--------|---------|--------|-------|------------|-------------|",
        ]

        for turn in data.get("turns", []):
            t_num = turn.get("turn", "?")
            inp = (turn.get("input") or "")[:50].replace("|", "\\|")
            worst = _sev_emoji(turn.get("worst_severity", "INFO"))

            checks = {c["name"]: c for c in (turn.get("checks") or [])}

            def _check_cell(name: str) -> str:
                c = checks.get(name)
                if not c:
                    return "—"
                return _sev_emoji(c["severity"])

            lines.append(
                f"| {t_num} | `{inp}` | {worst} | "
                f"{_check_cell('STATUS')} | {_check_cell('LATENCY')} | "
                f"{_check_cell('INTENT')} | {_check_cell('STAGE')} | "
                f"{_check_cell('EXTRACTION')} | {_check_cell('CONFIRMATION')} |"
            )

        # Detail on FAIL/WARN checks
        fail_warn_turns = [
            t for t in data.get("turns", [])
            if t.get("worst_severity") in ("FAIL", "WARN")
        ]
        if fail_warn_turns:
            lines += ["", "**Issues:**", ""]
            for t in fail_warn_turns:
                for c in (t.get("checks") or []):
                    if c["severity"] in ("FAIL", "WARN"):
                        lines.append(
                            f"- Turn {t['turn']} [{c['severity']}] `{c['name']}`: {c['message']}"
                        )

        lines += [""]

    return "\n".join(lines)


def _section_automated_eval(run_eval_summary: Optional[dict]) -> str:
    if not run_eval_summary:
        return (
            "---\n\n"
            "## Automated Scenario Suite Results\n\n"
            "> `results/run_eval_output.txt` not found. "
            "Run `python -m tests.eval.run_eval --verbose > results/run_eval_output.txt`\n"
        )

    lines = [
        "---",
        "",
        "## Automated Scenario Suite Results",
        "",
        f"**Source:** `results/run_eval_output.txt`  ",
        "",
        "| # | Scenario | Result |",
        "|---|----------|--------|",
    ]

    for sc in run_eval_summary.get("scenarios", []):
        icon = "✅" if sc["passed"] else "❌"
        lines.append(f"| {sc['id']} | {sc['name']} | {icon} |")

    sp = run_eval_summary["scenarios_passed"]
    st = run_eval_summary["scenarios_total"]
    tp = run_eval_summary["turns_passed"]
    tt = run_eval_summary["turns_total"]

    lines += [
        "",
        f"**Result:** {sp}/{st} scenarios passed ({_pct(sp, st)}), "
        f"{tp}/{tt} turns passed ({_pct(tp, tt)})",
        "",
    ]

    if run_eval_summary["slow_turns"]:
        lines += ["**Slow turns (>12s):**", ""]
        for st_item in run_eval_summary["slow_turns"]:
            lines.append(
                f"- Scenario {st_item['scenario']} Turn {st_item['turn']} — "
                f"{st_item['note']}: `{_ms_to_s(st_item['latency_ms'])}`"
            )
        lines += [""]

    return "\n".join(lines)


def _section_failures_and_warnings(manual: dict, trace_evals: dict[str, dict]) -> str:
    lines = [
        "---",
        "",
        "## Failures & Warnings Detail",
        "",
    ]

    # From manual blocks
    hard_failures = []
    soft_warnings = []

    for b in manual.get("blocks", []):
        for s in b.get("sessions", []):
            for t in s.get("turns", []):
                if t.get("is_setup"):
                    continue
                ctx = f"Block {b['block_id']} / {s['name']} / Turn {t['turn_idx']}"
                for f_msg in (t.get("failures") or []):
                    hard_failures.append((ctx, t.get("message", "")[:60], f_msg))
                for w_msg in (t.get("warnings") or []):
                    soft_warnings.append((ctx, t.get("message", "")[:60], w_msg))

    if hard_failures:
        lines += ["### Hard Failures (blocked turns)", ""]
        lines.append("| Context | User Input | Failure |")
        lines.append("|---------|------------|---------|")
        for ctx, msg, fail in hard_failures:
            lines.append(f"| {ctx} | `{msg}` | {fail} |")
        lines += [""]
    else:
        lines += ["### Hard Failures\n\n> ✅ No hard failures.\n"]

    if soft_warnings:
        lines += ["### Soft Warnings (non-blocking)", ""]
        lines.append("| Context | User Input | Warning |")
        lines.append("|---------|------------|---------|")
        for ctx, msg, warn in soft_warnings[:40]:  # cap for readability
            lines.append(f"| {ctx} | `{msg}` | {warn[:120]} |")
        if len(soft_warnings) > 40:
            lines.append(f"| _(+{len(soft_warnings)-40} more)_ | | |")
        lines += [""]
    else:
        lines += ["### Soft Warnings\n\n> ✅ No soft warnings.\n"]

    # From trace evals
    trace_issues = []
    for stem, data in trace_evals.items():
        session_id = data.get("session_id", "?")
        for turn in data.get("turns", []):
            for c in (turn.get("checks") or []):
                if c["severity"] in ("FAIL", "WARN"):
                    trace_issues.append({
                        "session": session_id[:8] + "…",
                        "turn": turn.get("turn"),
                        "input": (turn.get("input") or "")[:60],
                        "criterion": c["name"],
                        "severity": c["severity"],
                        "message": c["message"],
                    })

    if trace_issues:
        lines += ["### Observability Trace Issues", ""]
        lines.append("| Session | Turn | Input | Criterion | Severity | Message |")
        lines.append("|---------|------|-------|-----------|----------|---------|")
        for issue in trace_issues[:50]:
            lines.append(
                f"| `{issue['session']}` | {issue['turn']} | "
                f"`{issue['input']}` | {issue['criterion']} | "
                f"{issue['severity']} | {issue['message'][:100]} |"
            )
        lines += [""]

    return "\n".join(lines)


def _section_response_quality(manual: dict) -> str:
    lines = [
        "---",
        "",
        "## Response Quality Observations",
        "",
    ]

    # Keyword match rates per block
    lines += [
        "### Keyword Match Rate by Block",
        "",
        "| Block | Test Turns | Keyword Warnings | Match Rate |",
        "|-------|------------|-----------------|------------|",
    ]

    for b in manual.get("blocks", []):
        test_turns = [
            t
            for s in b.get("sessions", [])
            for t in s.get("turns", [])
            if not t.get("is_setup")
        ]
        keyword_turns = [
            t for t in test_turns
            if any(
                "Keywords" in w or "keyword" in w.lower()
                for w in (t.get("warnings") or [])
            )
        ]
        match_rate = _pct(
            len(test_turns) - len(keyword_turns), len(test_turns)
        ) if test_turns else "N/A"
        lines.append(
            f"| Block {b['block_id']}: {b['name']} | {len(test_turns)} | "
            f"{len(keyword_turns)} | {match_rate} |"
        )

    # Latency analysis
    all_latencies = [
        (b["block_id"], b["name"], t["latency_ms"])
        for b in manual.get("blocks", [])
        for s in b.get("sessions", [])
        for t in s.get("turns", [])
        if not t.get("is_setup") and t.get("latency_ms") and not t.get("http_error")
    ]

    if all_latencies:
        avg = int(sum(l for _, _, l in all_latencies) / len(all_latencies))
        max_item = max(all_latencies, key=lambda x: x[2])
        min_item = min(all_latencies, key=lambda x: x[2])
        slow = [(bid, bname, lat) for bid, bname, lat in all_latencies if lat > 12000]

        lines += [
            "",
            "### Latency Distribution",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Average | {_ms_to_s(avg)} |",
            f"| Maximum | {_ms_to_s(max_item[2])} (Block {max_item[0]}: {max_item[1]}) |",
            f"| Minimum | {_ms_to_s(min_item[2])} (Block {min_item[0]}: {min_item[1]}) |",
            f"| Slow turns (>12s) | {len(slow)} |",
            "",
        ]

        if slow:
            lines += ["**Slow turns:**", ""]
            for bid, bname, lat in sorted(slow, key=lambda x: -x[2]):
                lines.append(f"- Block {bid} ({bname}): `{_ms_to_s(lat)}`")
            lines += [""]

    # UI type distribution
    ui_counts: dict[str, int] = {}
    for b in manual.get("blocks", []):
        for s in b.get("sessions", []):
            for t in s.get("turns", []):
                if not t.get("is_setup"):
                    ui = t.get("ui_type") or "unknown"
                    ui_counts[ui] = ui_counts.get(ui, 0) + 1

    if ui_counts:
        lines += [
            "### UI Type Distribution (test turns)",
            "",
            "| UI Type | Count |",
            "|---------|-------|",
        ]
        for ui, count in sorted(ui_counts.items(), key=lambda x: -x[1]):
            lines.append(f"| `{ui}` | {count} |")
        lines += [""]

    return "\n".join(lines)


def _section_recommendations(manual: dict, run_eval_summary: Optional[dict]) -> str:
    lines = [
        "---",
        "",
        "## Recommendations",
        "",
    ]

    recs: list[str] = []

    # Check for failed blocks
    failed_blocks = [b for b in manual.get("blocks", []) if not b.get("passed")]
    if failed_blocks:
        for b in failed_blocks:
            failed_sessions = [s for s in b.get("sessions", []) if not s.get("passed")]
            for s in failed_sessions:
                hard_fails = [
                    t for t in s.get("turns", [])
                    if not t.get("is_setup") and t.get("failures")
                ]
                for t in hard_fails[:2]:
                    fail_msg = t["failures"][0] if t["failures"] else "unknown"
                    recs.append(
                        f"**[Block {b['block_id']} — {s['name']}]** Fix assertion: "
                        f"`{fail_msg}` on turn {t['turn_idx']} "
                        f"(input: `{(t.get('message') or '')[:60]}`)"
                    )

    # Check for keyword warnings
    kw_blocks = []
    for b in manual.get("blocks", []):
        test_turns = [
            t for s in b.get("sessions", [])
            for t in s.get("turns", [])
            if not t.get("is_setup")
        ]
        kw_warns = [
            t for t in test_turns
            if any("Keywords" in w for w in (t.get("warnings") or []))
        ]
        if len(kw_warns) > len(test_turns) // 2 and test_turns:
            kw_blocks.append(f"Block {b['block_id']} ({b['name']})")

    if kw_blocks:
        recs.append(
            f"**[Response Phrasing]** Multiple keyword mismatches in: "
            f"{', '.join(kw_blocks)}. Consider updating expected keyword lists "
            f"to match the bot's current phrasing."
        )

    # Slow turns
    slow_turns = [
        t for b in manual.get("blocks", [])
        for s in b.get("sessions", [])
        for t in s.get("turns", [])
        if not t.get("is_setup") and t.get("latency_ms", 0) > 12000
    ]
    if len(slow_turns) >= 3:
        recs.append(
            f"**[Performance]** {len(slow_turns)} turns exceeded 12s latency. "
            f"Consider reviewing LLM model selection, prompt length, or adding "
            f"streaming responses to improve perceived responsiveness."
        )

    # Run eval failures
    if run_eval_summary:
        sp = run_eval_summary["scenarios_passed"]
        st = run_eval_summary["scenarios_total"]
        if sp < st:
            failed_sc = [sc for sc in run_eval_summary["scenarios"] if not sc["passed"]]
            sc_names = ", ".join(f"S{sc['id']} ({sc['name']})" for sc in failed_sc[:3])
            recs.append(
                f"**[Automated Eval]** {st - sp} automated scenarios failed: {sc_names}. "
                f"Review `results/run_eval_output.txt` for detailed turn failures."
            )

    # Check for missing lease_selection for Nike
    b6_sessions = next(
        (b.get("sessions", []) for b in manual.get("blocks", []) if b["block_id"] == 6),
        [],
    )
    for s in b6_sessions:
        if "Nike" in s.get("name", ""):
            failed = any(not t.get("passed") for t in s.get("turns", []) if not t.get("is_setup"))
            if failed:
                recs.append(
                    "**[Lease Lookup]** Nike multi-lease selection card not shown — "
                    "verify Nike leases are seeded in the database "
                    "(`python scripts/seed_users.py` or check mock data setup)."
                )

    if not recs:
        recs.append("✅ All tests passed. No action items identified.")

    for i, rec in enumerate(recs, start=1):
        lines.append(f"{i}. {rec}")

    lines += [""]
    return "\n".join(lines)


def _section_observability_admin_link() -> str:
    return (
        "---\n\n"
        "## Observability Admin Panel\n\n"
        "All test sessions are visible in the agent observability UI:\n\n"
        "- **URL:** [http://localhost:3000/admin/agent-observability](http://localhost:3000/admin/agent-observability)\n"
        "- Filter by session ID to trace each block's conversation\n"
        "- Each trace shows: LLM calls, tool calls, state snapshots, field extractions, "
        "intent classification, stage progression\n"
        "- The `PAYLOAD_BUILDER_OUTPUT` snapshot shows the exact JSON payload sent to the SR API\n"
    )


def _section_raw_run_eval(run_eval_text: Optional[str]) -> str:
    if not run_eval_text:
        return ""
    return (
        "---\n\n"
        "## Appendix — Automated Eval Raw Output\n\n"
        "<details>\n<summary>Click to expand raw run_eval output</summary>\n\n"
        f"```\n{run_eval_text[:8000]}\n```\n\n"
        "</details>\n"
    )


# ── Main ──────────────────────────────────────────────────────────────────────


def generate_report(results_dir: Path) -> str:
    manual = _load_manual_results(results_dir)
    trace_evals = _load_trace_evals(results_dir)
    run_eval_text = _load_run_eval(results_dir)
    run_eval_summary = _parse_run_eval_summary(run_eval_text) if run_eval_text else None
    report_date = datetime.now().strftime("%Y-%m-%d %H:%M")

    if manual is None:
        print(
            "ERROR: results/manual_block_results.json not found. "
            "Run test_manual_blocks.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    sections = [
        _section_executive_summary(manual, trace_evals, run_eval_summary, report_date),
        _section_block_results(manual),
        _section_block_details(manual),
        _section_observability_traces(trace_evals, manual),
        _section_automated_eval(run_eval_summary),
        _section_response_quality(manual),
        _section_failures_and_warnings(manual, trace_evals),
        _section_recommendations(manual, run_eval_summary),
        _section_observability_admin_link(),
        _section_raw_run_eval(run_eval_text),
    ]

    return "\n".join(sections)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compile evaluation results into a detailed markdown report."
    )
    parser.add_argument(
        "--results-dir",
        default=None,
        metavar="DIR",
        help="Path to results directory (default: auto-detected from script location)",
    )
    args = parser.parse_args()

    if args.results_dir:
        results_dir = Path(args.results_dir)
    else:
        results_dir = Path(__file__).parent.parent.parent.parent / "results"

    if not results_dir.exists():
        print(f"ERROR: Results directory not found: {results_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading results from: {results_dir}")

    manual = _load_manual_results(results_dir)
    trace_evals = _load_trace_evals(results_dir)
    run_eval_text = _load_run_eval(results_dir)

    print(f"  manual_block_results.json: {'✓' if manual else '✗ not found'}")
    print(f"  trace_eval_block_*.json:   {len(trace_evals)} file(s)")
    print(f"  run_eval_output.txt:       {'✓' if run_eval_text else '✗ not found'}")
    print()

    report = generate_report(results_dir)

    run_date = date.today().isoformat()
    out_path = results_dir / f"manual-test-eval-report-{run_date}.md"
    out_path.write_text(report, encoding="utf-8")

    print(f"Report written to: {out_path}")
    print(f"  Size: {len(report):,} bytes")


if __name__ == "__main__":
    main()
