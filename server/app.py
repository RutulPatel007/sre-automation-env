from __future__ import annotations

import time
from collections import OrderedDict
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from env.models import SREAction
from env.sre_env import SREEnv, TASK_METADATA

app = FastAPI(title="sre-automation-env", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_SESSIONS = 200
SESSION_TTL_SECONDS = 600  # 10 minutes


class _SessionEntry:
    __slots__ = ("env", "created_at", "last_active")

    def __init__(self, env: SREEnv):
        self.env = env
        self.created_at = time.time()
        self.last_active = self.created_at

    def touch(self) -> None:
        self.last_active = time.time()

    @property
    def expired(self) -> bool:
        return (time.time() - self.last_active) > SESSION_TTL_SECONDS


SESSIONS: OrderedDict[str, _SessionEntry] = OrderedDict()


def _evict_stale_sessions() -> None:
    """Remove expired sessions and enforce max session count."""
    now = time.time()
    expired = [
        sid for sid, entry in SESSIONS.items()
        if (now - entry.last_active) > SESSION_TTL_SECONDS
    ]
    for sid in expired:
        entry = SESSIONS.pop(sid, None)
        if entry:
            entry.env.close()

    while len(SESSIONS) > MAX_SESSIONS:
        sid, entry = SESSIONS.popitem(last=False)
        entry.env.close()


def _get_session(session_id: str) -> _SessionEntry:
    entry = SESSIONS.get(session_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Unknown session_id")
    if entry.expired:
        SESSIONS.pop(session_id, None)
        entry.env.close()
        raise HTTPException(status_code=410, detail="Session expired")
    entry.touch()
    return entry


class ResetRequest(BaseModel):
    task_id: Literal["alert_triage", "incident_diagnosis", "runbook_execution"] = "alert_triage"


class StepRequest(BaseModel):
    session_id: str = ""
    action: SREAction | None = None


@app.post("/reset")
def reset_environment(request: ResetRequest | None = None) -> dict:
    _evict_stale_sessions()
    session_id = str(uuid4())
    task_id = request.task_id if request else "alert_triage"
    env = SREEnv(task_id=task_id)
    observation = env.reset()
    SESSIONS[session_id] = _SessionEntry(env)
    return {"session_id": session_id, **observation.model_dump()}


@app.post("/step")
def step_environment(request: StepRequest | None = None) -> dict:
    if not request or not request.session_id:
        raise HTTPException(status_code=400, detail="Missing session_id in request body")
    
    entry = _get_session(request.session_id)
    action = request.action
    if not action:
        # Fallback empty action if tester sends malformed action
        action = SREAction(
            action_type="diagnose",
            target="api-gateway",
            parameters={},
            reasoning="fallback action due to missing action body"
        )
        
    observation, reward, done, info = entry.env.step(action)
    if done:
        # Clean up completed sessions after a small delay
        SESSIONS.pop(request.session_id, None)
    return {
        "observation": observation.model_dump(),
        "reward": reward.model_dump(),
        "done": done,
        "info": info,
    }


@app.get("/state")
def get_state(session_id: str = Query(...)) -> dict:
    entry = _get_session(session_id)
    return entry.env.state()


@app.get("/tasks")
def list_tasks() -> list[dict]:
    return TASK_METADATA


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
