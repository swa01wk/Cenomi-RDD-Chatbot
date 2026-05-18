"""LLM prompt for the response generation node.

This is the only place in the graph where the assistant's voice is composed.
Every other node sets machine-readable signals; this node turns those signals
into a natural, context-aware message for the user.
"""

# ---------------------------------------------------------------------------
# Field name → human-readable label mapping (never expose raw field keys)
# ---------------------------------------------------------------------------

FIELD_LABELS: dict[str, str] = {
    "lease_code": "lease code",
    "lease_brand_mall": "lease, brand, or mall",
    "title": "title",
    "description": "description",
    "startDate": "inspection start date",
    "endDate": "inspection end date",
    "inspection_done_by": "who will perform the inspection (FM Manager or Operations)",
    "comments": "comments",
    "unit_readiness_date": "unit readiness date",
    "expected_handover_date": "expected handover date",
    "guideLineLink": "guideline link",
    "actual_handover_date": "actual handover date",
    "fitout_start_date": "fitout start date",
    "fitout_end_date": "fitout end date",
    "trading_date": "trading date",
    "brand": "brand name",
    "mall": "mall name",
    "city": "city",
    "unit_codes": "unit codes",
    "contracted_area": "contracted area",
}

# ---------------------------------------------------------------------------
# Stage descriptions
# ---------------------------------------------------------------------------

STAGE_DESCRIPTIONS: dict[str, str] = {
    "CREATE_SR": "creating a new Handover Service Request",
    "FM_REVIEW": "FM Manager review of the handover",
    "RDD_REVIEW": "RDD Engineer review and final sign-off",
}

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

RESPONSE_GENERATION_SYSTEM_PROMPT = """
You are a professional, warm, and concise assistant for the Cenomi Malls Service Request platform.
You help mall managers and operations staff create and manage Handover Service Requests for tenant fit-outs.

════════════════════════════════════════════════════════
YOUR ROLE IN THIS TURN
════════════════════════════════════════════════════════

You receive structured context about what just happened in the workflow and your
job is to compose a single, natural reply that the user sees in the chat UI.

════════════════════════════════════════════════════════
TONE AND STYLE RULES
════════════════════════════════════════════════════════

- Be conversational and professional — like a knowledgeable colleague, not a form wizard.
- Be concise: 1–3 sentences for most replies. Do not pad with filler phrases.
- Personalise using real names from the context (brand, mall, lease code) when available.
- Acknowledge progress: if data was just collected, briefly confirm it before asking for the next item.
- Ask only ONE question per turn. Never list multiple questions at once.
- When there are VALIDATION ISSUES in the context, focus EXCLUSIVELY on the
  validation error. Do NOT also ask for missing fields in the same message.
  Address the invalid value first; the user can provide the remaining fields
  after the error is resolved.
- When a lease is found, celebrate it briefly then move on (e.g. "Got it — found your [Brand] lease at [Mall].").
- When something goes wrong, be empathetic and specific about what to try.
- Never mention internal field names like `startDate`, `tenant_profile_id`, `brand_id`, etc.
  Always use their plain English equivalents from the context you are given.
- Never reveal workflow internals (node names, stages, status codes).
- If the user is confirming or cancelling, acknowledge their choice warmly.

════════════════════════════════════════════════════════
OUTPUT FORMAT — STRICT
════════════════════════════════════════════════════════

Return ONLY a JSON object with exactly one key:

  {"message": "<your natural language response here>"}

Do NOT include markdown, extra keys, or any text outside the JSON object.
""".strip()


def build_response_generation_context(
    *,
    user_message: str,
    response_intent: str,
    workflow_stage: str | None,
    intent: str | None,
    collected_data: dict,
    missing_fields: list[str],
    validation_errors: list[dict],
    confirmation_status: str | None,
    response_ui_type: str | None,
    conversation_history: list[dict],
) -> str:
    """Build the user-content string sent to the LLM for response generation."""

    lines: list[str] = []

    # ── 1. What the system determined needs to be communicated ──────────────
    lines.append("## WHAT TO COMMUNICATE TO THE USER")
    lines.append(response_intent or "Continue the conversation naturally.")
    lines.append("")

    # ── 2. Workflow context ──────────────────────────────────────────────────
    lines.append("## WORKFLOW CONTEXT")
    stage_label = STAGE_DESCRIPTIONS.get(workflow_stage or "", workflow_stage or "unknown")
    lines.append(f"Current task: {stage_label}")
    if intent:
        lines.append(f"User intent: {intent.replace('_', ' ').title()}")
    if confirmation_status:
        lines.append(f"Confirmation status: {confirmation_status}")
    if response_ui_type:
        lines.append(f"UI component being shown: {response_ui_type}")
    lines.append("")

    # ── 3. Data collected so far ─────────────────────────────────────────────
    if collected_data:
        readable_data: dict[str, str] = {}
        for k, v in collected_data.items():
            if v is None or v == "" or v == []:
                continue
            label = FIELD_LABELS.get(k, k)
            readable_data[label] = str(v) if not isinstance(v, list) else ", ".join(str(i) for i in v)
        if readable_data:
            lines.append("## DATA COLLECTED SO FAR")
            for label, val in readable_data.items():
                lines.append(f"- {label}: {val}")
            lines.append("")

    # ── 4. Still missing ─────────────────────────────────────────────────────
    # Suppress missing fields when there are blocking validation errors so the
    # response LLM focuses exclusively on asking the user to fix the invalid
    # value rather than also asking for other fields.
    if missing_fields and not validation_errors:
        # Fields that are never user-supplied: backend-derived IDs and
        # ``title`` which is auto-generated from lease_code + description.
        # Showing ``title`` here causes the LLM to hallucinate draft titles in
        # free-form text, which misleads users into thinking the value was
        # accepted when it was never stored in the collected draft.
        _non_user_fields = {
            "tenant_profile_id", "property_id", "lease_id", "brand_id",
            "contract_id", "unit_codes", "city", "contracted_area",
            "lease_brand_mall", "lease", "mall", "brand",
            "title",  # auto-generated — never collected from the user
        }
        user_facing_missing = [
            FIELD_LABELS.get(f, f) for f in missing_fields
            if f not in _non_user_fields
        ]
        if user_facing_missing:
            lines.append("## STILL NEEDED FROM USER")
            for field_label in user_facing_missing:
                lines.append(f"- {field_label}")
            lines.append("")

    # ── 5. Validation errors ─────────────────────────────────────────────────
    if validation_errors:
        lines.append("## VALIDATION ISSUES")
        for err in validation_errors:
            field_label = FIELD_LABELS.get(err.get("field", ""), err.get("field", "unknown field"))
            lines.append(f"- {field_label}: {err.get('message', 'invalid value')}")
        lines.append("")

    # ── 6. User's current message ────────────────────────────────────────────
    lines.append("## USER'S CURRENT MESSAGE")
    lines.append(f'"{user_message}"')
    lines.append("")

    # ── 7. Recent conversation history ───────────────────────────────────────
    if conversation_history:
        lines.append("## CONVERSATION SO FAR (oldest first)")
        for turn in conversation_history[-8:]:
            role = turn.get("role", "unknown").capitalize()
            content = turn.get("content", "")
            if content:
                lines.append(f"{role}: {content}")
        lines.append("")

    lines.append(
        "Now write a single natural reply for the assistant. "
        "Respond ONLY with: {\"message\": \"<your reply>\"}"
    )

    return "\n".join(lines)
