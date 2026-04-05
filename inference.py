"""
STRICT FORMAT - do not deviate from [START]/[STEP]/[END] lines.
All three tasks must run sequentially.
"""

import json
import os
import re
import time

import httpx
from openai import OpenAI

API_BASE_URL = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "Qwen/Qwen2.5-72B-Instruct")
HF_TOKEN = os.getenv("HF_TOKEN")
ENV_URL = os.getenv("ENV_URL", "http://localhost:7860")

TASKS = ["alert_triage", "incident_diagnosis", "runbook_execution"]
MAX_STEPS = {"alert_triage": 10, "incident_diagnosis": 12, "runbook_execution": 15}
BENCHMARK = "sre-automation-env"

client = OpenAI(base_url=API_BASE_URL, api_key=HF_TOKEN or "hf_token_not_set")

# ---------------------------------------------------------------------------
# Task-specific system prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_BASE = """\
You are an expert Site Reliability Engineer AI agent.
You receive observations from a simulated SRE environment and must
respond with a valid JSON action object. Always respond with ONLY
valid JSON matching this schema:
{
  "action_type": "<one of the available actions>",
  "target": "<service name or alert id>",
  "parameters": {},
  "reasoning": "<one sentence explaining your decision>"
}
Do NOT wrap your response in markdown code blocks. Output raw JSON only."""

SYSTEM_PROMPT_ALERT_TRIAGE = SYSTEM_PROMPT_BASE + """

TASK: Alert Triage
You have a queue of firing alerts. Your goal is to:
1. First, TRIAGE each alert: use action_type="triage" with target=<alert_id> and
   parameters={"decision": "ignore", "priority": "P3"} for flapping or duplicate alerts.
   Use {"decision": "actionable", "priority": "P1|P2|P3"} for real alerts.
   Priority mapping: critical->P1, warning->P2, info->P3.
2. Then, ACKNOWLEDGE actionable alerts in priority order (P1 first, then P2, then P3):
   use action_type="acknowledge" with target=<alert_id>.

Key rules:
- Alerts with is_flapping=true or is_duplicate=true should be triaged as "ignore"
- Critical alerts are P1, warning alerts are P2, info alerts are P3
- Acknowledge P1 alerts first, then P2, then P3
- Do NOT acknowledge flapping or duplicate alerts"""

SYSTEM_PROMPT_INCIDENT = SYSTEM_PROMPT_BASE + """

TASK: Incident Diagnosis
A production incident is in progress across a microservice topology:
  api-gateway -> auth-service -> user-service
                              -> payment-service -> db-service

Your goal is to identify the ROOT CAUSE service and its failure mode.
Strategy:
1. Check the SLO status and incident timeline in the context first
2. Query metrics for services showing the highest SLO burn rates (action_type="diagnose",
   target=<service>, parameters={"operation": "query_metrics"})
3. Query logs for the most suspicious services (parameters={"operation": "query_logs"})
4. Work backwards through the dependency chain — the true root cause is usually the
   furthest downstream service with anomalous metrics
5. Submit diagnosis (parameters={"operation": "submit_diagnosis", "failure_mode": "<mode>"})

Failure modes: "high latency", "high error rate", "memory leak", "config drift",
"deprecated endpoint dependency"

Be efficient: query no more than 3-4 services before submitting your diagnosis."""

SYSTEM_PROMPT_RUNBOOK = SYSTEM_PROMPT_BASE + """

TASK: Runbook Execution
You must execute a runbook for "High memory pressure - payment-service" in STRICT order.
Each step uses action_type="execute_step" with target=<step_name>.

Steps IN ORDER:
1. check_memory_usage — params: {"service": "payment-service"}
2. identify_top_processes — params: {"service": "payment-service"}
3. capture_heap_dump — params: {"service": "payment-service", "pid": <pid from step 2>}
4. cordon_instance — params: {"instance_id": "<instance_id from step 2>"}
5. scale_out — params: {"service": "payment-service", "replicas": 2}
6. verify_recovery — params: {"service": "payment-service", "wait_seconds": 30}
7. file_incident_report — params: {"severity": "P2", "summary": "<your summary>"}

CRITICAL: After step 2, read the tool_outputs carefully to extract the pid and instance_id.
These MUST be used in steps 3 and 4. The summary in step 7 must mention payment-service
and describe what was done (e.g., memory pressure, scaled out, recovered)."""

TASK_PROMPTS = {
    "alert_triage": SYSTEM_PROMPT_ALERT_TRIAGE,
    "incident_diagnosis": SYSTEM_PROMPT_INCIDENT,
    "runbook_execution": SYSTEM_PROMPT_RUNBOOK,
}

TASK_FALLBACK = {
    "alert_triage": lambda obs: {
        "action_type": "acknowledge",
        "target": (obs.get("alert_queue", [{}])[0] or {}).get("id", "ALT-001"),
        "parameters": {},
        "reasoning": "fallback: acknowledging first available alert",
    },
    "incident_diagnosis": lambda obs: {
        "action_type": "diagnose",
        "target": "db-service",
        "parameters": {"operation": "query_metrics"},
        "reasoning": "fallback: querying deepest service in dependency chain",
    },
    "runbook_execution": lambda obs: {
        "action_type": "execute_step",
        "target": (obs.get("context", {}).get("next_expected_step") or {}).get(
            "name", "check_memory_usage"
        ),
        "parameters": {"service": "payment-service"},
        "reasoning": "fallback: attempting next expected runbook step",
    },
}

# ---------------------------------------------------------------------------
# JSON extraction helpers
# ---------------------------------------------------------------------------


def _extract_json(raw: str) -> dict | None:
    """Extract JSON from raw LLM output, handling markdown code blocks."""
    text = raw.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Extract from markdown code blocks: ```json ... ``` or ``` ... ```
    code_block_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if code_block_match:
        try:
            return json.loads(code_block_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try to find a JSON object anywhere in the text
    brace_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


# ---------------------------------------------------------------------------
# Episode runner
# ---------------------------------------------------------------------------

MAX_RETRIES = 2


def run_episode(task_id: str):
    resp = httpx.post(f"{ENV_URL}/reset", json={"task_id": task_id}, timeout=30)
    resp.raise_for_status()
    obs = resp.json()
    session_id = obs.get("session_id", task_id)

    print(f"[START] task={task_id} env={BENCHMARK} model={MODEL_NAME}")

    rewards = []
    done = False
    step = 0
    score = 0.0
    last_error = "null"
    system_prompt = TASK_PROMPTS[task_id]
    conversation = [{"role": "system", "content": system_prompt}]

    while not done and step < MAX_STEPS[task_id]:
        # Build user message from current observation
        user_msg = f"Current observation:\n{json.dumps(obs, indent=2)}\n\nWhat action do you take?"
        conversation.append({"role": "user", "content": user_msg})

        # Call LLM with retries
        action = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                completion = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=conversation,
                    max_tokens=400,
                    temperature=0.1,
                )
                raw = completion.choices[0].message.content.strip()
                action = _extract_json(raw)
                if action:
                    last_error = "null"
                    # Store the assistant response for conversation history
                    conversation.append({"role": "assistant", "content": json.dumps(action)})
                    break
                else:
                    last_error = "json_extraction_failed"
            except Exception as e:
                last_error = f"llm_error:{type(e).__name__}"
                if attempt < MAX_RETRIES:
                    time.sleep(1)

        if not action:
            action = TASK_FALLBACK[task_id](obs)
            last_error = last_error or "fallback_used"
            conversation.append({"role": "assistant", "content": json.dumps(action)})

        # Ensure required fields exist
        action.setdefault("action_type", "diagnose")
        action.setdefault("target", "")
        action.setdefault("parameters", {})
        action.setdefault("reasoning", "")

        # Step the environment
        try:
            step_resp = httpx.post(
                f"{ENV_URL}/step",
                json={"session_id": session_id, "action": action},
                timeout=30,
            )
            step_resp.raise_for_status()
            result = step_resp.json()
        except Exception as e:
            last_error = f"env_error:{type(e).__name__}"
            step += 1
            rewards.append(0.0)
            print(
                f"[STEP] step={step} action={action.get('action_type', '?')}({action.get('target', '?')}) "
                f"reward=0.00 done=false error={last_error}"
            )
            continue

        obs = result["observation"]
        reward_val = result["reward"]["value"]
        done = result["done"]
        score = result.get("info", {}).get("cumulative_score", reward_val)

        rewards.append(reward_val)
        step += 1

        print(
            f"[STEP] step={step} action={action['action_type']}({action['target']}) "
            f"reward={reward_val:.2f} done={str(done).lower()} error={last_error}"
        )

        # Trim conversation history if too long (keep system + last 6 exchanges)
        if len(conversation) > 13:
            conversation = [conversation[0]] + conversation[-12:]

    success = score >= 0.5
    rewards_str = ",".join(f"{reward:.2f}" for reward in rewards)
    print(
        f"[END] success={str(success).lower()} steps={step} "
        f"score={score:.2f} rewards={rewards_str}"
    )
    return score


if __name__ == "__main__":
    for task in TASKS:
        run_episode(task)
