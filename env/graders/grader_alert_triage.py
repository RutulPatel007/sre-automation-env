from __future__ import annotations

from typing import Any

from env.models import SREReward

PRIORITY_WEIGHT = {"P1": 3, "P2": 2, "P3": 1}


def _clamp(value: float) -> float:
    return max(0.0001, min(0.9999, round(value, 4)))


def _ordering_accuracy(
    acknowledged_order: list[str], ground_truth: dict[str, dict[str, Any]]
) -> float:
    ranks = [
        PRIORITY_WEIGHT[ground_truth[alert_id]["priority"]]
        for alert_id in acknowledged_order
        if alert_id in ground_truth
    ]
    if len(ranks) <= 1:
        return 1.0 if ranks else 0.0
    total_pairs = 0
    correct_pairs = 0
    for idx, current_rank in enumerate(ranks):
        for later_rank in ranks[idx + 1 :]:
            total_pairs += 1
            if current_rank >= later_rank:
                correct_pairs += 1
    return correct_pairs / total_pairs if total_pairs else 0.0


def _weighted_jaccard(
    actionable_ids: set[str],
    agent_ids: set[str],
    ground_truth: dict[str, dict[str, Any]],
) -> float:
    union_ids = actionable_ids | agent_ids
    if not union_ids:
        return 0.0
    intersection_weight = sum(
        PRIORITY_WEIGHT[ground_truth[alert_id]["priority"]]
        for alert_id in actionable_ids & agent_ids
    )
    union_weight = sum(
        PRIORITY_WEIGHT.get(ground_truth.get(alert_id, {}).get("priority", "P3"), 1)
        for alert_id in union_ids
    )
    return intersection_weight / union_weight if union_weight else 0.0


def grade_alert_triage(state: dict[str, Any], step_count: int, done: bool) -> SREReward:
    actionable_ids = set(state["actionable_ids"])
    ignored_ids = set(state["ignorable_ids"])
    ground_truth = state["ground_truth"]
    acknowledged_order = [
        alert_id
        for alert_id in state["acknowledged_order"]
        if alert_id in actionable_ids
    ]
    acknowledged_ids = set(acknowledged_order)
    weighted_jaccard = _weighted_jaccard(actionable_ids, acknowledged_ids, ground_truth)

    correct_ignored = 0
    for alert_id in ignored_ids:
        decision = state["triage_decisions"].get(alert_id, {}).get("decision")
        if decision == "ignore" or alert_id in state["ignored_alert_ids"]:
            correct_ignored += 1
    ignore_score = 0.1 * correct_ignored

    highest_priority_weight = None
    if actionable_ids:
        highest_priority_weight = max(
            PRIORITY_WEIGHT[ground_truth[alert_id]["priority"]]
            for alert_id in actionable_ids
        )
    first_ack_score = 0.0
    if acknowledged_order and highest_priority_weight is not None:
        first_ack_priority = PRIORITY_WEIGHT[
            ground_truth[acknowledged_order[0]]["priority"]
        ]
        if first_ack_priority == highest_priority_weight:
            first_ack_score = 0.2

    ordering_score = 0.15 * _ordering_accuracy(acknowledged_order, ground_truth)
    coverage_score = 0.55 * weighted_jaccard

    p1_ids = {
        alert_id
        for alert_id in actionable_ids
        if ground_truth[alert_id]["priority"] == "P1"
    }
    p1_left_unacked = len(p1_ids - acknowledged_ids)
    p1_penalty = 0.1 * p1_left_unacked if done else 0.0
    invalid_penalty = 0.02 * state.get("invalid_actions", 0)

    total = coverage_score + ignore_score + first_ack_score + ordering_score
    total -= p1_penalty + invalid_penalty
    total = _clamp(total)

    breakdown = {
        "coverage_weighted_jaccard": round(weighted_jaccard, 4),
        "coverage_score": round(coverage_score, 4),
        "correctly_ignored_alerts": correct_ignored,
        "ignore_score": round(ignore_score, 4),
        "first_ack_priority_score": round(first_ack_score, 4),
        "ordering_score": round(ordering_score, 4),
        "p1_left_unacknowledged": p1_left_unacked,
        "end_penalty": round(p1_penalty, 4),
        "invalid_action_penalty": round(invalid_penalty, 4),
        "acknowledged_order": acknowledged_order,
        "actionable_ground_truth_order": list(state["actionable_ids"]),
        "score_explanation": (
            "Weighted Jaccard rewards acknowledging the right alerts, while ordering "
            "and ignore bonuses reward good on-call hygiene."
        ),
    }
    return SREReward(value=total, breakdown=breakdown, done=done, info={})
