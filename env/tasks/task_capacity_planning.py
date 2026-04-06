from __future__ import annotations

from copy import deepcopy
from typing import Any

from env.models import SREAction, SREObservation

CAPACITY_PLANNING_INFO = {
    "id": "capacity_planning",
    "name": "Capacity Planning",
    "difficulty": "easy",
    "description": "Analyze service metrics trends and recommend scaling decisions.",
    "max_steps": 5,
    "available_actions": ["query_capacity", "recommend_scaling", "escalate", "resolve"],
}

CAPACITY_SCENARIOS = [
    {
        "service": "api-gateway",
        "current_replicas": 4,
        "metrics": {
            "cpu_avg": 72,
            "cpu_p95": 89,
            "mem_avg": 65,
            "mem_p95": 78,
            "latency_p99": 180,
            "rps": 12000,
        },
        "trend": "increasing",
        "growth_rate_pct": 15,
        "peak_event": "Black Friday sale in 2 weeks",
        "correct_recommendation": "scale_out",
        "target_replicas": 6,
    },
    {
        "service": "db-service",
        "current_replicas": 3,
        "metrics": {
            "cpu_avg": 45,
            "cpu_p95": 55,
            "mem_avg": 70,
            "mem_p95": 75,
            "latency_p99": 30,
            "rps": 8000,
        },
        "trend": "stable",
        "growth_rate_pct": 2,
        "peak_event": None,
        "correct_recommendation": "no_change",
        "target_replicas": 3,
    },
    {
        "service": "payment-service",
        "current_replicas": 6,
        "metrics": {
            "cpu_avg": 35,
            "cpu_p95": 42,
            "mem_avg": 48,
            "mem_p95": 55,
            "latency_p99": 95,
            "rps": 5000,
        },
        "trend": "decreasing",
        "growth_rate_pct": -5,
        "peak_event": None,
        "correct_recommendation": "scale_in",
        "target_replicas": 4,
    },
    {
        "service": "auth-service",
        "current_replicas": 3,
        "metrics": {
            "cpu_avg": 88,
            "cpu_p95": 97,
            "mem_avg": 82,
            "mem_p95": 91,
            "latency_p99": 210,
            "rps": 15000,
        },
        "trend": "increasing",
        "growth_rate_pct": 25,
        "peak_event": "Product launch next week",
        "correct_recommendation": "scale_out_urgent",
        "target_replicas": 6,
    },
]


def init_capacity_planning_task(
    catalogs: dict[str, Any], service_map: dict[str, list[str]], rng
) -> dict[str, Any]:
    scenario = deepcopy(rng.choice(CAPACITY_SCENARIOS))
    return {
        "task": "capacity_planning",
        "scenario": scenario,
        "queries_made": [],
        "recommendation": None,
        "escalated": False,
        "invalid_actions": 0,
        "service_map": service_map,
        "message": (
            "Analyze the capacity metrics for the target service. Query capacity data "
            "first, then recommend a scaling action. Use action_type='query_capacity' "
            "to get metrics, then action_type='recommend_scaling' with parameters "
            "containing your recommendation (scale_out, scale_in, no_change, or "
            "scale_out_urgent) and target replica count."
        ),
    }


def apply_capacity_planning_action(
    state: dict[str, Any], action: SREAction, step_count: int
) -> str:
    scenario = state["scenario"]

    if action.action_type == "escalate":
        state["escalated"] = True
        return f"Capacity planning for {scenario['service']} escalated to the infrastructure team."

    if action.action_type == "resolve":
        if state["recommendation"]:
            return "Recommendation already submitted; waiting for episode termination."
        state["invalid_actions"] += 1
        return "Resolve is only meaningful after submitting a scaling recommendation."

    if action.action_type == "query_capacity":
        if action.target not in {scenario["service"], "all"}:
            state["invalid_actions"] += 1
            return f"Query must target '{scenario['service']}' or 'all'."
        if action.target not in state["queries_made"]:
            state["queries_made"].append(action.target)
        return (
            f"Capacity data for {scenario['service']}: "
            f"replicas={scenario['current_replicas']}, "
            f"cpu_avg={scenario['metrics']['cpu_avg']}%, "
            f"cpu_p95={scenario['metrics']['cpu_p95']}%, "
            f"mem_avg={scenario['metrics']['mem_avg']}%, "
            f"mem_p95={scenario['metrics']['mem_p95']}%, "
            f"latency_p99={scenario['metrics']['latency_p99']}ms, "
            f"rps={scenario['metrics']['rps']}, "
            f"trend={scenario['trend']}, "
            f"growth_rate={scenario['growth_rate_pct']}%."
            + (
                f" Upcoming event: {scenario['peak_event']}."
                if scenario["peak_event"]
                else ""
            )
        )

    if action.action_type == "recommend_scaling":
        recommendation = str(action.parameters.get("recommendation", "")).lower()
        target_replicas = action.parameters.get("target_replicas")
        if target_replicas is not None:
            try:
                target_replicas = int(target_replicas)
            except (ValueError, TypeError):
                target_replicas = None

        state["recommendation"] = {
            "recommendation": recommendation,
            "target_replicas": target_replicas,
            "service": scenario["service"],
            "step": step_count + 1,
        }
        return (
            f"Scaling recommendation submitted: {recommendation} to "
            f"{target_replicas} replicas for {scenario['service']}."
        )

    state["invalid_actions"] += 1
    return f"Action {action.action_type} is not supported for capacity planning."


def build_capacity_planning_observation(
    task_id: str,
    step_count: int,
    state: dict[str, Any],
    service_map: dict[str, list[str]],
    done: bool,
    message: str,
) -> SREObservation:
    scenario = state["scenario"]
    visible_metrics = {}
    if scenario["service"] in state["queries_made"] or "all" in state["queries_made"]:
        visible_metrics = {scenario["service"]: scenario["metrics"]}

    context = {
        "instruction": (
            "Analyze capacity metrics and recommend a scaling decision. "
            "Query capacity data first, then recommend: scale_out, scale_in, "
            "no_change, or scale_out_urgent with a target replica count."
        ),
        "service": scenario["service"],
        "current_replicas": scenario["current_replicas"],
        "trend": scenario["trend"],
        "growth_rate_pct": scenario["growth_rate_pct"],
        "peak_event": scenario["peak_event"],
        "queries_made": state["queries_made"],
        "recommendation_submitted": state["recommendation"] is not None,
    }
    logs = [
        f"Capacity review requested for {scenario['service']}",
        f"Traffic trend: {scenario['trend']} ({scenario['growth_rate_pct']}% growth)",
    ]
    if scenario["peak_event"]:
        logs.append(f"Upcoming peak event: {scenario['peak_event']}")

    return SREObservation(
        task_id=task_id,
        step=step_count,
        context=context,
        available_actions=CAPACITY_PLANNING_INFO["available_actions"],
        alert_queue=[],
        service_map=service_map,
        metrics=visible_metrics,
        logs=logs,
        done=done,
        message=message,
    )


def is_capacity_planning_done(
    state: dict[str, Any], step_count: int, max_steps: int
) -> bool:
    return state["recommendation"] is not None or step_count >= max_steps
