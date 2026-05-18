"""Centralised authorization checks for graph transitions and API calls.

Permission model
----------------
Each *action* string (e.g. ``"CREATE_HANDOVER_SR"``) maps to a required
*permission string* that the caller's ``AuthContext.roles`` frozenset must
contain.  If the caller does not hold the required permission a
``PermissionDeniedError`` is raised — never silently allowed.

POC note: ``AuthContext.roles`` is currently populated from the stub
``get_auth_context`` in ``core/security.py``.  When real JWT validation is
wired the roles frozenset will be populated from token claims and this
service will enforce them automatically.
"""

from __future__ import annotations

from app.types.chat import AuthContext

# ---------------------------------------------------------------------------
# Permission map — action → required role/permission string
# ---------------------------------------------------------------------------

ACTION_PERMISSION_MAP: dict[str, str] = {
    # Tenant / mall manager raises a new handover SR
    "CREATE_HANDOVER_SR": "CAN_RAISE_HANDOVER_SR",
    # FM manager approves the handover at the FM review stage
    "FM_APPROVAL": "CAN_APPROVE_HANDOVER_SR",
    # DD/RDD engineer gives final approval
    "RDD_FINAL_APPROVAL": "CAN_APPROVE_HANDOVER_SR",
    # Any read access to a handover SR record
    "VIEW_HANDOVER_SR": "VIEW_FIT_OUT_HANDOVER",
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PermissionDeniedError(Exception):
    """Raised when a caller attempts an action they are not authorised for.

    Attributes
    ----------
    action:         The action that was attempted.
    required_role:  The permission string that was missing from the caller's
                    roles frozenset.
    """

    def __init__(self, action: str, required_role: str) -> None:
        self.action = action
        self.required_role = required_role
        super().__init__(
            f"Permission denied: action '{action}' requires role '{required_role}'."
        )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class PermissionService:
    """Evaluate whether a caller may perform a named action.

    All enforcement goes through :meth:`check`.  Convenience wrappers
    (``ensure_can_*``) are provided for existing call-sites.
    """

    # ------------------------------------------------------------------
    # Core check
    # ------------------------------------------------------------------

    def check(self, action: str, auth: AuthContext) -> None:
        """Assert that *auth* holds the permission required for *action*.

        Raises :class:`PermissionDeniedError` when the required permission is
        absent from ``auth.roles``.

        Unknown actions (not present in ``ACTION_PERMISSION_MAP``) are
        **fail-open** for the POC: if no mapping exists, the call succeeds.
        This keeps unclassified legacy paths unblocked while explicit
        high-value actions are protected.
        """
        required = ACTION_PERMISSION_MAP.get(action)
        if required is None:
            # Action is not in the map → no restriction defined yet.
            return
        if required not in auth.roles:
            raise PermissionDeniedError(action=action, required_role=required)

    # ------------------------------------------------------------------
    # Convenience wrappers
    # ------------------------------------------------------------------

    def ensure_can_create_request(self, auth: AuthContext) -> None:
        """Assert the caller may raise a new Handover Service Request."""
        self.check("CREATE_HANDOVER_SR", auth)

    def ensure_can_approve_request(self, action: str, auth: AuthContext) -> None:
        """Assert the caller may approve at the given stage.

        *action* should be one of ``"FM_APPROVAL"`` or ``"RDD_FINAL_APPROVAL"``.
        """
        self.check(action, auth)

    def ensure_can_view_trace(self, auth: AuthContext) -> None:
        """Assert the caller may read handover SR records."""
        self.check("VIEW_HANDOVER_SR", auth)
