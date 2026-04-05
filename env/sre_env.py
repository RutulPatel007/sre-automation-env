from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from env.graders import (
    grade_alert_triage,
    grade_incident_diagnosis,
    grade_runbook_execution,
)
from env.models import SREAction, SREObservation, SREReward
from env.tasks import (
    ALERT_TRIAGE_INFO,
    INCIDENT_DIAGNOSIS_INFO,
    RUNBOOK_EXECUTION_INFO,
    apply_alert_triage_action,
    apply_incident_diagnosis_action,
    apply_runbook_execution_action,
    build_alert_triage_observation,
    build_incident_diagnosis_observation,
    build_runbook_execution_observation,
    init_alert_triage_task,
    init_incident_diagnosis_task,
    init_runbook_execution_task,
    is_alert_triage_done,
    is_incident_diagnosis_done,
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
    "incident_diagnosis": {
        "metadata": INCIDENT_DIAGNOSIS_INFO,
        "reset": init_incident_diagnosis_task,
        "apply": apply_incident_diagnosis_action,
        "build_observation": build_incident_diagnosis_observation,
        "grade": grade_incident_diagnosis,
        "is_done": is_incident_diagnosis_done,
    },
    "runbook_execution": {
        "metadata": RUNBOOK_EXECUTION_INFO,
        "reset": init_runbook_execution_task,
        "apply": apply_runbook_execution_action,
        "build_observation": build_runbook_execution_observation,
        "grade": grade_runbook_execution,
        "is_done": is_runbook_execution_done,
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

    def step(self, action: SREAction) -> tuple[SREObservation, SREReward, bool, dict[str, Any]]:
        registry_entry = TASK_REGISTRY[self.task_id]
        available_actions = registry_entry["metadata"]["available_actions"]

        if action.action_type not in available_actions:
            self.state_data["invalid_actions"] = self.state_data.get("invalid_actions", 0) + 1
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
        self.cumulative_reward = max(0.0, min(1.0, round(
            self.cumulative_reward + reward.value, 4
        )))
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
        if self.task_id == "incident_diagnosis":
            return "diagnosis_submitted"
        if self.task_id == "runbook_execution":
            return "runbook_completed"
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
