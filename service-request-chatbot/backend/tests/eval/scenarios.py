"""All 9 evaluation scenarios from docs/e2e-test-guide.md.

Each scenario models the exact conversation turns described in the guide.
Assertions are split into:
  - Hard checks  (ui_type, workflow_stage) — failure stops the scenario.
  - Soft checks  (keywords)                — failure adds a warning only.

Mock data leases (from the guide):
  t0105712  Under Armour  Jawharat Jeddah   Jeddah   FF050      420 sqm
  t0208831  Nike          Riyadh Park       Riyadh   GF101/102  680 sqm
  t0301144  Nike          Mall of Arabia    Jeddah   LG220      510 sqm
  t0419977  Zara          Dubai Festival City  Dubai  UF301      900 sqm

UI type notes:
  The backend response_generation node emits TWO distinct conversational types:
    "message"       — general/greeting/clarification messages (no specific input expected)
    "text_question" — targeted prompts asking for a single user-supplied value
  Both are "normal" conversational turns. The test guide uses "message" for both
  (documentation gap), so scenario turns that collect field data do NOT assert
  expect_ui_type.  Only the structurally significant UI cards are asserted:
    "lease_selection"  — multiple lease matches found
    "confirmation_card" — all fields collected; awaiting user confirmation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Turn:
    """A single user message in a scenario, plus assertions on the response."""

    message: str
    note: str = ""

    # ── Hard assertions (failures stop the scenario) ──────────────────────────
    expect_ui_type: Optional[str] = None
    """Expected value of response.ui.type. None = skip check."""

    expect_workflow_stage: Optional[str] = None
    """Expected value of response.state.workflow_stage. None = skip check."""

    # ── Soft assertions (failures produce warnings only) ──────────────────────
    expect_keywords: list[str] = field(default_factory=list)
    """At least one keyword must appear (case-insensitive) in response.message."""

    expect_no_submit: bool = False
    """Assert that state.ready_to_submit is False (error / pre-submit turn)."""

    # ── Extra API payload fields (advanced scenarios) ─────────────────────────
    action: Optional[str] = None
    """Optional action field: 'confirm' or 'cancel'."""

    corrected_fields: Optional[dict] = None
    """Optional corrected_fields dict for inline card edits."""

    selected_lease_id: Optional[str] = None
    """Optional selected_lease_id for lease selection card API scenarios."""

    # ── Extra soft assertions ─────────────────────────────────────────────────
    expect_no_active_agent: bool = False
    """Soft: assert that response.active_agent is null/empty after a reset."""

    expect_field_value: Optional[dict] = None
    """Soft: {label: expected_value} — check ui.fields entries on a confirmation_card."""


@dataclass
class Scenario:
    id: int
    name: str
    goal: str
    turns: list[Turn]
    enabled: bool = True
    tags: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 1 — Happy Path (Lease Code Known)
# ─────────────────────────────────────────────────────────────────────────────
_S1 = Scenario(
    id=1,
    name="Happy Path (Lease Code Known)",
    goal="Full flow: intent → lease resolution → 6 field turns → confirmation card → submission",
    turns=[
        Turn(
            message="I want to create a handover service request",
            note="Bot should ask for lease code, brand, or mall name",
        ),
        Turn(
            message="t0105712",
            note="Lease auto-resolved (Under Armour, Jawharat Jeddah); bot asks for title",
        ),
        Turn(
            message="Handover Inspection – UA FF050",
            note="Title accepted; bot asks for description",
        ),
        Turn(
            message="Standard fit-out inspection for new tenant unit",
            note="Description accepted; bot asks for start date",
        ),
        Turn(
            message="2026-06-01",
            note="Start date accepted; bot asks for end date",
        ),
        Turn(
            message="2026-06-03",
            note="End date accepted; bot asks for inspection done by",
        ),
        Turn(
            message="FM Manager",
            note="Inspection done by accepted; bot asks for comments",
        ),
        Turn(
            message="Hard opening date June 5, please prioritise",
            note="All fields collected; confirmation card must be shown",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            message="Confirm",
            note="SR submitted; response contains UUID reference and SR_CREATED stage",
            expect_workflow_stage="SR_CREATED",
            expect_keywords=["reference", "submitted", "successfully", "created"],
        ),
    ],
    tags=["happy-path", "core"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 2 — Brand + Mall Search (No Lease Code)
# ─────────────────────────────────────────────────────────────────────────────
_S2 = Scenario(
    id=2,
    name="Brand + Mall Search (No Lease Code)",
    goal="Test free-text lease search and multi-match selection card for Nike",
    turns=[
        Turn(
            message="I need to raise a handover request for Nike",
            note="Lease lookup finds 2 Nike leases; lease_selection card must appear",
            expect_ui_type="lease_selection",
        ),
        Turn(
            message="Nike Riyadh Park",
            note="User selects Nike Riyadh Park via text; lease auto-filled, bot asks for title",
        ),
        Turn(
            message="Nike Riyadh Park Inspection",
            note="Title accepted; bot asks for description",
        ),
        Turn(
            message="Inspection for Nike flagship unit at Riyadh Park mall",
            note="Description accepted; bot asks for start date",
        ),
        Turn(
            message="2026-07-10",
            note="Start date accepted; bot asks for end date",
        ),
        Turn(
            message="2026-07-12",
            note="End date accepted; bot asks for inspection done by",
        ),
        Turn(
            message="Operations",
            note="Inspection done by accepted; bot asks for comments",
        ),
        Turn(
            message="Tenant has requested early access from July 9",
            note="All fields collected; confirmation card must be shown",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            message="Yes, confirm and submit",
            note="SR submitted successfully",
            expect_workflow_stage="SR_CREATED",
            expect_keywords=["reference", "submitted", "successfully", "created"],
        ),
    ],
    tags=["lease-search", "multi-match"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 3 — Full Details in One Message
# ─────────────────────────────────────────────────────────────────────────────
_S3 = Scenario(
    id=3,
    name="Full Details in One Message",
    goal=(
        "Verify the LLM extracts lease_code, title, startDate, endDate, and "
        "inspection_done_by from a single long message, then only asks for what's missing"
    ),
    turns=[
        Turn(
            message=(
                "Create a handover service request for lease t0419977 — Zara at Dubai Festival City. "
                "Title: Zara UF301 Handover Inspection. The inspection will run from June 10 to "
                "June 12 2026 and will be done by FM Manager."
            ),
            note=(
                "LLM should extract 5 fields at once; lease resolved; "
                "bot asks only for what's still missing (description)"
            ),
            expect_keywords=["description"],
        ),
        Turn(
            message="New tenant fit-out handover for Zara flagship unit UF301",
            note="Description accepted; bot asks for comments (last missing field)",
        ),
        Turn(
            message="No additional comments",
            note="'No additional comments' treated as valid comments value; confirmation card shown",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            message="Submit",
            note="SR submitted successfully",
            expect_workflow_stage="SR_CREATED",
            expect_keywords=["reference", "submitted", "successfully", "created"],
        ),
    ],
    tags=["multi-field-extraction", "core"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 4 — Mall Name Only (Partial Search)
# ─────────────────────────────────────────────────────────────────────────────
_S4 = Scenario(
    id=4,
    name="Mall Name Only (Partial Search)",
    goal="Test that a mall-only search resolves to the single Under Armour lease at Jawharat Jeddah",
    turns=[
        Turn(
            message="I want to open a handover request",
            note="Bot asks for lease identifier (code, brand, or mall)",
        ),
        Turn(
            message="Jawharat Jeddah mall",
            note="Mall name alone resolves to t0105712 (Under Armour); all backend fields auto-filled",
        ),
        Turn(
            message="Under Armour Jawharat Handover",
            note="Title accepted; bot asks for description",
        ),
        Turn(
            message="Initial fit-out handover inspection for new tenant space",
            note="Description accepted; bot asks for start date",
        ),
        Turn(
            message="2026-06-15",
            note="Start date accepted; bot asks for end date",
        ),
        Turn(
            message="2026-06-17",
            note="End date accepted; bot asks for inspection done by",
        ),
        Turn(
            message="FM Manager",
            note="Inspection done by accepted; bot asks for comments",
        ),
        Turn(
            message="Please schedule before the public opening",
            note="All fields collected; confirmation card shown",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            message="Yes, go ahead",
            note="SR submitted successfully",
            expect_workflow_stage="SR_CREATED",
            expect_keywords=["reference", "submitted", "successfully", "created"],
        ),
    ],
    tags=["partial-search", "mall-lookup"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 5 — Correction After Confirmation Card
# ─────────────────────────────────────────────────────────────────────────────
_S5 = Scenario(
    id=5,
    name="Correction After Confirmation Card",
    goal="Test updating a field after the confirmation card has been shown (end date change)",
    turns=[
        Turn(
            message="I want to create a handover service request",
            note="Bot asks for lease identifier",
        ),
        Turn(
            message="t0301144",
            note="Nike Mall of Arabia (Jeddah) lease resolved",
        ),
        Turn(
            message="Nike Mall of Arabia Handover",
            note="Title accepted",
        ),
        Turn(
            message="Fit-out handover for Nike at Mall of Arabia, Jeddah",
            note="Description accepted",
        ),
        Turn(
            message="2026-08-01",
            note="Start date accepted",
        ),
        Turn(
            message="2026-08-03",
            note="End date accepted",
        ),
        Turn(
            message="FM Manager",
            note="Inspection done by accepted",
        ),
        Turn(
            message="No additional comments",
            note="All fields collected; confirmation card shown with endDate=2026-08-03",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            message="Actually, change the end date to 2026-08-05",
            note="Bot updates end date and shows a refreshed confirmation card with 2026-08-05",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            message="Confirm",
            note="SR submitted with corrected end date 2026-08-05",
            expect_workflow_stage="SR_CREATED",
            expect_keywords=["reference", "submitted", "successfully", "created"],
        ),
    ],
    tags=["correction", "edit-after-confirm"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 6 — Invalid Lease Code, Then Correct
# ─────────────────────────────────────────────────────────────────────────────
_S6 = Scenario(
    id=6,
    name="Invalid Lease Code, Then Correct",
    goal="Verify error handling when the lease lookup returns no results; flow resumes with correct code",
    turns=[
        Turn(
            message="I want to create a handover request",
            note="Bot asks for lease identifier",
        ),
        Turn(
            message="LC-TEST-999",
            note="Mock lookup returns 0 matches; bot apologises and asks to try again",
            expect_keywords=["not found", "couldn't find", "no lease", "unable", "try again", "sorry"],
        ),
        Turn(
            message="Sorry, the correct code is t0208831",
            note="Correct lease code accepted; Nike Riyadh Park resolved; flow resumes",
        ),
        Turn(
            message="Nike Riyadh Park Summer Handover",
            note="Title accepted",
        ),
        Turn(
            message="Seasonal handover inspection for Nike Riyadh Park units",
            note="Description accepted",
        ),
        Turn(
            message="2026-09-01",
            note="Start date accepted",
        ),
        Turn(
            message="2026-09-03",
            note="End date accepted",
        ),
        Turn(
            message="Operations",
            note="Inspection done by accepted",
        ),
        Turn(
            message="Units GF101 and GF102 both need inspection",
            note="All fields collected; confirmation card shown",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            message="Confirm",
            note="SR submitted successfully",
            expect_workflow_stage="SR_CREATED",
            expect_keywords=["reference", "submitted", "successfully", "created"],
        ),
    ],
    tags=["error-handling", "invalid-lease"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 7 — Cancel Mid-Flow and Restart
# ─────────────────────────────────────────────────────────────────────────────
_S7 = Scenario(
    id=7,
    name="Cancel Mid-Flow and Restart",
    goal="Verify cancel phrases clear session state so a fresh intent can be started",
    turns=[
        Turn(
            message="I want to create a handover request",
            note="Bot asks for lease identifier",
        ),
        Turn(
            message="t0208831",
            note="Nike Riyadh Park lease resolved",
        ),
        Turn(
            message="Actually, cancel. I want to start over",
            note="'cancel' triggers supervisor reset; active agent cleared; state wiped",
            expect_keywords=["cancel", "cancelled", "cleared", "start", "help", "anything", "fresh", "reset"],
        ),
        Turn(
            message="I need to raise a handover for Zara Dubai",
            note="Fresh intent classification; t0419977 resolved via brand+mall search",
        ),
        Turn(
            message="Zara DFC Handover – Q3",
            note="Title accepted",
        ),
        Turn(
            message="Q3 fit-out handover for Zara unit UF301",
            note="Description accepted",
        ),
        Turn(
            message="2026-10-01",
            note="Start date accepted",
        ),
        Turn(
            message="2026-10-03",
            note="End date accepted",
        ),
        Turn(
            message="FM Manager",
            note="Inspection done by accepted",
        ),
        Turn(
            message="No comments",
            note="All fields collected; confirmation card shown",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            message="Confirm",
            note="SR submitted successfully; prior Nike context must be gone",
            expect_workflow_stage="SR_CREATED",
            expect_keywords=["reference", "submitted", "successfully", "created"],
        ),
    ],
    tags=["cancel", "restart", "state-management"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 8 — Ambiguous / Off-Topic Opening
# ─────────────────────────────────────────────────────────────────────────────
_S8 = Scenario(
    id=8,
    name="Ambiguous / Off-Topic Opening",
    goal="Test that the supervisor asks for clarification on unclear and off-topic messages",
    turns=[
        Turn(
            message="hello",
            note="Bot greets and asks what the user wants to do",
        ),
        Turn(
            message="I need to do something about a lease",
            note="Bot asks to clarify — create, update, approve, or check status?",
            expect_keywords=["create", "handover", "service", "request", "help", "what"],
        ),
        Turn(
            message="create a new handover",
            note="Intent classified as CREATE_HANDOVER_SERVICE_REQUEST; bot asks for lease identifier",
            expect_keywords=["lease", "code", "brand", "mall"],
        ),
        Turn(
            message="t0105712",
            note="Lease resolved; bot asks for title",
        ),
        Turn(
            message="UA Jeddah Ambiguity Test Handover",
            note="Title accepted; bot asks for description",
        ),
        Turn(
            message="Test handover for ambiguity scenario validation",
            note="Description accepted",
        ),
        Turn(
            message="2026-11-10",
            note="Start date accepted",
        ),
        Turn(
            message="2026-11-12",
            note="End date accepted",
        ),
        Turn(
            message="FM Manager",
            note="Inspection done by accepted",
        ),
        Turn(
            message="No comments for this test",
            note="All fields collected; confirmation card shown",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            message="Confirm",
            note="SR submitted successfully",
            expect_workflow_stage="SR_CREATED",
            expect_keywords=["reference", "submitted", "successfully", "created"],
        ),
    ],
    tags=["ambiguous", "clarification"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 9 — Natural Language Dates
# ─────────────────────────────────────────────────────────────────────────────
_S9 = Scenario(
    id=9,
    name="Natural Language Dates",
    goal=(
        "Verify the LLM correctly parses human-friendly date formats: "
        "'first of November' → 2026-11-01, 'November 3rd' → 2026-11-03"
    ),
    turns=[
        Turn(
            message="Create a handover service request for t0105712",
            note="Lease resolved; bot asks for title",
        ),
        Turn(
            message="Under Armour Jeddah Q4 Handover",
            note="Title accepted; bot asks for description",
        ),
        Turn(
            message="End-of-year fit-out handover for FF050 unit",
            note="Description accepted; bot asks for start date",
        ),
        Turn(
            message="Start on the first of November",
            note="LLM must parse 'first of November' as 2026-11-01",
        ),
        Turn(
            message="End on November 3rd",
            note="LLM must parse 'November 3rd' as 2026-11-03",
        ),
        Turn(
            message="FM Manager",
            note="Inspection done by accepted; bot asks for comments",
        ),
        Turn(
            message="Please confirm availability with FM team before scheduling",
            note="All fields collected; confirmation card must show 2026-11-01 and 2026-11-03",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            message="Confirm",
            note="SR submitted successfully",
            expect_workflow_stage="SR_CREATED",
            expect_keywords=["reference", "submitted", "successfully", "created"],
        ),
    ],
    tags=["date-parsing", "natural-language"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 10 — Date Range Violation then Fix (§4D / §4F)
# ─────────────────────────────────────────────────────────────────────────────
_S10 = Scenario(
    id=10,
    name="Date Range Violation then Fix (§4D/§4F)",
    goal="End date before start date blocks submission; correcting end date clears error and shows card",
    turns=[
        Turn("I want to create a handover service request", "Bot asks for lease identifier"),
        Turn("t0105712", "Under Armour, Jawharat Jeddah resolved"),
        Turn("Date range validation test", "Description accepted; bot asks for start date"),
        Turn("2026-09-05", "Start date 2026-09-05 accepted; bot asks for end date"),
        Turn(
            "2026-09-03",
            "End 2026-09-03 < start 2026-09-05; must block — bot asks to correct end date",
            expect_no_submit=True,
            expect_keywords=["end date", "start", "after", "before", "valid", "correct", "invalid", "date"],
        ),
        Turn("2026-09-07", "Valid end date; bot asks for inspector"),
        Turn("FM Manager", "Inspector accepted; bot asks for comments"),
        Turn(
            "No additional comments",
            "All fields valid; confirmation card shown",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            "Confirm",
            "SR submitted",
            expect_workflow_stage="SR_CREATED",
            expect_keywords=["submitted", "successfully", "reference", "created"],
        ),
    ],
    tags=["date-validation", "error-handling"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 11 — Garbage Date Inputs Rejected (§4E)
# ─────────────────────────────────────────────────────────────────────────────
_S11 = Scenario(
    id=11,
    name="Garbage Date Inputs Rejected (§4E)",
    goal="Non-date placeholders (ASAP, TBD) are rejected and bot re-asks for a real date",
    turns=[
        Turn("I want to create a handover service request", "Bot asks for lease identifier"),
        Turn("t0105712", "Under Armour resolved"),
        Turn("Garbage date test", "Description accepted; bot asks for start date"),
        Turn(
            "ASAP",
            "Non-date placeholder — bot must reject and re-ask for start date",
            expect_no_submit=True,
            expect_keywords=["date", "when", "start", "please", "specific"],
        ),
        Turn("2026-10-01", "Valid start date accepted; bot asks for end date"),
        Turn(
            "TBD",
            "Another placeholder — bot must reject and re-ask for end date",
            expect_no_submit=True,
            expect_keywords=["date", "when", "end", "please", "specific"],
        ),
        Turn("2026-10-03", "Valid end date accepted; bot asks for inspector"),
        Turn("FM Manager", "Inspector accepted; bot asks for comments"),
        Turn(
            "None",
            "All fields valid; confirmation card shown",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            "Confirm",
            "SR submitted",
            expect_workflow_stage="SR_CREATED",
            expect_keywords=["submitted", "successfully", "reference", "created"],
        ),
    ],
    tags=["date-validation", "edge-case"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 12 — Ambiguous Inspector Prompts Clarification (§5B)
# ─────────────────────────────────────────────────────────────────────────────
_S12 = Scenario(
    id=12,
    name="Ambiguous Inspector Prompts Clarification (§5B)",
    goal="Vague inspector input triggers FM Manager vs Operations re-ask; no guessing",
    turns=[
        Turn("I want to create a handover service request", "Bot asks for lease identifier"),
        Turn("t0419977", "Zara Dubai Festival City resolved"),
        Turn("Inspector ambiguity test handover", "Description accepted"),
        Turn("2026-11-01", "Start date accepted"),
        Turn("2026-11-03", "End date accepted"),
        Turn(
            "my team",
            "Ambiguous — bot must ask FM Manager or Operations?",
            expect_keywords=["fm manager", "operations", "who", "inspector", "which", "perform"],
        ),
        Turn("Operations", "Enum resolved to OPERATIONS; bot asks for comments"),
        Turn(
            "skip",
            "All fields collected; confirmation card shown",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            "Confirm",
            "SR submitted",
            expect_workflow_stage="SR_CREATED",
            expect_keywords=["submitted", "successfully", "reference", "created"],
        ),
    ],
    tags=["inspector", "ambiguous", "edge-case"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 13 — Brand + Mall Combo Unambiguous Resolution (§2E)
# ─────────────────────────────────────────────────────────────────────────────
_S13 = Scenario(
    id=13,
    name="Brand and Mall Combo — Direct Resolution (§2E)",
    goal="'Nike at Riyadh Park' resolves directly without a lease_selection card",
    turns=[
        Turn(
            "I need to create a handover request for Nike at Riyadh Park",
            "Nike + Riyadh Park unambiguous — bot resolves t0208831 and asks for description (no selection card)",
            expect_ui_type="text_question",
        ),
        Turn("Nike Riyadh Park fit-out inspection", "Description accepted"),
        Turn("2026-07-10", "Start date accepted"),
        Turn("2026-07-12", "End date accepted"),
        Turn("Operations", "Inspector accepted"),
        Turn(
            "No comments",
            "All fields collected; confirmation card shown",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            "Confirm",
            "SR submitted",
            expect_workflow_stage="SR_CREATED",
            expect_keywords=["submitted", "successfully", "reference", "created"],
        ),
    ],
    tags=["lease-search", "brand-mall-combo"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 14 — Restart After Confirmation Card (§10B)
# ─────────────────────────────────────────────────────────────────────────────
_S14 = Scenario(
    id=14,
    name="Restart After Confirmation Card (§10B)",
    goal="'start over' at card stage clears all state; new request opens without context leak",
    turns=[
        Turn("I want to create a handover service request", "Bot asks for lease identifier"),
        Turn("t0105712", "Under Armour resolved"),
        Turn("Complete fit-out verification before opening", "Description accepted"),
        Turn("2026-06-01", "Start date accepted"),
        Turn("2026-06-03", "End date accepted"),
        Turn("FM Manager", "Inspector accepted"),
        Turn(
            "No additional comments",
            "All fields collected; confirmation card shown",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            "start over",
            "State cleared at card stage; bot asks what to do next",
            expect_keywords=["cleared", "start", "fresh", "help", "anything", "reset", "cancel"],
        ),
        Turn(
            "I need to raise a handover for Zara Dubai",
            "Fresh intent; t0419977 resolved; no Under Armour context leaks",
        ),
        Turn("Zara DFC Q3 fit-out verification", "Description accepted"),
        Turn("2026-08-01", "Start date accepted"),
        Turn("2026-08-03", "End date accepted"),
        Turn("Operations", "Inspector accepted"),
        Turn(
            "No comments",
            "All fields collected — Zara, not Under Armour; confirmation card shown",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            "Confirm",
            "SR submitted; no Under Armour context in payload",
            expect_workflow_stage="SR_CREATED",
            expect_keywords=["submitted", "successfully", "reference", "created"],
        ),
    ],
    tags=["restart", "state-management", "context-isolation"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 15 — Off-Topic and Unsupported Intents (§1C)
# ─────────────────────────────────────────────────────────────────────────────
_S15 = Scenario(
    id=15,
    name="Off-Topic and Unsupported Intents (§1C)",
    goal="Lease renewal and weather queries are UNKNOWN; bot clarifies or politely declines",
    turns=[
        Turn(
            "I want to renew my lease",
            "Lease renewal is UNKNOWN — bot asks what the user wants to do",
            expect_keywords=["create", "handover", "service", "request", "help"],
        ),
        Turn(
            "What is the weather today?",
            "Off-topic — bot politely declines or redirects to handover",
            expect_keywords=["sorry", "weather", "help", "handover", "service", "request", "can"],
        ),
        Turn(
            "OK I want to create a new handover request",
            "Clear handover intent — bot asks for lease identifier",
            expect_keywords=["lease", "code", "brand", "mall"],
        ),
        Turn("t0301144", "Nike Mall of Arabia resolved"),
        Turn("Standard fit-out verification for store opening", "Description accepted"),
        Turn("2026-12-01", "Start date accepted"),
        Turn("2026-12-03", "End date accepted"),
        Turn("FM Manager", "Inspector accepted"),
        Turn(
            "No comments",
            "Confirmation card shown",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            "Confirm",
            "SR submitted",
            expect_workflow_stage="SR_CREATED",
            expect_keywords=["submitted", "successfully", "reference", "created"],
        ),
    ],
    tags=["off-topic", "intent-classification"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 16 — API: corrected_fields Single Field (§12A)
# ─────────────────────────────────────────────────────────────────────────────
_S16 = Scenario(
    id=16,
    name="API corrected_fields — Single Field Update (§12A)",
    goal="corrected_fields with endDate sent alongside action=confirm updates and submits in one shot",
    turns=[
        Turn(
            "Create a handover service request for lease t0105712. "
            "Description: corrected_fields API test. "
            "Start 2026-06-01, end 2026-06-03, FM Manager, no comments.",
            "All fields extracted in one message; confirmation card shown",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            "Confirmed",
            "corrected_fields updates endDate to 2026-06-10; SR submitted with new value",
            action="confirm",
            corrected_fields={"endDate": "2026-06-10"},
            expect_workflow_stage="SR_CREATED",
            expect_keywords=["submitted", "successfully", "reference", "created"],
        ),
    ],
    tags=["api", "corrected-fields", "inline-edit"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 17 — API: corrected_fields Multiple Fields (§12B)
# ─────────────────────────────────────────────────────────────────────────────
_S17 = Scenario(
    id=17,
    name="API corrected_fields — Multiple Fields Update (§12B)",
    goal="Multiple corrected_fields applied simultaneously before submission",
    turns=[
        Turn(
            "Create a handover service request for lease t0105712. "
            "Description: multi corrected_fields test. "
            "Start 2026-07-01, end 2026-07-03, FM Manager, no comments.",
            "All fields extracted; confirmation card shown",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            "Submit",
            "Both endDate and comments updated via corrected_fields; SR submitted",
            action="confirm",
            corrected_fields={
                "endDate": "2026-07-10",
                "comments": "Revised timeline — tenant opens July 12",
            },
            expect_workflow_stage="SR_CREATED",
            expect_keywords=["submitted", "successfully", "reference", "created"],
        ),
    ],
    tags=["api", "corrected-fields", "inline-edit"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 18 — API: corrected_fields Date Range Violation (§12D)
# ─────────────────────────────────────────────────────────────────────────────
_S18 = Scenario(
    id=18,
    name="API corrected_fields — Date Range Violation Blocks Submission (§12D)",
    goal="corrected_fields making start > end triggers blocking validation; bot asks to fix dates",
    turns=[
        Turn(
            "Create a handover service request for lease t0208831. "
            "Description: corrected_fields date violation test. "
            "Start 2026-09-01, end 2026-09-03, Operations, no comments.",
            "All fields extracted; confirmation card shown",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            "update start date",
            "corrected_fields sets startDate=2026-09-10 which exceeds endDate=2026-09-03; must block",
            corrected_fields={"startDate": "2026-09-10"},
            expect_no_submit=True,
            expect_keywords=["end date", "start", "after", "before", "valid", "correct", "invalid", "date"],
        ),
        Turn(
            "change end date to 2026-09-15",
            "Valid end date fixes the range; confirmation card re-shown",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            "Confirm",
            "SR submitted with corrected dates",
            expect_workflow_stage="SR_CREATED",
            expect_keywords=["submitted", "successfully", "reference", "created"],
        ),
    ],
    tags=["api", "corrected-fields", "date-validation"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 19 — API: selected_lease_id (§13A / §13B)
# ─────────────────────────────────────────────────────────────────────────────
_S19 = Scenario(
    id=19,
    name="API selected_lease_id — Lease Selection via API Field (§13A/§13B)",
    goal="selected_lease_id bypasses text search and resolves the specified lease directly",
    turns=[
        Turn(
            "I need to raise a handover request for Nike",
            "Two Nike leases found; lease_selection card shown",
            expect_ui_type="lease_selection",
        ),
        Turn(
            "t0208831",
            "selected_lease_id=t0208831 selects Nike Riyadh Park; bot asks for description",
            selected_lease_id="t0208831",
        ),
        Turn("Selected lease API test", "Description accepted"),
        Turn("2026-10-01", "Start date accepted"),
        Turn("2026-10-03", "End date accepted"),
        Turn("FM Manager", "Inspector accepted"),
        Turn(
            "No comments",
            "All fields collected; confirmation card shown",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            "Confirm",
            "SR submitted",
            expect_workflow_stage="SR_CREATED",
            expect_keywords=["submitted", "successfully", "reference", "created"],
        ),
    ],
    tags=["api", "selected-lease-id"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 20 — Title Auto-Generation Verification (§15)
# ─────────────────────────────────────────────────────────────────────────────
_S20 = Scenario(
    id=20,
    name="Title Auto-Generation Verification (§15)",
    goal="Confirmation card title follows handover-{lease_code}-{first-5-words-slug} pattern",
    turns=[
        Turn(
            "Create a handover service request for lease t0105712. "
            "Description: Standard fit-out inspection for new tenant unit. "
            "Start 2026-06-01, end 2026-06-03, FM Manager, no comments.",
            "All fields extracted; title in card must be handover-t0105712-standard-fitout-inspection-for-new",
            expect_ui_type="confirmation_card",
            expect_field_value={"Title": "handover-t0105712-standard-fitout-inspection-for-new"},
        ),
        Turn(
            "Confirm",
            "SR submitted",
            expect_workflow_stage="SR_CREATED",
            expect_keywords=["submitted", "successfully", "reference", "created"],
        ),
    ],
    tags=["title-generation", "validation"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 21 — Boundary and Special-Character Inputs (§14B / §14D)
# ─────────────────────────────────────────────────────────────────────────────
_S21 = Scenario(
    id=21,
    name="Boundary and Special-Character Inputs (§14B/§14D)",
    goal="Whitespace-only and emoji messages handled gracefully without crash",
    turns=[
        Turn(
            "     ",
            "Whitespace-only — bot responds gracefully (no crash or 500)",
            expect_keywords=["help", "what", "create", "service", "request", "hello", "hi"],
        ),
        Turn(
            "🏗️ I want to create a handover request for lease t0105712",
            "Emoji in message — intent recognised; lease t0105712 extracted",
        ),
        Turn("Boundary stress test description", "Description accepted"),
        Turn("2026-06-01", "Start date accepted"),
        Turn("2026-06-03", "End date accepted"),
        Turn("FM Manager", "Inspector accepted"),
        Turn(
            "No comments",
            "Confirmation card shown",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            "Confirm",
            "SR submitted",
            expect_workflow_stage="SR_CREATED",
            expect_keywords=["submitted", "successfully", "reference", "created"],
        ),
    ],
    tags=["boundary", "unicode", "edge-case"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 22 — API: corrected_fields Protected Fields Silently Ignored (§12C)
# ─────────────────────────────────────────────────────────────────────────────
_S22 = Scenario(
    id=22,
    name="API corrected_fields — Protected Fields Silently Ignored (§12C)",
    goal="lease_id and brand_id in corrected_fields are ignored; only endDate is applied",
    turns=[
        Turn(
            "Create a handover service request for lease t0105712. "
            "Description: protected fields ignore test. "
            "Start 2026-06-01, end 2026-06-03, FM Manager, no comments.",
            "All fields extracted; confirmation card shown",
            expect_ui_type="confirmation_card",
        ),
        Turn(
            "Confirmed",
            "lease_id=99999 and brand_id=999 silently ignored; only endDate=2026-06-10 applied; SR submitted",
            action="confirm",
            corrected_fields={"lease_id": 99999, "brand_id": 999, "endDate": "2026-06-10"},
            expect_workflow_stage="SR_CREATED",
            expect_keywords=["submitted", "successfully", "reference", "created"],
        ),
    ],
    tags=["api", "corrected-fields", "security"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Master list — all scenarios in order
# ─────────────────────────────────────────────────────────────────────────────
SCENARIOS: list[Scenario] = [
    _S1, _S2, _S3, _S4, _S5, _S6, _S7, _S8, _S9,
    _S10, _S11, _S12, _S13, _S14, _S15, _S16, _S17,
    _S18, _S19, _S20, _S21, _S22,
]
