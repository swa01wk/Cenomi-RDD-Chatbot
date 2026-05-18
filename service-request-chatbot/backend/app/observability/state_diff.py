"""Compute structured diffs between graph state snapshots."""

from __future__ import annotations

from typing import Any


def build_json_diff(
    before_state: dict[str, Any],
    after_state: dict[str, Any],
) -> dict[str, Any]:
    """Return a structured diff between *before_state* and *after_state*.

    The result has three top-level keys:

    - ``"added"``   — keys present in *after_state* but not in *before_state*.
    - ``"changed"`` — keys present in both whose values differ; each entry is
      ``{"before": <old_value>, "after": <new_value>}``.
    - ``"removed"`` — keys present in *before_state* but not in *after_state*.

    Keys whose values are equal in both states are not included in any bucket.
    Neither input dict is mutated.
    """
    all_keys = set(before_state) | set(after_state)
    added: dict[str, Any] = {}
    changed: dict[str, Any] = {}
    removed: dict[str, Any] = {}

    for k in all_keys:
        in_before = k in before_state
        in_after = k in after_state

        if in_after and not in_before:
            added[k] = after_state[k]
        elif in_before and not in_after:
            removed[k] = before_state[k]
        elif before_state[k] != after_state[k]:
            changed[k] = {"before": before_state[k], "after": after_state[k]}

    return {"added": added, "changed": changed, "removed": removed}


def shallow_dict_diff(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    """Deprecated — use :func:`build_json_diff` instead.

    Returns a flat ``{key: {"before": ..., "after": ...}}`` dict for keys
    whose values differ.  Kept for backward compatibility.
    """
    keys = set(before) | set(after)
    return {
        k: {"before": before.get(k), "after": after.get(k)}
        for k in keys
        if before.get(k) != after.get(k)
    }
