from __future__ import annotations

from copy import deepcopy
from typing import Any

from env.models import SREAction, SREObservation

ON_CALL_HANDOFF_INFO = {
    "id": "on_call_handoff",
    "name": "On-Call Handoff",
    "difficulty": "easy",
    "description": "Summarize active incidents, pending actions, and service health for the incoming on-call engineer.",
    "max_steps": 6,
    "available_actions": ["summarize", "escalate", "resolve"],
}

SHIFT_CONTEXTS = [
    {
        "shift": "night_to_day",
        "active_incidents": [
            {
                "id": "INC-101",
                "service": "payment-service",
                "severity": "P2",
                "status": "investigating",
                "summary": "Elevated error rate on checkout endpoint",
            },
            {
                "id": "INC-102",
                "service": "db-service",
                "severity": "P3",
                "status": "monitoring",
                "summary": "Replica lag intermittent but self-healing",
            },
        ],
        "pending_actions": [
            "Deploy hotfix v2.4.1 to payment-service",
            "Monitor db replica lag for next 2 hours",
        ],
        "resolved_last_shift": 2,
    },
    {
        "shift": "day_to_evening",
        "active_incidents": [
            {
                "id": "INC-201",
                "service": "auth-service",
                "severity": "P1",
                "status": "mitigating",
                "summary": "JWT validation failures blocking login",
            },
            {
                "id": "INC-202",
                "service": "api-gateway",
                "severity": "P2",
                "status": "investigating",
                "summary": "5xx spike on /login route",
            },
            {
                "id": "INC-203",
                "service": "user-service",
                "severity": "P3",
                "status": "acknowledged",
                "summary": "Profile hydration timeout",
            },
        ],
        "pending_actions": [
            "Rollback auth-service to v3.1.0",
            "Verify api-gateway upstream config",
            "Escalate INC-201 to platform team if not resolved in 30min",
        ],
        "resolved_last_shift": 1,
    },
    {
        "shift": "evening_to_night",
        "active_incidents": [
            {
                "id": "INC-301",
                "service": "payment-service",
                "severity": "P2",
                "status": "monitoring",
                "summary": "Memory pressure after scale-out",
            },
        ],
        "pending_actions": [
            "Verify memory stabilization after 1 hour",
            "Run load test on payment-service before peak traffic",
        ],
        "resolved_last_shift": 3,
    },
]

SERVICE_HEALTH_BASE = {
    "api-gateway": {"status": "healthy", "error_rate": 0.01, "latency_p99": 120},
    "auth-service": {"status": "healthy", "error_rate": 0.008, "latency_p99": 95},
    "user-service": {"status": "healthy", "error_rate": 0.006, "latency_p99": 82},
    "payment-service": {"status": "healthy", "error_rate": 0.01, "latency_p99": 110},
    "db-service": {"status": "healthy", "error_rate": 0.002, "latency_p99": 20},
}


def init_on_call_handoff_task(
    catalogs: dict[str, Any], service_map: dict[str, list[str]], rng
) -> dict[str, Any]:
    context = deepcopy(rng.choice(SHIFT_CONTEXTS))
    health = deepcopy(SERVICE_HEALTH_BASE)
    for inc in context["active_incidents"]:
        svc = inc["service"]
        if svc in health:
            if inc["severity"] == "P1":
                health[svc] = {
                    "status": "critical",
                    "error_rate": 0.25,
                    "latency_p99": 300,
                }
            elif inc["severity"] == "P2":
                health[svc] = {
                    "status": "degraded",
                    "error_rate": 0.12,
                    "latency_p99": 220,
                }
            elif inc["severity"] == "P3":
                health[svc] = {
                    "status": "warning",
                    "error_rate": 0.05,
                    "latency_p99": 150,
                }

    return {
        "task": "on_call_handoff",
        "shift_context": context,
        "service_health": health,
        "service_map": service_map,
        "handoff_summary": None,
        "escalated_incidents": [],
        "invalid_actions": 0,
        "message": (
            "You are the outgoing on-call SRE. Summarize the current shift for the "
            "incoming engineer. Include active incidents, pending actions, and service "
            "health. Use action_type='summarize' with target='handoff' and parameters "
            "containing your summary."
        ),
    }


def apply_on_call_handoff_action(
    state: dict[str, Any], action: SREAction, step_count: int
) -> str:
    if action.action_type == "escalate":
        state["escalated_incidents"].append(action.target)
        return f"Incident {action.target} escalated to the next-level on-call."

    if action.action_type == "resolve":
        if state["handoff_summary"]:
            return "Handoff already submitted; waiting for episode termination."
        state["invalid_actions"] += 1
        return "Resolve is only meaningful after submitting the handoff summary."

    if action.action_type == "summarize":
        summary = str(action.parameters.get("summary", "")).strip()
        if not summary:
            state["invalid_actions"] += 1
            return "Handoff summary cannot be empty."
        state["handoff_summary"] = {
            "summary": summary,
            "step": step_count + 1,
            "active_incidents_count": len(state["shift_context"]["active_incidents"]),
            "pending_actions_count": len(state["shift_context"]["pending_actions"]),
        }
        return "Handoff summary submitted successfully."

    state["invalid_actions"] += 1
    return f"Action {action.action_type} is not supported for on-call handoff."


def build_on_call_handoff_observation(
    task_id: str,
    step_count: int,
    state: dict[str, Any],
    service_map: dict[str, list[str]],
    done: bool,
    message: str,
) -> SREObservation:
    context = {
        "instruction": (
            "Create a concise handoff summary for the incoming on-call engineer. "
            "Include: active incidents with severity, pending actions, service health "
            "highlights, and any risks to watch for."
        ),
        "shift": state["shift_context"]["shift"],
        "active_incidents": state["shift_context"]["active_incidents"],
        "pending_actions": state["shift_context"]["pending_actions"],
        "resolved_last_shift": state["shift_context"]["resolved_last_shift"],
        "service_health": state["service_health"],
        "handoff_submitted": state["handoff_summary"] is not None,
    }
    logs = [
        f"Shift change: {state['shift_context']['shift']} rotation",
        f"{len(state['shift_context']['active_incidents'])} active incident(s) to hand off",
    ]

    return SREObservation(
        task_id=task_id,
        step=step_count,
        context=context,
        available_actions=ON_CALL_HANDOFF_INFO["available_actions"],
        alert_queue=[],
        service_map=service_map,
        metrics={"services": state["service_health"]},
        logs=logs,
        done=done,
        message=message,
    )


def is_on_call_handoff_done(
    state: dict[str, Any], step_count: int, max_steps: int
) -> bool:
    return state["handoff_summary"] is not None or step_count >= max_steps
