from __future__ import annotations

from copy import deepcopy
from typing import Any

from env.models import SREAction, SREObservation

BLAMELESS_POSTMORTEM_INFO = {
    "id": "blameless_postmortem",
    "name": "Blameless Postmortem Generation",
    "difficulty": "hard",
    "description": "Synthesize incident timeline, root cause analysis, and actionable follow-ups into a blameless postmortem document.",
    "max_steps": 8,
    "available_actions": ["write_postmortem", "diagnose", "escalate", "resolve"],
}

POSTMORTEM_INCIDENTS = [
    {
        "id": "POST-1",
        "title": "Payment Service Outage - March 15, 2026",
        "severity": "SEV-1",
        "duration_minutes": 47,
        "affected_services": ["payment-service", "db-service", "api-gateway"],
        "customer_impact": "Checkout failures for ~12,000 users, estimated $85K revenue loss",
        "timeline": [
            {
                "time": "14:23",
                "event": "db-service latency spike detected, p99 > 400ms",
            },
            {"time": "14:25", "event": "payment-service reports checkout timeouts"},
            {"time": "14:28", "event": "api-gateway 5xx rate exceeds 15% threshold"},
            {"time": "14:30", "event": "PagerDuty alert fired, on-call acknowledged"},
            {"time": "14:35", "event": "On-call identified db-service as root cause"},
            {
                "time": "14:42",
                "event": "Database connection pool increased from 100 to 200",
            },
            {"time": "14:55", "event": "Latency normalized, checkout flow recovered"},
            {"time": "15:10", "event": "Incident declared resolved"},
        ],
        "root_cause": "Database connection pool exhaustion during peak traffic. A slow query on the ledger_entries table held connections open, starving the checkout path.",
        "contributing_factors": [
            "Connection pool size was not scaled with traffic growth (15% MoM increase)",
            "No circuit breaker on payment-service to db-service calls",
            "Slow query alerting threshold was set too high at 500ms",
        ],
        "action_items": [
            {
                "action": "Increase db connection pool to 300 with auto-scaling",
                "owner": "DBA team",
                "priority": "P1",
            },
            {
                "action": "Implement circuit breaker on payment-service",
                "owner": "Payment team",
                "priority": "P1",
            },
            {
                "action": "Lower slow query alert threshold to 200ms",
                "owner": "SRE team",
                "priority": "P2",
            },
            {
                "action": "Add runbook for connection pool exhaustion",
                "owner": "SRE team",
                "priority": "P2",
            },
        ],
        "detection_time_minutes": 7,
        "mitigation_time_minutes": 19,
        "resolution_time_minutes": 47,
    },
    {
        "id": "POST-2",
        "title": "Auth Service Login Failures - March 18, 2026",
        "severity": "SEV-1",
        "duration_minutes": 32,
        "affected_services": ["auth-service", "api-gateway"],
        "customer_impact": "Login failures for ~8,000 users, support ticket spike",
        "timeline": [
            {"time": "09:15", "event": "JWT signing key rotation initiated"},
            {
                "time": "09:17",
                "event": "New key not propagated to all auth-service pods",
            },
            {"time": "09:18", "event": "Login failures spike, error rate > 20%"},
            {"time": "09:22", "event": "PagerDuty alert fired"},
            {"time": "09:28", "event": "On-call identified key propagation issue"},
            {"time": "09:35", "event": "Manual key sync across all pods"},
            {"time": "09:47", "event": "Login flow recovered, incident resolved"},
        ],
        "root_cause": "JWT signing key rotation did not propagate to all auth-service pods due to a race condition in the key distribution service.",
        "contributing_factors": [
            "Key distribution service had a 60-second sync interval (too slow)",
            "No validation step after key rotation to confirm all pods received new key",
            "Rollback procedure for key rotation was not documented",
        ],
        "action_items": [
            {
                "action": "Reduce key sync interval to 5 seconds",
                "owner": "Auth team",
                "priority": "P1",
            },
            {
                "action": "Add post-rotation validation check",
                "owner": "Auth team",
                "priority": "P1",
            },
            {
                "action": "Document key rotation rollback procedure",
                "owner": "SRE team",
                "priority": "P2",
            },
        ],
        "detection_time_minutes": 4,
        "mitigation_time_minutes": 10,
        "resolution_time_minutes": 32,
    },
]


def init_blameless_postmortem_task(
    catalogs: dict[str, Any], service_map: dict[str, list[str]], rng
) -> dict[str, Any]:
    incident = deepcopy(rng.choice(POSTMORTEM_INCIDENTS))
    return {
        "task": "blameless_postmortem",
        "incident": incident,
        "sections_written": [],
        "postmortem_submitted": None,
        "queried_data": [],
        "escalated": False,
        "invalid_actions": 0,
        "service_map": service_map,
        "message": (
            "Write a blameless postmortem for the given incident. Use "
            "action_type='diagnose' with operation='query_timeline' or "
            "'query_impact' to gather data, then action_type='write_postmortem' "
            "with parameters containing the section name and content. Required "
            "sections: summary, timeline, root_cause, impact, action_items."
        ),
    }


def apply_blameless_postmortem_action(
    state: dict[str, Any], action: SREAction, step_count: int
) -> str:
    incident = state["incident"]

    if action.action_type == "escalate":
        state["escalated"] = True
        return "Postmortem escalated to the engineering manager for review."

    if action.action_type == "resolve":
        if state["postmortem_submitted"]:
            return "Postmortem already submitted."
        state["invalid_actions"] += 1
        return "Resolve is only meaningful after submitting the postmortem."

    if action.action_type == "diagnose":
        operation = str(action.parameters.get("operation", "")).lower()
        if operation == "query_timeline":
            if "timeline" not in state["queried_data"]:
                state["queried_data"].append("timeline")
            return f"Timeline: {len(incident['timeline'])} events from {incident['timeline'][0]['time']} to {incident['timeline'][-1]['time']}."
        elif operation == "query_impact":
            if "impact" not in state["queried_data"]:
                state["queried_data"].append("impact")
            return (
                f"Impact: {incident['customer_impact']}. "
                f"Duration: {incident['duration_minutes']}min. "
                f"Detection: {incident['detection_time_minutes']}min, "
                f"Mitigation: {incident['mitigation_time_minutes']}min, "
                f"Resolution: {incident['resolution_time_minutes']}min."
            )
        elif operation == "query_root_cause":
            if "root_cause" not in state["queried_data"]:
                state["queried_data"].append("root_cause")
            return f"Root cause: {incident['root_cause']}"
        elif operation == "query_action_items":
            if "action_items" not in state["queried_data"]:
                state["queried_data"].append("action_items")
            return f"Action items: {len(incident['action_items'])} items identified."
        state["invalid_actions"] += 1
        return "Use operation: query_timeline, query_impact, query_root_cause, or query_action_items."

    if action.action_type == "write_postmortem":
        section = str(action.parameters.get("section", "")).strip()
        content = str(action.parameters.get("content", "")).strip()
        if not section or not content:
            state["invalid_actions"] += 1
            return "Both 'section' and 'content' parameters are required."

        valid_sections = ["summary", "timeline", "root_cause", "impact", "action_items"]
        if section not in valid_sections:
            state["invalid_actions"] += 1
            return f"Invalid section '{section}'. Valid sections: {valid_sections}."

        state["sections_written"].append(section)
        if state["postmortem_submitted"] is None:
            state["postmortem_submitted"] = {}
        state["postmortem_submitted"][section] = {
            "content": content,
            "step": step_count + 1,
            "word_count": len(content.split()),
        }
        return f"Section '{section}' written ({len(content.split())} words)."

    state["invalid_actions"] += 1
    return f"Action {action.action_type} is not supported for blameless postmortem."


def build_blameless_postmortem_observation(
    task_id: str,
    step_count: int,
    state: dict[str, Any],
    service_map: dict[str, list[str]],
    done: bool,
    message: str,
) -> SREObservation:
    incident = state["incident"]
    context = {
        "instruction": (
            "Write a blameless postmortem with these required sections: "
            "summary, timeline, root_cause, impact, action_items. "
            "Query incident data first, then write each section using "
            "action_type='write_postmortem'."
        ),
        "incident_id": incident["id"],
        "incident_title": incident["title"],
        "severity": incident["severity"],
        "affected_services": incident["affected_services"],
        "sections_required": [
            "summary",
            "timeline",
            "root_cause",
            "impact",
            "action_items",
        ],
        "sections_written": state["sections_written"],
        "sections_remaining": [
            s
            for s in ["summary", "timeline", "root_cause", "impact", "action_items"]
            if s not in state["sections_written"]
        ],
        "queried_data": state["queried_data"],
        "postmortem_submitted": state["postmortem_submitted"] is not None,
    }
    logs = [
        f"Postmortem requested for {incident['title']}",
        f"Severity: {incident['severity']}, Duration: {incident['duration_minutes']}min",
        f"Affected services: {', '.join(incident['affected_services'])}",
    ]

    return SREObservation(
        task_id=task_id,
        step=step_count,
        context=context,
        available_actions=BLAMELESS_POSTMORTEM_INFO["available_actions"],
        alert_queue=[],
        service_map=service_map,
        metrics={
            "sections_complete": len(state["sections_written"]),
            "sections_total": 5,
        },
        logs=logs,
        done=done,
        message=message,
    )


def is_blameless_postmortem_done(
    state: dict[str, Any], step_count: int, max_steps: int
) -> bool:
    required = {"summary", "timeline", "root_cause", "impact", "action_items"}
    return required.issubset(set(state["sections_written"])) or step_count >= max_steps
