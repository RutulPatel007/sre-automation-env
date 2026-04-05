from __future__ import annotations

from typing import Any

from env.models import SREReward

# Upstream dependency map: service -> list of services that depend on it
# If agent names a service one hop upstream of the real root cause, partial credit
UPSTREAM_MAP = {
    "db-service": ["payment-service"],
    "payment-service": ["auth-service"],
    "auth-service": ["api-gateway"],
    "user-service": ["auth-service"],
    "api-gateway": [],
}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, round(value, 4)))


def _normalize(text: str) -> str:
    return " ".join(text.lower().strip().replace("-", " ").split())


def _failure_mode_match(predicted: str, scenario: dict[str, Any]) -> bool:
    normalized_prediction = _normalize(predicted)
    if not normalized_prediction:
        return False
    keywords = scenario.get("keywords", [])
    return any(keyword in normalized_prediction for keyword in keywords)


def _efficiency_bonus(step_used: int) -> float:
    if step_used <= 8:
        return 0.2
    if step_used >= 12:
        return 0.0
    return round(0.2 * ((12 - step_used) / 4), 4)


def _is_upstream_of(predicted_service: str, root_cause_service: str) -> bool:
    """Check if predicted_service is a direct upstream consumer of root_cause_service."""
    return predicted_service in UPSTREAM_MAP.get(root_cause_service, [])


def grade_incident_diagnosis(
    state: dict[str, Any], step_count: int, done: bool
) -> SREReward:
    scenario = state["incident"]
    diagnosis = state.get("submitted_diagnosis") or {}
    predicted_service = diagnosis.get("service", "")
    predicted_failure = diagnosis.get("failure_mode", "")
    correct_service = predicted_service == scenario["service"]
    failure_match = _failure_mode_match(predicted_failure, scenario)

    # Evidence collection bonuses
    evidence_metric = 0.05 if scenario["service"] in state["queried_metrics"] else 0.0
    evidence_logs = 0.05 if scenario["service"] in state["queried_logs"] else 0.0

    # Root cause identification
    root_cause_score = 0.0
    upstream_partial = False
    if correct_service:
        root_cause_score = 0.5
    elif predicted_service and _is_upstream_of(predicted_service, scenario["service"]):
        root_cause_score = 0.1
        upstream_partial = True

    # Failure mode scoring
    failure_mode_score = 0.0
    if correct_service and failure_match:
        failure_mode_score = 0.2
    elif upstream_partial and failure_match:
        # Partial credit: correctly matched failure mode but wrong service
        failure_mode_score = 0.05

    # Efficiency bonus (only for correct root cause)
    efficiency_score = 0.0
    if correct_service and diagnosis:
        efficiency_score = _efficiency_bonus(diagnosis["step"])

    # Penalties
    extra_metric_queries = max(0, len(state["queried_metrics"]) - 6)
    query_penalty = 0.05 * extra_metric_queries
    invalid_penalty = 0.02 * state.get("invalid_actions", 0)

    total = (
        evidence_metric
        + evidence_logs
        + root_cause_score
        + failure_mode_score
        + efficiency_score
        - query_penalty
        - invalid_penalty
    )
    total = _clamp(total)

    breakdown = {
        "root_cause_service_correct": correct_service,
        "root_cause_score": round(root_cause_score, 4),
        "upstream_partial_credit": upstream_partial,
        "failure_mode_match": failure_match,
        "failure_mode_score": round(failure_mode_score, 4),
        "evidence_collection": {
            "queried_root_metrics": scenario["service"] in state["queried_metrics"],
            "queried_root_logs": scenario["service"] in state["queried_logs"],
            "score": round(evidence_metric + evidence_logs, 4),
        },
        "efficiency_score": round(efficiency_score, 4),
        "metric_queries": len(state["queried_metrics"]),
        "query_penalty": round(query_penalty, 4),
        "invalid_action_penalty": round(invalid_penalty, 4),
        "score_explanation": (
            "The score rewards collecting the right evidence, naming the correct root "
            "cause service (or its direct upstream for partial credit), "
            "matching the failure mode, and submitting an efficient diagnosis."
        ),
    }
    return SREReward(value=total, breakdown=breakdown, done=done, info={})
