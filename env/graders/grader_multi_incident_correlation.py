from __future__ import annotations

from typing import Any

from env.models import SREReward


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, round(value, 4)))


def grade_multi_incident_correlation(
    state: dict[str, Any], step_count: int, done: bool
) -> SREReward:
    scenario = state["scenario"]
    corr = state.get("correlation_submitted")
    if not corr:
        return SREReward(
            value=0.0,
            breakdown={"error": "No correlation analysis submitted"},
            done=done,
            info={},
        )

    correct_type = corr["correlation_type"] == scenario["type"]
    type_score = 0.4 if correct_type else 0.0

    if scenario["type"] == "shared_root_cause":
        root_correct = corr["root_cause_service"] == scenario["root_cause"]
        root_score = 0.3 if root_correct else 0.0
        all_alerts = set(a["id"] for a in scenario["alerts"])
        submitted_alerts = set(corr.get("alert_ids", []))
        alert_coverage = (
            len(all_alerts & submitted_alerts) / len(all_alerts) if all_alerts else 0.0
        )
        alert_score = 0.2 * alert_coverage
    elif scenario["type"] == "independent_incidents":
        root_correct = (
            not corr["root_cause_service"]
            or corr["root_cause_service"] == "none"
            or corr["root_cause_service"] == ""
        )
        root_score = 0.3 if root_correct else 0.0
        submitted_alerts = set(corr.get("alert_ids", []))
        all_alerts = set(a["id"] for a in scenario["alerts"])
        alert_coverage = (
            len(all_alerts & submitted_alerts) / len(all_alerts) if all_alerts else 0.0
        )
        alert_score = 0.2 * alert_coverage
    else:
        root_correct = corr["root_cause_service"] == scenario["root_cause"]
        root_score = 0.15 if root_correct else 0.0
        submitted_alerts = set(corr.get("alert_ids", []))
        correlated_alerts = set(
            a["id"]
            for a in scenario["alerts"]
            if a["id"] not in scenario["independent_alerts"]
        )
        independent_correct = all(
            aid not in submitted_alerts for aid in scenario["independent_alerts"]
        )
        partial_score = 0.15 if independent_correct else 0.0
        alert_coverage = (
            len(correlated_alerts & submitted_alerts) / len(correlated_alerts)
            if correlated_alerts
            else 0.0
        )
        alert_score = 0.1 * alert_coverage + partial_score

    queried_services = len(state["queried_services"])
    evidence_bonus = (
        0.1 if queried_services >= 2 else 0.05 if queried_services >= 1 else 0.0
    )

    efficiency_bonus = 0.1 if step_count <= 6 else 0.0
    invalid_penalty = 0.02 * state.get("invalid_actions", 0)

    if scenario["type"] == "partial_correlation":
        total = (
            type_score
            + root_score
            + alert_score
            + evidence_bonus
            + efficiency_bonus
            - invalid_penalty
        )
    else:
        total = (
            type_score
            + root_score
            + alert_score
            + evidence_bonus
            + efficiency_bonus
            - invalid_penalty
        )
    total = _clamp(total)

    breakdown = {
        "correlation_type_correct": correct_type,
        "type_score": round(type_score, 4),
        "root_cause_score": round(root_score, 4),
        "alert_coverage_score": round(alert_score, 4),
        "evidence_bonus": round(evidence_bonus, 4),
        "efficiency_bonus": round(efficiency_bonus, 4),
        "invalid_action_penalty": round(invalid_penalty, 4),
        "score_explanation": (
            "Rewards correct correlation type, root cause identification, "
            "proper alert grouping, and evidence gathering."
        ),
    }
    return SREReward(value=total, breakdown=breakdown, done=done, info={})
