from __future__ import annotations

from env.models import SREReward


def _clamp(value: float) -> float:
    return max(0.0001, min(0.9999, round(value, 4)))


def _report_quality(report: dict | None) -> float:
    if not report:
        return 0.0
    summary = str(report.get("summary", "")).lower()
    severity = str(report.get("severity", "")).upper()
    has_severity = severity == "P2"
    has_service = "payment-service" in summary
    has_resolution_language = any(
        keyword in summary
        for keyword in ["scaled", "recovered", "cordon", "heap dump", "memory pressure"]
    )
    coherent_sentence = len(summary.split()) >= 6 and summary.endswith((".", "!", "?"))
    return (
        0.1
        if has_severity
        and has_service
        and has_resolution_language
        and coherent_sentence
        else 0.0
    )


def grade_runbook_execution(state: dict, step_count: int, done: bool) -> SREReward:
    completed_count = len(state["completed_steps"])
    step_score = min(0.7, 0.1 * completed_count)
    pid_bonus = 0.1 if state.get("pid_dependency_ok") else 0.0
    report_bonus = _report_quality(state.get("report_submitted"))
    out_of_order_penalty = 0.05 * state.get("out_of_order_attempts", 0)
    wrong_parameter_penalty = 0.05 * state.get("wrong_parameter_attempts", 0)
    invalid_penalty = 0.02 * state.get("invalid_actions", 0)

    total = (
        step_score
        + pid_bonus
        + report_bonus
        - out_of_order_penalty
        - wrong_parameter_penalty
        - invalid_penalty
    )
    total = _clamp(total)

    breakdown = {
        "completed_steps": state["completed_steps"],
        "step_score": round(step_score, 4),
        "pid_dependency_bonus": round(pid_bonus, 4),
        "report_quality_bonus": round(report_bonus, 4),
        "out_of_order_penalty": round(out_of_order_penalty, 4),
        "wrong_parameter_penalty": round(wrong_parameter_penalty, 4),
        "invalid_action_penalty": round(invalid_penalty, 4),
        "score_explanation": (
            "The runbook score is dense: every correct step adds credit, but ordering "
            "mistakes and bad parameters reduce the final score."
        ),
    }
    return SREReward(value=total, breakdown=breakdown, done=done, info={})
