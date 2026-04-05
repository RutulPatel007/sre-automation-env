from __future__ import annotations

from copy import deepcopy
from typing import Any

from env.models import SREAction, SREObservation

INCIDENT_DIAGNOSIS_INFO = {
    "id": "incident_diagnosis",
    "name": "Incident Diagnosis",
    "difficulty": "medium",
    "description": "Identify root cause service and failure mode from noisy metrics.",
    "max_steps": 12,
    "available_actions": ["diagnose", "resolve", "escalate"],
}

BASE_METRICS = {
    "api-gateway": {"cpu": 41, "mem": 58, "latency_p99": 120, "error_rate": 0.01},
    "auth-service": {"cpu": 37, "mem": 52, "latency_p99": 95, "error_rate": 0.008},
    "user-service": {"cpu": 35, "mem": 48, "latency_p99": 82, "error_rate": 0.006},
    "payment-service": {"cpu": 43, "mem": 56, "latency_p99": 110, "error_rate": 0.01},
    "db-service": {"cpu": 49, "mem": 63, "latency_p99": 20, "error_rate": 0.002},
}

# SLO targets per service (realistic production SLOs)
SERVICE_SLOS = {
    "api-gateway": {"latency_p99_ms": 200, "error_rate_pct": 1.0, "availability": 99.95},
    "auth-service": {"latency_p99_ms": 150, "error_rate_pct": 0.5, "availability": 99.99},
    "user-service": {"latency_p99_ms": 120, "error_rate_pct": 0.5, "availability": 99.95},
    "payment-service": {"latency_p99_ms": 180, "error_rate_pct": 0.5, "availability": 99.99},
    "db-service": {"latency_p99_ms": 50, "error_rate_pct": 0.1, "availability": 99.999},
}


def _jitter(value: float | int, rng, pct: float = 0.12) -> float | int:
    """Apply random jitter of ±pct to a value, preserving type for ints."""
    factor = 1.0 + rng.uniform(-pct, pct)
    result = value * factor
    if isinstance(value, int):
        return max(0, int(round(result)))
    return max(0.0, round(result, 4))


def _apply_jitter_to_metrics(
    metrics: dict[str, dict[str, Any]], rng
) -> dict[str, dict[str, Any]]:
    """Apply random noise to all metric values so each reset is unique."""
    jittered = {}
    for service, service_metrics in metrics.items():
        jittered[service] = {
            key: _jitter(val, rng, pct=0.12)
            for key, val in service_metrics.items()
        }
    return jittered


def _apply_incident_metrics(scenario: dict[str, Any]) -> dict[str, dict[str, Any]]:
    metrics = deepcopy(BASE_METRICS)
    service = scenario["service"]
    if service == "db-service":
        metrics["db-service"].update({"cpu": 84, "mem": 79, "latency_p99": 460, "error_rate": 0.03})
        metrics["payment-service"].update(
            {"cpu": 71, "mem": 66, "latency_p99": 320, "error_rate": 0.08}
        )
        metrics["auth-service"].update(
            {"cpu": 55, "mem": 58, "latency_p99": 190, "error_rate": 0.03}
        )
        metrics["api-gateway"].update(
            {"cpu": 62, "mem": 64, "latency_p99": 260, "error_rate": 0.04}
        )
    elif service == "auth-service":
        metrics["auth-service"].update(
            {"cpu": 59, "mem": 68, "latency_p99": 180, "error_rate": 0.24}
        )
        metrics["api-gateway"].update(
            {"cpu": 63, "mem": 67, "latency_p99": 225, "error_rate": 0.18}
        )
    elif service == "payment-service":
        metrics["payment-service"].update(
            {"cpu": 78, "mem": 97, "latency_p99": 280, "error_rate": 0.12}
        )
        metrics["auth-service"].update(
            {"cpu": 57, "mem": 63, "latency_p99": 165, "error_rate": 0.05}
        )
        metrics["api-gateway"].update(
            {"cpu": 61, "mem": 65, "latency_p99": 210, "error_rate": 0.04}
        )
    elif service == "api-gateway":
        metrics["api-gateway"].update(
            {"cpu": 64, "mem": 60, "latency_p99": 300, "error_rate": 0.31}
        )
    elif service == "user-service":
        metrics["user-service"].update(
            {"cpu": 56, "mem": 61, "latency_p99": 240, "error_rate": 0.19}
        )
        metrics["auth-service"].update(
            {"cpu": 52, "mem": 60, "latency_p99": 170, "error_rate": 0.08}
        )
        metrics["api-gateway"].update(
            {"cpu": 58, "mem": 65, "latency_p99": 195, "error_rate": 0.06}
        )
    return metrics


def _build_logs(scenario: dict[str, Any]) -> dict[str, list[str]]:
    normal_logs = {
        "api-gateway": [
            "route cache warmup completed",
            "edge auth policy refreshed",
        ],
        "auth-service": [
            "jwt signing keys rotated successfully",
            "token cache hit ratio steady at 0.93",
        ],
        "user-service": [
            "profile aggregation pipeline healthy",
            "read replica lag under 10ms",
        ],
        "payment-service": [
            "checkout authorization median stable",
            "settlement worker backlog cleared",
        ],
        "db-service": [
            "autovacuum completed on ledger_entries",
            "read pool healthy with 18 active connections",
        ],
    }

    scenario_logs = {
        "db-service": [
            "slow query detected on ledger_entries: 428ms",
            "connection pool wait exceeded 200ms",
            "disk spill observed during payment reconciliation",
        ],
        "auth-service": [
            "upstream OAuth provider returned invalid audience",
            "login request rejected with signature verification error",
            "token introspection error rate exceeded SLO",
        ],
        "payment-service": [
            "worker restarted after memory limit breach",
            "heap growth detected in checkout-session manager",
            "OOM killer terminated pid 4412 on payment pod",
        ],
        "api-gateway": [
            "config drift detected: upstream target set to auth-v1-shadow",
            "404 spike on /login due to invalid upstream cluster",
            "reload succeeded but checksum mismatch persists",
        ],
        "user-service": [
            "deprecated /v1/profile endpoint returned 410 Gone",
            "fallback client still calling sunset endpoint",
            "retry storm detected for user profile hydration",
        ],
    }
    root_service = scenario["service"]
    normal_logs[root_service] = scenario_logs[root_service]
    return normal_logs


def _build_incident_timeline(scenario: dict[str, Any], rng) -> list[dict[str, str]]:
    """Build a realistic incident timeline with timestamped events."""
    base_hour = rng.randint(0, 23)
    base_min = rng.randint(0, 45)
    service = scenario["service"]

    timeline_templates = {
        "db-service": [
            ("T+0m", f"PagerDuty alert: {service} p99 latency > 400ms"),
            ("T+1m", "Upstream payment-service reports increased timeouts"),
            ("T+2m", "auth-service latency degraded — possible cascade"),
            ("T+3m", "api-gateway 5xx rate climbing, customer-facing impact"),
            ("T+5m", "On-call SRE acknowledged the incident"),
        ],
        "auth-service": [
            ("T+0m", f"PagerDuty alert: {service} error rate > 20%"),
            ("T+1m", "Login flow failures reported by customer support"),
            ("T+2m", "api-gateway returning 401/403 at elevated rate"),
            ("T+4m", "On-call SRE acknowledged the incident"),
        ],
        "payment-service": [
            ("T+0m", f"PagerDuty alert: {service} pod restarted (OOM killed)"),
            ("T+1m", "Checkout flow latency increased to 280ms p99"),
            ("T+2m", "Second pod restart observed, memory climbing on remaining pods"),
            ("T+3m", "auth-service showing mild impact from backpressure"),
            ("T+5m", "On-call SRE acknowledged the incident"),
        ],
        "api-gateway": [
            ("T+0m", f"PagerDuty alert: {service} 5xx rate > 30%"),
            ("T+1m", "Customers reporting blank login page"),
            ("T+3m", "Config reload attempted but no improvement"),
            ("T+4m", "On-call SRE acknowledged the incident"),
        ],
        "user-service": [
            ("T+0m", f"PagerDuty alert: {service} 410 errors spiking"),
            ("T+1m", "Profile hydration failures cascading to auth-service"),
            ("T+2m", "api-gateway error rate climbing from upstream failures"),
            ("T+4m", "On-call SRE acknowledged the incident"),
        ],
    }
    events = timeline_templates.get(service, [])
    return [
        {"time": t, "event": e, "utc": f"2026-03-15T{base_hour:02d}:{base_min:02d}:00Z"}
        for t, e in events
    ]


def _compute_slo_status(
    metrics: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Compute SLO burn rate and budget remaining per service."""
    slo_status = {}
    for service, slos in SERVICE_SLOS.items():
        current = metrics.get(service, {})
        latency = current.get("latency_p99", 0)
        error_rate = current.get("error_rate", 0) * 100  # convert to pct

        latency_budget_burn = max(0.0, (latency - slos["latency_p99_ms"]) / slos["latency_p99_ms"])
        error_budget_burn = max(0.0, (error_rate - slos["error_rate_pct"]) / slos["error_rate_pct"])

        slo_status[service] = {
            "latency_slo_ms": slos["latency_p99_ms"],
            "latency_current_ms": latency,
            "latency_budget_burn_rate": round(latency_budget_burn, 3),
            "error_slo_pct": slos["error_rate_pct"],
            "error_current_pct": round(error_rate, 3),
            "error_budget_burn_rate": round(error_budget_burn, 3),
            "slo_breached": latency_budget_burn > 0 or error_budget_burn > 0,
        }
    return slo_status


def init_incident_diagnosis_task(
    catalogs: dict[str, Any], service_map: dict[str, list[str]], rng
) -> dict[str, Any]:
    scenario = deepcopy(rng.choice(catalogs["incidents"]))
    raw_metrics = _apply_incident_metrics(scenario)
    full_metrics = _apply_jitter_to_metrics(raw_metrics, rng)
    visible_metrics = {
        service: {"status": "query_metrics_required"} for service in full_metrics
    }
    slo_status = _compute_slo_status(full_metrics)
    timeline = _build_incident_timeline(scenario, rng)

    return {
        "task": "incident_diagnosis",
        "incident": scenario,
        "full_metrics": full_metrics,
        "visible_metrics": visible_metrics,
        "service_logs": _build_logs(scenario),
        "visible_logs": [],
        "queried_metrics": [],
        "queried_logs": [],
        "submitted_diagnosis": None,
        "escalations": [],
        "invalid_actions": 0,
        "slo_status": slo_status,
        "incident_timeline": timeline,
        "message": (
            "A production incident is in progress. Use action_type='diagnose' with "
            "parameters.operation set to 'query_metrics', 'query_logs', or "
            "'submit_diagnosis'. Submit the root cause service in target and include "
            "failure_mode in parameters. Use the SLO status and incident timeline "
            "to guide your investigation."
        ),
        "service_map": service_map,
    }


def apply_incident_diagnosis_action(
    state: dict[str, Any], action: SREAction, step_count: int
) -> str:
    if action.action_type == "escalate":
        state["escalations"].append(
            {"service": action.target, "step": step_count + 1, "reason": action.reasoning}
        )
        return f"Escalation recorded for {action.target}."

    if action.action_type == "resolve":
        if state["submitted_diagnosis"]:
            return "Diagnosis already submitted; waiting for episode termination."
        state["invalid_actions"] += 1
        return "Resolve is only meaningful after you submit a diagnosis."

    operation = str(action.parameters.get("operation", "")).lower()
    if action.action_type != "diagnose" or operation not in {
        "query_metrics",
        "query_logs",
        "submit_diagnosis",
    }:
        state["invalid_actions"] += 1
        return (
            "For incident diagnosis, use action_type='diagnose' with operation "
            "query_metrics, query_logs, or submit_diagnosis."
        )

    if action.target not in state["full_metrics"]:
        state["invalid_actions"] += 1
        return f"Service {action.target} is not part of the incident topology."

    if operation == "query_metrics":
        if action.target not in state["queried_metrics"]:
            state["queried_metrics"].append(action.target)
        state["visible_metrics"][action.target] = deepcopy(state["full_metrics"][action.target])
        return f"Metrics revealed for {action.target}."

    if operation == "query_logs":
        if action.target not in state["queried_logs"]:
            state["queried_logs"].append(action.target)
            state["visible_logs"].extend(
                [f"{action.target}: {line}" for line in state["service_logs"][action.target]]
            )
        return f"Logs revealed for {action.target}."

    failure_mode = str(action.parameters.get("failure_mode", "")).strip()
    state["submitted_diagnosis"] = {
        "service": action.target,
        "failure_mode": failure_mode,
        "step": step_count + 1,
    }
    return (
        f"Diagnosis submitted: root cause service={action.target}, "
        f"failure_mode={failure_mode or 'unspecified'}."
    )


def build_incident_diagnosis_observation(
    task_id: str,
    step_count: int,
    state: dict[str, Any],
    service_map: dict[str, list[str]],
    done: bool,
    message: str,
) -> SREObservation:
    context = {
        "instruction": (
            "A production incident is in progress. Query metrics and logs selectively "
            "to identify the root cause. Use the SLO status to identify which services "
            "are breaching their error budgets. Submit your diagnosis using "
            "action_type='diagnose' and parameters.operation='submit_diagnosis'."
        ),
        "service_topology": {
            "api-gateway": ["auth-service"],
            "auth-service": ["user-service", "payment-service"],
            "payment-service": ["db-service"],
        },
        "service_topology_hint": "api-gateway -> auth-service -> user-service; payment-service -> db-service",
        "incident_timeline": state.get("incident_timeline", []),
        "slo_status": state.get("slo_status", {}),
        "queried_metrics": state["queried_metrics"],
        "queried_logs": state["queried_logs"],
        "submitted_diagnosis": state["submitted_diagnosis"],
        "failure_mode_options": [
            "high latency",
            "high error rate",
            "memory leak",
            "config drift",
            "deprecated endpoint dependency",
        ],
    }
    return SREObservation(
        task_id=task_id,
        step=step_count,
        context=context,
        available_actions=INCIDENT_DIAGNOSIS_INFO["available_actions"],
        alert_queue=[],
        service_map=service_map,
        metrics=deepcopy(state["visible_metrics"]),
        logs=list(state["visible_logs"]),
        done=done,
        message=message,
    )


def is_incident_diagnosis_done(
    state: dict[str, Any], step_count: int, max_steps: int
) -> bool:
    return state["submitted_diagnosis"] is not None or step_count >= max_steps
