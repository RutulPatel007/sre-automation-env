from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any

from env.models import SREAction, SREObservation

ALERT_TRIAGE_INFO = {
    "id": "alert_triage",
    "name": "Alert Triage",
    "difficulty": "easy",
    "description": "Prioritize and acknowledge firing alerts in correct severity order.",
    "max_steps": 10,
    "available_actions": ["triage", "acknowledge", "resolve", "escalate"],
}

PRIORITY_BY_SEVERITY = {"critical": "P1", "warning": "P2", "info": "P3"}
PRIORITY_RANK = {"P1": 1, "P2": 2, "P3": 3}
SEVERITY_WEIGHT = {"critical": 3, "warning": 2, "info": 1}


def _sorted_actionable_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        alerts,
        key=lambda alert: (
            PRIORITY_RANK[PRIORITY_BY_SEVERITY[alert["severity"]]],
            alert["fired_at"],
            alert["id"],
        ),
    )


def init_alert_triage_task(
    catalogs: dict[str, Any], service_map: dict[str, list[str]], rng
) -> dict[str, Any]:
    alerts = deepcopy(rng.sample(catalogs["alerts"], k=8))
    actionable_alerts = [
        alert for alert in alerts if not alert["is_flapping"] and not alert["is_duplicate"]
    ]
    actionable_order = _sorted_actionable_alerts(actionable_alerts)
    ground_truth = {
        alert["id"]: {
            "priority": PRIORITY_BY_SEVERITY[alert["severity"]],
            "service": alert["service"],
            "severity": alert["severity"],
        }
        for alert in actionable_order
    }

    for alert in alerts:
        alert["status"] = "pending"
        alert["assigned_priority"] = None

    return {
        "task": "alert_triage",
        "alerts": alerts,
        "actionable_ids": [alert["id"] for alert in actionable_order],
        "ignorable_ids": [
            alert["id"] for alert in alerts if alert["is_flapping"] or alert["is_duplicate"]
        ],
        "ground_truth": ground_truth,
        "triage_decisions": {},
        "acknowledged_order": [],
        "ignored_alert_ids": [],
        "escalated_alert_ids": [],
        "invalid_actions": 0,
        "message": (
            "Triage the alert queue. Use action_type='triage' with parameters "
            "{decision: ignore|actionable, priority: P1|P2|P3}, then use "
            "action_type='acknowledge' on actionable alerts in priority order."
        ),
        "service_map": service_map,
    }


def apply_alert_triage_action(
    state: dict[str, Any], action: SREAction, step_count: int
) -> str:
    alert_lookup = {alert["id"]: alert for alert in state["alerts"]}
    alert = alert_lookup.get(action.target)
    if action.action_type in {"triage", "acknowledge", "escalate"} and alert is None:
        state["invalid_actions"] += 1
        return f"Alert {action.target} was not found in the current queue."

    if action.action_type == "triage":
        decision = str(action.parameters.get("decision", "actionable")).lower()
        priority = str(
            action.parameters.get(
                "priority", PRIORITY_BY_SEVERITY.get(alert["severity"], "P3")
            )
        ).upper()
        state["triage_decisions"][alert["id"]] = {
            "decision": decision,
            "priority": priority,
            "step": step_count + 1,
        }
        alert["assigned_priority"] = priority
        if decision == "ignore":
            if alert["id"] not in state["ignored_alert_ids"]:
                state["ignored_alert_ids"].append(alert["id"])
            alert["status"] = "ignored"
            return f"Alert {alert['id']} was marked as ignorable with priority {priority}."
        alert["status"] = "triaged"
        return f"Alert {alert['id']} was marked actionable with priority {priority}."

    if action.action_type == "acknowledge":
        if alert["id"] in state["acknowledged_order"]:
            state["invalid_actions"] += 1
            return f"Alert {alert['id']} was already acknowledged."
        if alert["is_flapping"] or alert["is_duplicate"]:
            state["invalid_actions"] += 1
            alert["status"] = "mis-acknowledged"
            return (
                f"Alert {alert['id']} should have been ignored because it is "
                "flapping or duplicate."
            )
        priority = action.parameters.get("priority")
        if priority:
            alert["assigned_priority"] = str(priority).upper()
        state["acknowledged_order"].append(alert["id"])
        alert["status"] = "acknowledged"
        return f"Alert {alert['id']} acknowledged for service {alert['service']}."

    if action.action_type == "escalate":
        if alert["id"] not in state["escalated_alert_ids"]:
            state["escalated_alert_ids"].append(alert["id"])
        return f"Alert {alert['id']} escalated to the on-call escalation policy."

    if action.action_type == "resolve":
        return "Alert triage episodes end when all actionable alerts are acknowledged."

    state["invalid_actions"] += 1
    return f"Action {action.action_type} is not supported for alert triage."


def build_alert_triage_observation(
    task_id: str,
    step_count: int,
    state: dict[str, Any],
    service_map: dict[str, list[str]],
    done: bool,
    message: str,
) -> SREObservation:
    per_service: dict[str, dict[str, int]] = defaultdict(
        lambda: {"open_alerts": 0, "critical": 0, "warning": 0, "info": 0}
    )
    for alert in state["alerts"]:
        if alert["status"] not in {"acknowledged", "ignored"}:
            per_service[alert["service"]]["open_alerts"] += 1
        per_service[alert["service"]][alert["severity"]] += 1

    context = {
        "instruction": (
            "Identify non-actionable alerts, assign P1/P2/P3, and acknowledge only "
            "actionable alerts in descending priority order."
        ),
        "triaged_alerts": len(state["triage_decisions"]),
        "acknowledged_alerts": state["acknowledged_order"],
        "ignored_alerts": state["ignored_alert_ids"],
        "remaining_actionable": len(
            [
                alert_id
                for alert_id in state["actionable_ids"]
                if alert_id not in state["acknowledged_order"]
            ]
        ),
        "ground_truth_hidden": False,
    }
    logs = [
        f"{alert['id']} {alert['service']} {alert['severity']}: {alert['message']}"
        for alert in state["alerts"]
    ]

    return SREObservation(
        task_id=task_id,
        step=step_count,
        context=context,
        available_actions=ALERT_TRIAGE_INFO["available_actions"],
        alert_queue=deepcopy(state["alerts"]),
        service_map=service_map,
        metrics={"services": dict(per_service), "queue_depth": len(state["alerts"])},
        logs=logs,
        done=done,
        message=message,
    )


def is_alert_triage_done(
    state: dict[str, Any], step_count: int, max_steps: int
) -> bool:
    actionable_remaining = [
        alert_id
        for alert_id in state["actionable_ids"]
        if alert_id not in state["acknowledged_order"]
    ]
    return not actionable_remaining or step_count >= max_steps
