from __future__ import annotations

from copy import deepcopy
from typing import Any

from env.models import SREAction, SREObservation

CHAOS_ENGINEERING_INFO = {
    "id": "chaos_engineering",
    "name": "Chaos Engineering Scenario",
    "difficulty": "hard",
    "description": "Inject a controlled failure, observe system impact, and execute mitigation steps to restore stability.",
    "max_steps": 12,
    "available_actions": [
        "inject_chaos",
        "observe_impact",
        "mitigate_chaos",
        "escalate",
        "resolve",
    ],
}

CHAOS_SCENARIOS = [
    {
        "id": "CHAOS-A",
        "failure_type": "network_partition",
        "target_service": "payment-service",
        "description": "Simulate network partition between payment-service and db-service",
        "impact": {
            "payment-service": {
                "status": "degraded",
                "error_rate": 0.35,
                "latency_p99": 5000,
                "note": "timeout waiting for db responses",
            },
            "db-service": {
                "status": "healthy",
                "error_rate": 0.002,
                "latency_p99": 20,
                "note": "isolated but healthy",
            },
            "api-gateway": {
                "status": "degraded",
                "error_rate": 0.15,
                "latency_p99": 350,
                "note": "upstream payment failures",
            },
        },
        "mitigation_steps": [
            {
                "step": "enable_circuit_breaker",
                "description": "Enable circuit breaker on payment-service to fail fast",
                "effect": "reduces latency, errors become predictable",
            },
            {
                "step": "enable_fallback",
                "description": "Enable cached payment status fallback",
                "effect": "serves stale data, reduces user-facing errors",
            },
            {
                "step": "restore_network",
                "description": "Restore network connectivity between services",
                "effect": "full recovery",
            },
        ],
        "correct_order": [
            "enable_circuit_breaker",
            "enable_fallback",
            "restore_network",
        ],
    },
    {
        "id": "CHAOS-B",
        "failure_type": "pod_termination",
        "target_service": "auth-service",
        "description": "Randomly terminate 2 of 3 auth-service pods",
        "impact": {
            "auth-service": {
                "status": "critical",
                "error_rate": 0.45,
                "latency_p99": 800,
                "note": "single pod handling 3x traffic",
            },
            "api-gateway": {
                "status": "degraded",
                "error_rate": 0.22,
                "latency_p99": 400,
                "note": "auth failures causing login errors",
            },
            "user-service": {
                "status": "warning",
                "error_rate": 0.08,
                "latency_p99": 180,
                "note": "mild impact from auth retries",
            },
        },
        "mitigation_steps": [
            {
                "step": "scale_out_pods",
                "description": "Scale auth-service from 1 to 4 pods",
                "effect": "reduces load per pod",
            },
            {
                "step": "enable_rate_limiting",
                "description": "Rate limit auth requests to prevent cascade",
                "effect": "protects downstream services",
            },
            {
                "step": "verify_auth_health",
                "description": "Verify all auth pods are healthy and serving",
                "effect": "confirms recovery",
            },
        ],
        "correct_order": [
            "scale_out_pods",
            "enable_rate_limiting",
            "verify_auth_health",
        ],
    },
    {
        "id": "CHAOS-C",
        "failure_type": "database_failover",
        "target_service": "db-service",
        "description": "Trigger primary-to-replica database failover",
        "impact": {
            "db-service": {
                "status": "critical",
                "error_rate": 0.60,
                "latency_p99": 10000,
                "note": "failover in progress, writes blocked",
            },
            "payment-service": {
                "status": "critical",
                "error_rate": 0.50,
                "latency_p99": 8000,
                "note": "all db writes failing",
            },
            "auth-service": {
                "status": "degraded",
                "error_rate": 0.15,
                "latency_p99": 300,
                "note": "read queries hitting replica",
            },
        },
        "mitigation_steps": [
            {
                "step": "enable_read_only_mode",
                "description": "Switch payment-service to read-only mode",
                "effect": "prevents write errors, serves cached data",
            },
            {
                "step": "monitor_failover_progress",
                "description": "Monitor DB failover status",
                "effect": "visibility into recovery timeline",
            },
            {
                "step": "resume_writes",
                "description": "Resume write operations after failover completes",
                "effect": "full recovery",
            },
        ],
        "correct_order": [
            "enable_read_only_mode",
            "monitor_failover_progress",
            "resume_writes",
        ],
    },
]


def init_chaos_engineering_task(
    catalogs: dict[str, Any], service_map: dict[str, list[str]], rng
) -> dict[str, Any]:
    scenario = deepcopy(rng.choice(CHAOS_SCENARIOS))
    return {
        "task": "chaos_engineering",
        "scenario": scenario,
        "chaos_injected": False,
        "impact_observed": False,
        "mitigation_steps_completed": [],
        "mitigation_in_wrong_order": 0,
        "final_state": None,
        "escalated": False,
        "invalid_actions": 0,
        "service_map": service_map,
        "message": (
            "You are running a chaos engineering experiment. Inject the failure, "
            "observe the impact on the service topology, then execute mitigation "
            "steps in the correct order. Use action_type='inject_chaos' to start, "
            "action_type='observe_impact' to check effects, and "
            "action_type='mitigate_chaos' with the mitigation step name."
        ),
    }


def apply_chaos_engineering_action(
    state: dict[str, Any], action: SREAction, step_count: int
) -> str:
    scenario = state["scenario"]

    if action.action_type == "escalate":
        state["escalated"] = True
        return f"Chaos experiment for {scenario['target_service']} escalated to stop the experiment."

    if action.action_type == "resolve":
        if state["final_state"]:
            return "Chaos experiment already concluded."
        state["invalid_actions"] += 1
        return "Resolve is only meaningful after completing the chaos experiment."

    if action.action_type == "inject_chaos":
        if state["chaos_injected"]:
            return "Chaos already injected. Observe impact or begin mitigation."
        state["chaos_injected"] = True
        return (
            f"Chaos injected: {scenario['description']}. "
            f"Use action_type='observe_impact' to see the effects."
        )

    if action.action_type == "observe_impact":
        if not state["chaos_injected"]:
            state["invalid_actions"] += 1
            return (
                "No chaos has been injected yet. Use action_type='inject_chaos' first."
            )
        state["impact_observed"] = True
        impact_summary = "; ".join(
            f"{svc}: {data['note']}" for svc, data in scenario["impact"].items()
        )
        return f"Impact observed: {impact_summary}"

    if action.action_type == "mitigate_chaos":
        if not state["chaos_injected"]:
            state["invalid_actions"] += 1
            return "No chaos has been injected yet."
        step_name = str(action.parameters.get("step", "")).strip()
        if not step_name:
            state["invalid_actions"] += 1
            return "Must specify mitigation step name in parameters."

        valid_steps = {s["step"] for s in scenario["mitigation_steps"]}
        if step_name not in valid_steps:
            state["invalid_actions"] += 1
            return f"Invalid mitigation step. Options: {sorted(valid_steps)}."

        if step_name in state["mitigation_steps_completed"]:
            state["invalid_actions"] += 1
            return f"Mitigation step '{step_name}' already completed."

        expected_step = scenario["correct_order"][
            len(state["mitigation_steps_completed"])
        ]
        step_info = next(
            s for s in scenario["mitigation_steps"] if s["step"] == step_name
        )

        if step_name != expected_step:
            state["mitigation_in_wrong_order"] += 1
            return (
                f"Out-of-order mitigation. Expected '{expected_step}' next, "
                f"got '{step_name}'. {step_info['description']}."
            )

        state["mitigation_steps_completed"].append(step_name)
        all_done = len(state["mitigation_steps_completed"]) == len(
            scenario["correct_order"]
        )

        if all_done:
            state["final_state"] = {
                "outcome": "recovered",
                "steps_completed": state["mitigation_steps_completed"],
                "wrong_order_attempts": state["mitigation_in_wrong_order"],
                "step": step_count + 1,
            }
            return (
                f"Mitigation step '{step_name}' completed: {step_info['effect']}. "
                f"All mitigation steps complete! System recovered."
            )

        return (
            f"Mitigation step '{step_name}' completed: {step_info['effect']}. "
            f"Continue with remaining steps."
        )

    state["invalid_actions"] += 1
    return f"Action {action.action_type} is not supported for chaos engineering."


def build_chaos_engineering_observation(
    task_id: str,
    step_count: int,
    state: dict[str, Any],
    service_map: dict[str, list[str]],
    done: bool,
    message: str,
) -> SREObservation:
    scenario = state["scenario"]
    visible_impact = {}
    if state["impact_observed"]:
        visible_impact = scenario["impact"]

    context = {
        "instruction": (
            "Run a chaos engineering experiment: inject failure, observe impact, "
            "then mitigate in the correct order. Mitigation steps must be executed "
            "sequentially."
        ),
        "experiment": scenario["id"],
        "failure_type": scenario["failure_type"],
        "target_service": scenario["target_service"],
        "description": scenario["description"],
        "chaos_injected": state["chaos_injected"],
        "impact_observed": state["impact_observed"],
        "mitigation_steps_available": [
            {"step": s["step"], "description": s["description"]}
            for s in scenario["mitigation_steps"]
            if s["step"] not in state["mitigation_steps_completed"]
        ],
        "mitigation_steps_completed": state["mitigation_steps_completed"],
        "remaining_steps": len(scenario["correct_order"])
        - len(state["mitigation_steps_completed"]),
        "final_state": state["final_state"],
    }
    logs = [
        f"Chaos experiment: {scenario['description']}",
    ]
    if state["chaos_injected"]:
        logs.append(
            f"FAILURE INJECTED: {scenario['failure_type']} on {scenario['target_service']}"
        )
    if state["mitigation_steps_completed"]:
        logs.append(
            f"Mitigation progress: {len(state['mitigation_steps_completed'])}/{len(scenario['correct_order'])} steps"
        )

    return SREObservation(
        task_id=task_id,
        step=step_count,
        context=context,
        available_actions=CHAOS_ENGINEERING_INFO["available_actions"],
        alert_queue=[],
        service_map=service_map,
        metrics=visible_impact,
        logs=logs,
        done=done,
        message=message,
    )


def is_chaos_engineering_done(
    state: dict[str, Any], step_count: int, max_steps: int
) -> bool:
    scenario = state["scenario"]
    return (
        len(state["mitigation_steps_completed"]) == len(scenario["correct_order"])
        or step_count >= max_steps
    )
