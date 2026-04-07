from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from env.graders import (
    grade_alert_triage,
    grade_auto_remediation,
    grade_blameless_postmortem,
    grade_capacity_planning,
    grade_chaos_engineering,
    grade_incident_diagnosis,
    grade_multi_incident_correlation,
    grade_on_call_handoff,
    grade_runbook_execution,
)
from env.models import SREAction, SREObservation, SREReward
from env.tasks import (
    ALERT_TRIAGE_INFO,
    AUTO_REMEDIATION_INFO,
    BLAMELESS_POSTMORTEM_INFO,
    CAPACITY_PLANNING_INFO,
    CHAOS_ENGINEERING_INFO,
    INCIDENT_DIAGNOSIS_INFO,
    MULTI_INCIDENT_CORRELATION_INFO,
    ON_CALL_HANDOFF_INFO,
    RUNBOOK_EXECUTION_INFO,
    apply_alert_triage_action,
    apply_auto_remediation_action,
    apply_blameless_postmortem_action,
    apply_capacity_planning_action,
    apply_chaos_engineering_action,
    apply_incident_diagnosis_action,
    apply_multi_incident_correlation_action,
    apply_on_call_handoff_action,
    apply_runbook_execution_action,
    build_alert_triage_observation,
    build_auto_remediation_observation,
    build_blameless_postmortem_observation,
    build_capacity_planning_observation,
    build_chaos_engineering_observation,
    build_incident_diagnosis_observation,
    build_multi_incident_correlation_observation,
    build_on_call_handoff_observation,
    build_runbook_execution_observation,
    init_alert_triage_task,
    init_auto_remediation_task,
    init_blameless_postmortem_task,
    init_capacity_planning_task,
    init_chaos_engineering_task,
    init_incident_diagnosis_task,
    init_multi_incident_correlation_task,
    init_on_call_handoff_task,
    init_runbook_execution_task,
    is_alert_triage_done,
    is_auto_remediation_done,
    is_blameless_postmortem_done,
    is_capacity_planning_done,
    is_chaos_engineering_done,
    is_incident_diagnosis_done,
    is_multi_incident_correlation_done,
    is_on_call_handoff_done,
    is_runbook_execution_done,
)

DATA_DIR = Path(__file__).resolve().parent / "data"
SERVICE_MAP = {
    "api-gateway": ["auth-service"],
    "auth-service": ["user-service", "payment-service"],
    "user-service": [],
    "payment-service": ["db-service"],
    "db-service": [],
}

TASK_REGISTRY = {
    "alert_triage": {
        "metadata": ALERT_TRIAGE_INFO,
        "reset": init_alert_triage_task,
        "apply": apply_alert_triage_action,
        "build_observation": build_alert_triage_observation,
        "grade": grade_alert_triage,
        "is_done": is_alert_triage_done,
    },
    "on_call_handoff": {
        "metadata": ON_CALL_HANDOFF_INFO,
        "reset": init_on_call_handoff_task,
        "apply": apply_on_call_handoff_action,
        "build_observation": build_on_call_handoff_observation,
        "grade": grade_on_call_handoff,
        "is_done": is_on_call_handoff_done,
    },
    "capacity_planning": {
        "metadata": CAPACITY_PLANNING_INFO,
        "reset": init_capacity_planning_task,
        "apply": apply_capacity_planning_action,
        "build_observation": build_capacity_planning_observation,
        "grade": grade_capacity_planning,
        "is_done": is_capacity_planning_done,
    },
    "incident_diagnosis": {
        "metadata": INCIDENT_DIAGNOSIS_INFO,
        "reset": init_incident_diagnosis_task,
        "apply": apply_incident_diagnosis_action,
        "build_observation": build_incident_diagnosis_observation,
        "grade": grade_incident_diagnosis,
        "is_done": is_incident_diagnosis_done,
    },
    "multi_incident_correlation": {
        "metadata": MULTI_INCIDENT_CORRELATION_INFO,
        "reset": init_multi_incident_correlation_task,
        "apply": apply_multi_incident_correlation_action,
        "build_observation": build_multi_incident_correlation_observation,
        "grade": grade_multi_incident_correlation,
        "is_done": is_multi_incident_correlation_done,
    },
    "auto_remediation": {
        "metadata": AUTO_REMEDIATION_INFO,
        "reset": init_auto_remediation_task,
        "apply": apply_auto_remediation_action,
        "build_observation": build_auto_remediation_observation,
        "grade": grade_auto_remediation,
        "is_done": is_auto_remediation_done,
    },
    "runbook_execution": {
        "metadata": RUNBOOK_EXECUTION_INFO,
        "reset": init_runbook_execution_task,
        "apply": apply_runbook_execution_action,
        "build_observation": build_runbook_execution_observation,
        "grade": grade_runbook_execution,
        "is_done": is_runbook_execution_done,
    },
    "blameless_postmortem": {
        "metadata": BLAMELESS_POSTMORTEM_INFO,
        "reset": init_blameless_postmortem_task,
        "apply": apply_blameless_postmortem_action,
        "build_observation": build_blameless_postmortem_observation,
        "grade": grade_blameless_postmortem,
        "is_done": is_blameless_postmortem_done,
    },
    "chaos_engineering": {
        "metadata": CHAOS_ENGINEERING_INFO,
        "reset": init_chaos_engineering_task,
        "apply": apply_chaos_engineering_action,
        "build_observation": build_chaos_engineering_observation,
        "grade": grade_chaos_engineering,
        "is_done": is_chaos_engineering_done,
    },
}


class SREEnv:
    def __init__(self, task_id: str):
        if task_id not in TASK_REGISTRY:
            raise ValueError(f"Unsupported task_id: {task_id}")
        self.task_id = task_id
        self.step_count = 0
        self.state_data: dict[str, Any] = {}
        self.episode_history: list[dict[str, Any]] = []
        self.cumulative_reward: float = 0.0
        self.catalogs = self._load_catalogs()
        self.rng = random.Random()

    def _load_catalogs(self) -> dict[str, Any]:
        return {
            "alerts": json.loads((DATA_DIR / "alerts.json").read_text()),
            "incidents": json.loads((DATA_DIR / "incidents.json").read_text()),
            "runbooks": json.loads((DATA_DIR / "runbooks.json").read_text()),
        }

    def reset(self) -> SREObservation:
        self.step_count = 0
        self.episode_history = []
        self.cumulative_reward = 0.0
        registry_entry = TASK_REGISTRY[self.task_id]
        self.state_data = registry_entry["reset"](self.catalogs, SERVICE_MAP, self.rng)
        message = self.state_data.get(
            "message", registry_entry["metadata"]["description"]
        )
        return registry_entry["build_observation"](
            self.task_id,
            self.step_count,
            self.state_data,
            SERVICE_MAP,
            False,
            message,
        )

    def step(
        self, action: SREAction
    ) -> tuple[SREObservation, SREReward, bool, dict[str, Any]]:
        registry_entry = TASK_REGISTRY[self.task_id]
        available_actions = registry_entry["metadata"]["available_actions"]

        if action.action_type not in available_actions:
            self.state_data["invalid_actions"] = (
                self.state_data.get("invalid_actions", 0) + 1
            )
            message = (
                f"Action {action.action_type} is not available for task {self.task_id}. "
                f"Allowed actions: {available_actions}."
            )
        else:
            message = registry_entry["apply"](self.state_data, action, self.step_count)

        self.step_count += 1
        done = registry_entry["is_done"](
            self.state_data,
            self.step_count,
            registry_entry["metadata"]["max_steps"],
        )
        reward = registry_entry["grade"](self.state_data, self.step_count, done)
        self.cumulative_reward = max(
            0.0001, min(0.9999, round(self.cumulative_reward + reward.value, 4))
        )
        reward = SREReward(
            value=reward.value,
            breakdown=reward.breakdown,
            done=done,
            info={
                **reward.info,
                "cumulative_score": self.cumulative_reward,
                "step_count": self.step_count,
            },
        )
        info = {
            "task_id": self.task_id,
            "cumulative_score": self.cumulative_reward,
            "max_steps": registry_entry["metadata"]["max_steps"],
            "termination_reason": self._termination_reason(done),
        }
        observation = registry_entry["build_observation"](
            self.task_id,
            self.step_count,
            self.state_data,
            SERVICE_MAP,
            done,
            message,
        )
        self.episode_history.append(
            {
                "step": self.step_count,
                "action": action.model_dump(),
                "reward": reward.model_dump(),
                "done": done,
                "info": info,
            }
        )
        return observation, reward, done, info

    def _termination_reason(self, done: bool) -> str | None:
        if not done:
            return None
        max_steps = TASK_REGISTRY[self.task_id]["metadata"]["max_steps"]
        if self.step_count >= max_steps:
            return "max_steps_reached"
        if self.task_id == "alert_triage":
            return "all_actionable_alerts_acknowledged"
        if self.task_id == "on_call_handoff":
            return "handoff_summary_submitted"
        if self.task_id == "capacity_planning":
            return "scaling_recommendation_submitted"
        if self.task_id == "incident_diagnosis":
            return "diagnosis_submitted"
        if self.task_id == "multi_incident_correlation":
            return "correlation_submitted"
        if self.task_id == "auto_remediation":
            return "remediation_cycle_complete"
        if self.task_id == "runbook_execution":
            return "runbook_completed"
        if self.task_id == "blameless_postmortem":
            return "postmortem_sections_complete"
        if self.task_id == "chaos_engineering":
            return "chaos_mitigation_complete"
        return "done"

    def state(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "step_count": self.step_count,
            "state_data": self.state_data,
            "episode_history": self.episode_history,
        }

    def close(self):
        self.state_data = {}
        self.episode_history = []


TASK_METADATA = [TASK_REGISTRY[task_id]["metadata"] for task_id in TASK_REGISTRY]
