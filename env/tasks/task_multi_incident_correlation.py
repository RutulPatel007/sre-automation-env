from __future__ import annotations

from copy import deepcopy
from typing import Any

from env.models import SREAction, SREObservation

MULTI_INCIDENT_CORRELATION_INFO = {
    "id": "multi_incident_correlation",
    "name": "Multi-Incident Correlation",
    "difficulty": "medium",
    "description": "Identify whether multiple simultaneous alerts share a common root cause or are independent incidents.",
    "max_steps": 10,
    "available_actions": ["correlate", "diagnose", "escalate", "resolve"],
}

CORRELATION_SCENARIOS = [
    {
        "id": "CORR-A",
        "type": "shared_root_cause",
        "alerts": [
            {
                "id": "ALT-101",
                "service": "api-gateway",
                "severity": "critical",
                "message": "5xx rate > 15%",
            },
            {
                "id": "ALT-102",
                "service": "auth-service",
                "severity": "critical",
                "message": "Error rate > 20%",
            },
            {
                "id": "ALT-103",
                "service": "db-service",
                "severity": "warning",
                "message": "Connection pool exhaustion",
            },
        ],
        "root_cause": "db-service",
        "root_cause_failure": "connection pool exhaustion causing cascade",
        "independent_alerts": [],
    },
    {
        "id": "CORR-B",
        "type": "independent_incidents",
        "alerts": [
            {
                "id": "ALT-201",
                "service": "payment-service",
                "severity": "critical",
                "message": "OOM restart on checkout worker",
            },
            {
                "id": "ALT-202",
                "service": "user-service",
                "severity": "warning",
                "message": "Deprecated endpoint 410 errors",
            },
            {
                "id": "ALT-203",
                "service": "api-gateway",
                "severity": "warning",
                "message": "Config reload checksum mismatch",
            },
        ],
        "root_cause": None,
        "root_cause_failure": None,
        "independent_alerts": ["ALT-201", "ALT-202", "ALT-203"],
    },
    {
        "id": "CORR-C",
        "type": "partial_correlation",
        "alerts": [
            {
                "id": "ALT-301",
                "service": "payment-service",
                "severity": "critical",
                "message": "Latency spike on checkout",
            },
            {
                "id": "ALT-302",
                "service": "db-service",
                "severity": "critical",
                "message": "Slow queries on ledger table",
            },
            {
                "id": "ALT-303",
                "service": "auth-service",
                "severity": "warning",
                "message": "Token cache miss rate elevated",
            },
        ],
        "root_cause": "db-service",
        "root_cause_failure": "slow queries affecting payment-service only",
        "independent_alerts": ["ALT-303"],
    },
]


def init_multi_incident_correlation_task(
    catalogs: dict[str, Any], service_map: dict[str, list[str]], rng
) -> dict[str, Any]:
    scenario = deepcopy(rng.choice(CORRELATION_SCENARIOS))
    visible_alerts = deepcopy(scenario["alerts"])
    for alert in visible_alerts:
        alert["status"] = "pending"
        alert["correlated_with"] = None

    return {
        "task": "multi_incident_correlation",
        "scenario": scenario,
        "alerts": visible_alerts,
        "queried_services": [],
        "correlation_submitted": None,
        "escalated_alerts": [],
        "invalid_actions": 0,
        "service_map": service_map,
        "message": (
            "Multiple alerts are firing simultaneously. Determine if they share a "
            "common root cause or are independent. Use action_type='diagnose' to query "
            "metrics for services, then action_type='correlate' with parameters "
            "containing your correlation analysis."
        ),
    }


def apply_multi_incident_correlation_action(
    state: dict[str, Any], action: SREAction, step_count: int
) -> str:
    scenario = state["scenario"]

    if action.action_type == "escalate":
        state["escalated_alerts"].append(action.target)
        return f"Alert {action.target} escalated for separate investigation."

    if action.action_type == "resolve":
        if state["correlation_submitted"]:
            return "Correlation already submitted; waiting for episode termination."
        state["invalid_actions"] += 1
        return "Resolve is only meaningful after submitting correlation analysis."

    if action.action_type == "diagnose":
        operation = str(action.parameters.get("operation", "")).lower()
        if operation != "query_metrics":
            state["invalid_actions"] += 1
            return "Use operation='query_metrics' for correlation tasks."
        if action.target not in state["queried_services"]:
            state["queried_services"].append(action.target)
        alert_services = {a["service"] for a in state["alerts"]}
        if action.target not in alert_services:
            state["invalid_actions"] += 1
            return f"Service {action.target} is not part of the current alert set."
        return f"Metrics queried for {action.target}. Check for anomalous patterns."

    if action.action_type == "correlate":
        correlation_type = str(action.parameters.get("correlation_type", "")).lower()
        root_cause = str(action.parameters.get("root_cause_service", "")).strip()
        alert_ids = action.parameters.get("alert_ids", [])
        if not isinstance(alert_ids, list):
            alert_ids = [alert_ids]

        state["correlation_submitted"] = {
            "correlation_type": correlation_type,
            "root_cause_service": root_cause,
            "alert_ids": alert_ids,
            "step": step_count + 1,
        }
        return (
            f"Correlation submitted: type={correlation_type}, "
            f"root_cause={root_cause or 'none'}, alerts={alert_ids}."
        )

    state["invalid_actions"] += 1
    return (
        f"Action {action.action_type} is not supported for multi-incident correlation."
    )


def build_multi_incident_correlation_observation(
    task_id: str,
    step_count: int,
    state: dict[str, Any],
    service_map: dict[str, list[str]],
    done: bool,
    message: str,
) -> SREObservation:
    context = {
        "instruction": (
            "Analyze the firing alerts and determine correlation. Options: "
            "shared_root_cause (all alerts from one root cause), "
            "independent_incidents (each alert is separate), or "
            "partial_correlation (some share a root cause, others are independent). "
            "Use action_type='correlate' with correlation_type, root_cause_service, "
            "and alert_ids in parameters."
        ),
        "alerts": state["alerts"],
        "queried_services": state["queried_services"],
        "service_topology": service_map,
        "correlation_submitted": state["correlation_submitted"] is not None,
    }
    logs = [
        f"{a['id']} {a['service']} {a['severity']}: {a['message']}"
        for a in state["alerts"]
    ]

    return SREObservation(
        task_id=task_id,
        step=step_count,
        context=context,
        available_actions=MULTI_INCIDENT_CORRELATION_INFO["available_actions"],
        alert_queue=state["alerts"],
        service_map=service_map,
        metrics={"queried_services": state["queried_services"]},
        logs=logs,
        done=done,
        message=message,
    )


def is_multi_incident_correlation_done(
    state: dict[str, Any], step_count: int, max_steps: int
) -> bool:
    return state["correlation_submitted"] is not None or step_count >= max_steps
