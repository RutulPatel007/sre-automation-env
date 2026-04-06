from __future__ import annotations

from typing import Any

from env.models import SREReward


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, round(value, 4)))


def grade_capacity_planning(
    state: dict[str, Any], step_count: int, done: bool
) -> SREReward:
    scenario = state["scenario"]
    rec = state.get("recommendation")
    if not rec:
        return SREReward(
            value=0.0,
            breakdown={"error": "No scaling recommendation submitted"},
            done=done,
            info={},
        )

    correct_rec = scenario["correct_recommendation"]
    correct_replicas = scenario["target_replicas"]

    rec_match = rec["recommendation"] == correct_rec
    rec_score = 0.5 if rec_match else 0.0

    submitted_replicas = rec.get("target_replicas")
    replica_match = submitted_replicas == correct_replicas
    replica_score = 0.3 if replica_match else 0.0

    queried = (
        scenario["service"] in state["queries_made"] or "all" in state["queries_made"]
    )
    query_score = 0.1 if queried else 0.0

    efficiency_bonus = 0.1 if step_count <= 3 else 0.0

    invalid_penalty = 0.02 * state.get("invalid_actions", 0)

    total = rec_score + replica_score + query_score + efficiency_bonus - invalid_penalty
    total = _clamp(total)

    breakdown = {
        "recommendation_correct": rec_match,
        "recommendation_score": round(rec_score, 4),
        "replica_count_correct": replica_match,
        "replica_score": round(replica_score, 4),
        "queried_data": queried,
        "query_score": round(query_score, 4),
        "efficiency_bonus": round(efficiency_bonus, 4),
        "invalid_action_penalty": round(invalid_penalty, 4),
        "score_explanation": (
            "Rewards correct scaling recommendation, accurate replica count, "
            "and querying data before deciding."
        ),
    }
    return SREReward(value=total, breakdown=breakdown, done=done, info={})
