from __future__ import annotations

from typing import Any

from env.models import SREReward


def _clamp(value: float) -> float:
    return max(0.0001, min(0.9999, round(value, 4)))


def grade_on_call_handoff(
    state: dict[str, Any], step_count: int, done: bool
) -> SREReward:
    summary = state.get("handoff_summary")
    if not summary:
        return SREReward(
            value=0.0001,
            breakdown={"error": "No handoff summary submitted"},
            done=done,
            info={},
        )

    text = summary["summary"].lower()
    shift_context = state["shift_context"]

    incident_mentions = sum(
        1
        for inc in shift_context["active_incidents"]
        if inc["id"] in text or inc["service"] in text
    )
    incident_score = 0.3 * (
        incident_mentions / max(1, len(shift_context["active_incidents"]))
    )

    action_mentions = sum(
        1
        for action in shift_context["pending_actions"]
        if any(word in text for word in action.lower().split()[:3])
    )
    action_score = 0.25 * (
        action_mentions / max(1, len(shift_context["pending_actions"]))
    )

    severity_mentioned = any(
        inc["severity"].lower() in text for inc in shift_context["active_incidents"]
    )
    severity_score = 0.15 if severity_mentioned else 0.0

    health_mentioned = any(svc in text for svc in state["service_health"])
    health_score = 0.1 if health_mentioned else 0.0

    length_bonus = (
        0.1 if len(text.split()) >= 20 else 0.05 if len(text.split()) >= 10 else 0.0
    )
    efficiency_bonus = 0.1 if step_count <= 3 else 0.0

    invalid_penalty = 0.02 * state.get("invalid_actions", 0)

    total = (
        incident_score
        + action_score
        + severity_score
        + health_score
        + length_bonus
        + efficiency_bonus
        - invalid_penalty
    )
    total = _clamp(total)

    breakdown = {
        "incident_coverage_score": round(incident_score, 4),
        "action_items_score": round(action_score, 4),
        "severity_mentioned": severity_mentioned,
        "severity_score": round(severity_score, 4),
        "health_mentioned": health_mentioned,
        "health_score": round(health_score, 4),
        "length_bonus": round(length_bonus, 4),
        "efficiency_bonus": round(efficiency_bonus, 4),
        "invalid_action_penalty": round(invalid_penalty, 4),
        "word_count": len(text.split()),
        "score_explanation": (
            "Rewards mentioning all active incidents, pending actions, severity levels, "
            "and service health in a concise summary."
        ),
    }
    return SREReward(value=total, breakdown=breakdown, done=done, info={})
