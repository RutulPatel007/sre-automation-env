from __future__ import annotations

from copy import deepcopy
from typing import Any

from env.models import SREAction, SREObservation

RUNBOOK_EXECUTION_INFO = {
    "id": "runbook_execution",
    "name": "Runbook Execution",
    "difficulty": "hard",
    "description": "Execute all runbook steps in order with correct parameters.",
    "max_steps": 15,
    "available_actions": ["execute_step", "resolve", "escalate"],
}


def _normalize_int(value: Any) -> int | None:
    """Coerce an int-like value from JSON (may arrive as str or int)."""
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value == int(value):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip().lstrip("+")
        try:
            return int(stripped)
        except ValueError:
            return None
    return None


def _normalize_replicas(value: Any) -> int | None:
    return _normalize_int(value)


def init_runbook_execution_task(
    catalogs: dict[str, Any], service_map: dict[str, list[str]], rng
) -> dict[str, Any]:
    runbook = deepcopy(catalogs["runbooks"][0])
    pid = rng.randint(4100, 5300)
    instance_id = f"pay-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}"
    memory_pct = rng.randint(91, 97)
    return {
        "task": "runbook_execution",
        "runbook": runbook,
        "current_step_index": 0,
        "completed_steps": [],
        "tool_outputs": {},
        "hidden_values": {
            "pid": pid,
            "instance_id": instance_id,
            "memory_pct": memory_pct,
            "process_name": "python /srv/payment/checkout_worker.py",
        },
        "pid_dependency_ok": False,
        "out_of_order_attempts": 0,
        "wrong_parameter_attempts": 0,
        "invalid_actions": 0,
        "report_submitted": None,
        "escalations": [],
        "message": (
            "Use action_type='execute_step' and set target to the exact next runbook "
            "step name. Each step requires the right parameters and later steps depend "
            "on outputs unlocked by earlier steps."
        ),
        "service_map": service_map,
    }


def apply_runbook_execution_action(
    state: dict[str, Any], action: SREAction, step_count: int
) -> str:
    if action.action_type == "escalate":
        state["escalations"].append(
            {"step": step_count + 1, "target": action.target, "reason": action.reasoning}
        )
        return f"Escalation recorded for {action.target}."

    if action.action_type == "resolve":
        if len(state["completed_steps"]) == len(state["runbook"]["steps"]):
            return "Runbook already complete; episode will terminate automatically."
        state["invalid_actions"] += 1
        return "Resolve cannot skip the remaining runbook steps."

    if action.action_type != "execute_step":
        state["invalid_actions"] += 1
        return "Runbook execution only accepts execute_step, escalate, or resolve."

    if state["current_step_index"] >= len(state["runbook"]["steps"]):
        state["invalid_actions"] += 1
        return "All runbook steps are already complete."

    expected_step = state["runbook"]["steps"][state["current_step_index"]]
    if action.target != expected_step["name"]:
        state["out_of_order_attempts"] += 1
        return (
            f"Out-of-order step. Expected {expected_step['name']} next, "
            f"received {action.target}."
        )

    hidden = state["hidden_values"]
    params = action.parameters
    valid = False
    output: dict[str, Any] = {}

    if action.target == "check_memory_usage":
        valid = params.get("service") == "payment-service"
        output = {
            "service": "payment-service",
            "memory_usage_pct": hidden["memory_pct"],
            "rss_mb": 2147,
            "note": "memory pressure above the 90% mitigation threshold",
        }
    elif action.target == "identify_top_processes":
        valid = params.get("service") == "payment-service"
        output = {
            "service": "payment-service",
            "pid": hidden["pid"],
            "instance_id": hidden["instance_id"],
            "process": hidden["process_name"],
            "memory_mb": 1532,
        }
    elif action.target == "capture_heap_dump":
        submitted_pid = _normalize_int(params.get("pid"))
        valid = (
            params.get("service") == "payment-service"
            and submitted_pid == hidden["pid"]
        )
        if valid:
            state["pid_dependency_ok"] = True
        output = {
            "artifact": f"/tmp/heapdump-payment-{hidden['pid']}.hprof",
            "pid": submitted_pid,
            "captured": bool(valid),
        }
    elif action.target == "cordon_instance":
        submitted_instance = str(params.get("instance_id", "")).strip()
        valid = submitted_instance == hidden["instance_id"]
        output = {
            "instance_id": submitted_instance,
            "status": "cordoned" if valid else "failed",
        }
    elif action.target == "scale_out":
        replicas = _normalize_replicas(params.get("replicas"))
        valid = params.get("service") == "payment-service" and replicas == 2
        output = {
            "service": "payment-service",
            "previous_replicas": 4,
            "current_replicas": 6 if valid else 4,
        }
    elif action.target == "verify_recovery":
        submitted_wait = _normalize_int(params.get("wait_seconds"))
        valid = (
            params.get("service") == "payment-service"
            and submitted_wait == 30
        )
        output = {
            "service": "payment-service",
            "latency_p99": 105,
            "error_rate": 0.012,
            "memory_usage_pct": 68,
            "recovered": bool(valid),
        }
    elif action.target == "file_incident_report":
        summary = str(params.get("summary", "")).strip()
        valid = params.get("severity") == "P2" and bool(summary)
        output = {
            "ticket_id": "INC-2048",
            "severity": params.get("severity"),
            "summary": summary,
        }
        if valid:
            state["report_submitted"] = output

    if not valid:
        state["wrong_parameter_attempts"] += 1
        return (
            f"Step {action.target} used incorrect parameters and did not complete. "
            f"Expected parameters similar to {expected_step['parameters']}."
        )

    state["tool_outputs"][action.target] = output
    state["completed_steps"].append(action.target)
    state["current_step_index"] += 1
    return f"Completed {action.target} successfully."


def build_runbook_execution_observation(
    task_id: str,
    step_count: int,
    state: dict[str, Any],
    service_map: dict[str, list[str]],
    done: bool,
    message: str,
) -> SREObservation:
    next_step = None
    if state["current_step_index"] < len(state["runbook"]["steps"]):
        next_step = state["runbook"]["steps"][state["current_step_index"]]

    context = {
        "instruction": (
            "Execute the runbook in strict order. Use action_type='execute_step', "
            "target the exact next step name, and carry forward required outputs "
            "such as pid and instance_id."
        ),
        "current_runbook": state["runbook"]["name"],
        "completed_steps": state["completed_steps"],
        "next_expected_step": next_step,
        "tool_outputs": deepcopy(state["tool_outputs"]),
        "remaining_steps": len(state["runbook"]["steps"]) - len(state["completed_steps"]),
    }
    logs = [
        "payment-service memory alert is firing on multiple pods",
        "one payment pod was restarted by the kernel OOM killer",
    ]

    return SREObservation(
        task_id=task_id,
        step=step_count,
        context=context,
        available_actions=RUNBOOK_EXECUTION_INFO["available_actions"],
        alert_queue=[],
        service_map=service_map,
        metrics={
            "payment-service": {
                "cpu": 77,
                "mem": state["hidden_values"]["memory_pct"],
                "latency_p99": 245,
                "error_rate": 0.11,
            }
        },
        logs=logs,
        done=done,
        message=message,
    )


def is_runbook_execution_done(
    state: dict[str, Any], step_count: int, max_steps: int
) -> bool:
    return len(state["completed_steps"]) == len(state["runbook"]["steps"]) or step_count >= max_steps
