from __future__ import annotations

from typing import Any

from env.models import SREReward


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, round(value, 4)))


def grade_chaos_engineering(
    state: dict[str, Any], step_count: int, done: bool
) -> SREReward:
    scenario = state["scenario"]
    completed = state.get("mitigation_steps_completed", [])
    total_steps = len(scenario["correct_order"])

    if not state.get("chaos_injected"):
        return SREReward(
            value=0.0, breakdown={"error": "No chaos injected"}, done=done, info={}
        )

    injection_score = 0.1
    observation_score = 0.1 if state.get("impact_observed") else 0.0

    step_score = 0.15 * len(completed)

    wrong_order = state.get("mitigation_in_wrong_order", 0)
    order_penalty = 0.05 * wrong_order

    all_complete = len(completed) == total_steps
    completion_bonus = 0.2 if all_complete else 0.0

    efficiency_bonus = 0.15 if (all_complete and step_count <= 8) else 0.0
    invalid_penalty = 0.02 * state.get("invalid_actions", 0)

    total = (
        injection_score
        + observation_score
        + step_score
        + completion_bonus
        + efficiency_bonus
        - order_penalty
        - invalid_penalty
    )
    total = _clamp(total)

    breakdown = {
        "chaos_injected": True,
        "injection_score": round(injection_score, 4),
        "impact_observed": state.get("impact_observed", False),
        "observation_score": round(observation_score, 4),
        "mitigation_steps_completed": completed,
        "step_score": round(step_score, 4),
        "wrong_order_attempts": wrong_order,
        "order_penalty": round(order_penalty, 4),
        "all_steps_complete": all_complete,
        "completion_bonus": round(completion_bonus, 4),
        "efficiency_bonus": round(efficiency_bonus, 4),
        "invalid_action_penalty": round(invalid_penalty, 4),
        "score_explanation": (
            "Rewards injecting chaos, observing impact, completing all mitigation "
            "steps in order, and doing so efficiently."
        ),
    }
    return SREReward(value=total, breakdown=breakdown, done=done, info={})
