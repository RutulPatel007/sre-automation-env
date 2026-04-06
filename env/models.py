from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SREObservation(BaseModel):
    task_id: str
    step: int = Field(ge=0)
    context: dict[str, Any]
    available_actions: list[str]
    alert_queue: list[dict[str, Any]]
    service_map: dict[str, list[str]]
    metrics: dict[str, Any]
    logs: list[str]
    done: bool
    message: str


class SREAction(BaseModel):
    action_type: Literal[
        "triage",
        "diagnose",
        "escalate",
        "acknowledge",
        "execute_step",
        "resolve",
        "summarize",
        "query_capacity",
        "recommend_scaling",
        "correlate",
        "remediate",
        "rollback",
        "verify_recovery",
        "write_postmortem",
        "inject_chaos",
        "observe_impact",
        "mitigate_chaos",
    ]
    target: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    reasoning: str


class SREReward(BaseModel):
    value: float = Field(ge=0.0, le=1.0)
    breakdown: dict[str, Any] = Field(default_factory=dict)
    done: bool
    info: dict[str, Any] = Field(default_factory=dict)
