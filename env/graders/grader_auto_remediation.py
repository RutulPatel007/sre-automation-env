from __future__ import annotations

from typing import Any

from env.models import SREReward


def _clamp(value: float) -> float:
    return max(0.0001, min(0.9999, round(value, 4)))


def grade_auto_remediation(
    state: dict[str, Any], step_count: int, done: bool
) -> SREReward:
    scenario = state["scenario"]
    attempted = state.get("remediation_attempted")
    final = state.get("final_state")

    if not attempted:
        return SREReward(
            value=0.0001,
            breakdown={"error": "No remediation attempted"},
            done=done,
            info={},
        )

    correct_action = attempted["action"] == scenario["correct_action"]
    action_score = 0.4 if correct_action else 0.0

    if final:
        outcome = final["outcome"]
        if outcome == "success":
            outcome_score = 0.4
        elif outcome == "rolled_back":
            outcome_score = 0.2
        elif outcome == "partial":
            outcome_score = 0.1
        else:
            outcome_score = 0.0
    else:
        outcome_score = 0.0

    verified = state.get("recovery_verified", False)
    verify_score = 0.1 if verified else 0.0

    if final and final["outcome"] == "worse" and not state.get("rollback_performed"):
        rollback_penalty = 0.2
    elif final and final["outcome"] == "worse" and state.get("rollback_performed"):
        rollback_penalty = 0.0
    else:
        rollback_penalty = 0.0

    efficiency_bonus = 0.1 if step_count <= 5 else 0.0
    invalid_penalty = 0.02 * state.get("invalid_actions", 0)

    total = (
        action_score
        + outcome_score
        + verify_score
        + efficiency_bonus
        - rollback_penalty
        - invalid_penalty
    )
    total = _clamp(total)

    breakdown = {
        "correct_action_chosen": correct_action,
        "action_score": round(action_score, 4),
        "outcome": final["outcome"] if final else "none",
        "outcome_score": round(outcome_score, 4),
        "recovery_verified": verified,
        "verify_score": round(verify_score, 4),
        "rollback_penalty": round(rollback_penalty, 4),
        "efficiency_bonus": round(efficiency_bonus, 4),
        "invalid_action_penalty": round(invalid_penalty, 4),
        "score_explanation": (
            "Rewards choosing the correct remediation, verifying recovery, "
            "and rolling back if the fix made things worse."
        ),
    }
    return SREReward(value=total, breakdown=breakdown, done=done, info={})
