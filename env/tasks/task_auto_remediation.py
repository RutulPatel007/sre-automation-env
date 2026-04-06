from __future__ import annotations

from copy import deepcopy
from typing import Any

from env.models import SREAction, SREObservation

AUTO_REMEDIATION_INFO = {
    "id": "auto_remediation",
    "name": "Auto-Remediation with Rollback",
    "difficulty": "medium",
    "description": "Execute a remediation action, verify if it improved the situation, and rollback if it made things worse.",
    "max_steps": 8,
    "available_actions": [
        "remediate",
        "verify_recovery",
        "rollback",
        "escalate",
        "resolve",
    ],
}

REMEDIATION_SCENARIOS = [
    {
        "id": "REM-A",
        "service": "api-gateway",
        "symptom": "5xx rate > 15% after config change",
        "root_cause": "config drift to wrong upstream",
        "remediation_options": [
            {
                "action": "reload_config",
                "effect": "worse",
                "description": "Reload config without reverting",
            },
            {
                "action": "rollback_config",
                "effect": "fix",
                "description": "Revert to previous config version",
            },
            {
                "action": "restart_service",
                "effect": "worse",
                "description": "Restart with current bad config",
            },
            {
                "action": "scale_out",
                "effect": "partial",
                "description": "Add more instances (masks symptom)",
            },
        ],
        "correct_action": "rollback_config",
        "post_fix_metrics": {"error_rate": 0.01, "latency_p99": 120},
        "current_metrics": {"error_rate": 0.18, "latency_p99": 350},
    },
    {
        "id": "REM-B",
        "service": "payment-service",
        "symptom": "Memory leak causing OOM restarts every 30 minutes",
        "root_cause": "memory leak in checkout worker",
        "remediation_options": [
            {
                "action": "increase_memory_limit",
                "effect": "partial",
                "description": "Raise memory ceiling (delays but doesn't fix)",
            },
            {
                "action": "restart_service",
                "effect": "partial",
                "description": "Restart clears memory temporarily",
            },
            {
                "action": "cordon_and_scale",
                "effect": "fix",
                "description": "Cordon affected instance, scale out replacement",
            },
            {
                "action": "disable_checkout",
                "effect": "worse",
                "description": "Disable checkout feature entirely",
            },
        ],
        "correct_action": "cordon_and_scale",
        "post_fix_metrics": {"error_rate": 0.01, "latency_p99": 110, "mem_pct": 65},
        "current_metrics": {"error_rate": 0.12, "latency_p99": 280, "mem_pct": 94},
    },
    {
        "id": "REM-C",
        "service": "auth-service",
        "symptom": "JWT validation failures after key rotation",
        "root_cause": "new signing key not propagated to all pods",
        "remediation_options": [
            {
                "action": "force_key_rotation",
                "effect": "worse",
                "description": "Rotate keys again (makes it worse)",
            },
            {
                "action": "propagate_keys",
                "effect": "fix",
                "description": "Manually sync signing keys across all pods",
            },
            {
                "action": "restart_service",
                "effect": "partial",
                "description": "Restart may pick up new keys on some pods",
            },
            {
                "action": "disable_auth",
                "effect": "worse",
                "description": "Disable authentication (security risk)",
            },
        ],
        "correct_action": "propagate_keys",
        "post_fix_metrics": {"error_rate": 0.008, "latency_p99": 95},
        "current_metrics": {"error_rate": 0.24, "latency_p99": 180},
    },
]


def init_auto_remediation_task(
    catalogs: dict[str, Any], service_map: dict[str, list[str]], rng
) -> dict[str, Any]:
    scenario = deepcopy(rng.choice(REMEDIATION_SCENARIOS))
    return {
        "task": "auto_remediation",
        "scenario": scenario,
        "remediation_attempted": None,
        "recovery_verified": False,
        "rollback_performed": False,
        "final_state": None,
        "escalated": False,
        "invalid_actions": 0,
        "service_map": service_map,
        "message": (
            "A production incident requires remediation. Choose a remediation action, "
            "verify if it improved metrics, and rollback if it made things worse. "
            "Use action_type='remediate' with the action name, then "
            "action_type='verify_recovery' to check results. If the fix made things "
            "worse, use action_type='rollback'."
        ),
    }


def apply_auto_remediation_action(
    state: dict[str, Any], action: SREAction, step_count: int
) -> str:
    scenario = state["scenario"]

    if action.action_type == "escalate":
        state["escalated"] = True
        return f"Remediation for {scenario['service']} escalated to senior SRE."

    if action.action_type == "resolve":
        if state["final_state"]:
            return "Remediation episode already concluded."
        state["invalid_actions"] += 1
        return "Resolve is only meaningful after completing the remediation cycle."

    if action.action_type == "remediate":
        chosen_action = str(action.parameters.get("action", "")).strip()
        if not chosen_action:
            state["invalid_actions"] += 1
            return "Must specify an action in parameters."
        valid_options = {opt["action"] for opt in scenario["remediation_options"]}
        if chosen_action not in valid_options:
            state["invalid_actions"] += 1
            return f"Invalid remediation action. Options: {sorted(valid_options)}."

        opt = next(
            o for o in scenario["remediation_options"] if o["action"] == chosen_action
        )
        state["remediation_attempted"] = {
            "action": chosen_action,
            "effect": opt["effect"],
            "description": opt["description"],
            "step": step_count + 1,
        }
        return (
            f"Remediation '{chosen_action}' executed: {opt['description']}. "
            f"Use action_type='verify_recovery' to check results."
        )

    if action.action_type == "verify_recovery":
        if not state["remediation_attempted"]:
            state["invalid_actions"] += 1
            return "No remediation has been attempted yet."

        effect = state["remediation_attempted"]["effect"]
        if effect == "fix":
            state["recovery_verified"] = True
            state["final_state"] = {
                "outcome": "success",
                "metrics": scenario["post_fix_metrics"],
                "step": step_count + 1,
            }
            return (
                f"Recovery verified! Metrics improved: {scenario['post_fix_metrics']}. "
                f"Remediation was successful."
            )
        elif effect == "partial":
            state["recovery_verified"] = True
            state["final_state"] = {
                "outcome": "partial",
                "metrics": scenario["current_metrics"],
                "note": "Symptom masked but root cause persists",
                "step": step_count + 1,
            }
            return (
                "Partial improvement detected. Symptoms reduced but root cause "
                "not addressed. Consider trying a different remediation or rollback."
            )
        else:
            state["recovery_verified"] = True
            state["final_state"] = {
                "outcome": "worse",
                "metrics": scenario["current_metrics"],
                "note": "Metrics degraded after remediation",
                "step": step_count + 1,
            }
            return (
                "CRITICAL: Metrics degraded after remediation! "
                "Use action_type='rollback' to revert immediately."
            )

    if action.action_type == "rollback":
        if not state["remediation_attempted"]:
            state["invalid_actions"] += 1
            return "No remediation to rollback."
        state["rollback_performed"] = True
        state["final_state"] = {
            "outcome": "rolled_back",
            "metrics": scenario["current_metrics"],
            "original_action": state["remediation_attempted"]["action"],
            "step": step_count + 1,
        }
        return (
            f"Rollback of '{state['remediation_attempted']['action']}' completed. "
            f"System restored to pre-remediation state."
        )

    state["invalid_actions"] += 1
    return f"Action {action.action_type} is not supported for auto-remediation."


def build_auto_remediation_observation(
    task_id: str,
    step_count: int,
    state: dict[str, Any],
    service_map: dict[str, list[str]],
    done: bool,
    message: str,
) -> SREObservation:
    scenario = state["scenario"]
    context = {
        "instruction": (
            "Choose a remediation action, verify its effect, and rollback if needed. "
            "The correct action will fix the root cause. Wrong actions may make things "
            "worse or only partially help."
        ),
        "service": scenario["service"],
        "symptom": scenario["symptom"],
        "root_cause": scenario["root_cause"],
        "current_metrics": scenario["current_metrics"],
        "remediation_options": [
            {"action": opt["action"], "description": opt["description"]}
            for opt in scenario["remediation_options"]
        ],
        "remediation_attempted": state["remediation_attempted"],
        "recovery_verified": state["recovery_verified"],
        "rollback_performed": state["rollback_performed"],
        "final_state": state["final_state"],
    }
    logs = [
        f"ALERT: {scenario['symptom']}",
        f"Root cause hypothesis: {scenario['root_cause']}",
    ]
    if state["remediation_attempted"]:
        logs.append(f"Attempted: {state['remediation_attempted']['action']}")
    if state["final_state"]:
        logs.append(f"Outcome: {state['final_state']['outcome']}")

    return SREObservation(
        task_id=task_id,
        step=step_count,
        context=context,
        available_actions=AUTO_REMEDIATION_INFO["available_actions"],
        alert_queue=[],
        service_map=service_map,
        metrics={"service": scenario["current_metrics"]},
        logs=logs,
        done=done,
        message=message,
    )


def is_auto_remediation_done(
    state: dict[str, Any], step_count: int, max_steps: int
) -> bool:
    return state["final_state"] is not None or step_count >= max_steps
